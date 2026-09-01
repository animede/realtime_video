from __future__ import annotations

import asyncio
import base64
import json
import math
import mimetypes
from pathlib import Path

import httpx

from .config import Settings
from .models import Scene, StoryPlan


SYSTEM = """You are a meticulous character analyst, screenwriter, storyboard artist,
and prompt engineer for a continuous AI-generated film. Inspect the uploaded character
image closely and combine what is visibly present with the user's story direction.
Return one strict JSON object, with no Markdown, using this schema:
{
  "character_description": "detailed English description of identity, face, hair,
    body, clothes, accessories, art/photographic style and invariant traits",
  "synopsis": "concise Japanese story synopsis",
  "scenes": [{
    "title": "short Japanese scene title",
    "prompt": "standalone detailed English video-generation prompt",
    "transition": "continue or cut"
  }]
}
Make exactly the requested number of scenes. Every prompt must restate the invariant
character traits from the image and describe the setting, action, expression, camera,
composition, lighting and smooth motion. Build a coherent dramatic progression from
the user's direction. Prompts must contain no dialogue, subtitles, captions or text.
Use transition=continue unless an intentional location or time change requires cut.
For continue scenes, make the opening action compatible with the previous scene's end."""


async def _llm_request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code not in {502, 503, 504}:
                response.raise_for_status()
                return response
            last_error = RuntimeError(f"Vision LLM temporarily unavailable ({response.status_code})")
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_error = exc
        if attempt < 2:
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Vision LLM failed after 3 attempts: {last_error}") from last_error


def _durations(total: float, count: int) -> list[float]:
    each = round(total / count, 3)
    values = [each] * count
    values[-1] = round(total - sum(values[:-1]), 3)
    return values


def _fallback(scene_count: int, duration: float, clip_duration: float, idea: str) -> StoryPlan:
    beats = [
        ("Arrival", "The character enters the setting and looks around with curious, natural movement; wide establishing shot"),
        ("Discovery", "The character notices something intriguing and approaches it; smooth medium tracking shot"),
        ("Moment", "The character interacts with the discovery with expressive but realistic gestures; intimate close shot"),
        ("Journey", "The character continues forward through the environment; fluid side tracking camera"),
        ("Finale", "The character pauses for a satisfying final moment as the camera slowly pulls back"),
    ]
    context = idea.strip() or "a cinematic, uplifting visual story"
    scenes = []
    durations = _durations(duration, scene_count)
    for i in range(scene_count):
        title, action = beats[min(i * len(beats) // scene_count, len(beats) - 1)]
        length = durations[i]
        scenes.append(Scene(
            index=i,
            title=title,
            duration=round(length, 3),
            prompt=(f"Same character as the reference image, identity and outfit unchanged. {action}. "
                    f"Story context: {context}. Cinematic composition, coherent environment, smooth motion, no text."),
        ))
    return StoryPlan(
        character_description="The character, appearance, outfit, and visual style shown in the reference image",
        synopsis=context,
        scenes=scenes,
    )


def _json_content(response: httpx.Response) -> dict:
    raw = response.json()["choices"][0]["message"]["content"]
    if isinstance(raw, list):
        raw = "".join(part.get("text", "") for part in raw if isinstance(part, dict))
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


async def _model_name(client: httpx.AsyncClient, cfg: Settings) -> str:
    if cfg.llm_model:
        return cfg.llm_model
    response = await _llm_request(client, "GET", cfg.llm_url.rsplit("/chat/completions", 1)[0] + "/models")
    available = response.json().get("data", [])
    if not available:
        raise RuntimeError("Vision LLM server returned no available models")
    return available[0]["id"]


async def _chat_json(client: httpx.AsyncClient, cfg: Settings, model: str, system: str, content) -> dict:
    headers = {"Authorization": f"Bearer {cfg.llm_api_key}"} if cfg.llm_api_key else {}
    response = await _llm_request(client, "POST", cfg.llm_url, headers=headers, json={
        "model": model, "response_format": {"type": "json_object"}, "temperature": .55,
        "max_tokens": 3000, "messages": [{"role": "system", "content": system},
                                            {"role": "user", "content": content}],
    })
    return _json_content(response)


async def _create_plan_staged(image_path: Path, duration: float, clip_duration: float, idea: str,
                              cfg: Settings, scene_paths: list[Path]) -> StoryPlan:
    count = math.ceil(duration / clip_duration)
    images = [image_path, *scene_paths]
    image_content = []
    for index, path in enumerate(images):
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode()
        image_content.extend([
            {"type": "text", "text": "CHARACTER REFERENCE" if index == 0 else f"ORDERED SCENE CHECKPOINT {index}"},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ])
    async with httpx.AsyncClient(timeout=120) as client:
        model = await _model_name(client, cfg)
        analysis = await _chat_json(client, cfg, model,
            "Analyze visual references for a film. Return strict JSON: character_description (detailed English invariant identity) and checkpoint_descriptions (ordered English array). No story writing.",
            image_content)
        character = str(analysis.get("character_description", "")).strip()
        if not character:
            raise RuntimeError("image analysis did not return character_description")
        outline = await _chat_json(client, cfg, model,
            "Write a coherent film outline. Return strict JSON: synopsis (Japanese), scenes array with exactly the requested count; each item has title (Japanese), direction (concise English action/setting/camera), transition (continue or cut). Do not write full generation prompts.",
            f"Duration {duration}s; exactly {count} scenes; user direction: {idea}\nCharacter: {character}\nOrdered checkpoints: {analysis.get('checkpoint_descriptions', [])}")
        raw_scenes = outline.get("scenes", [])
        if len(raw_scenes) != count:
            raise RuntimeError(f"outline must return exactly {count} scenes")
        prompts: list[str] = []
        for start in range(0, count, 6):
            batch = raw_scenes[start:start + 6]
            result = await _chat_json(client, cfg, model,
                "Convert scene directions into standalone English video-generation prompts. Return strict JSON with prompts array in the same order. Each prompt must preserve the supplied invariant character, specify action, expression, setting, camera, lighting and smooth motion; no dialogue or text.",
                json.dumps({"character": character, "synopsis": outline.get("synopsis"),
                            "scene_offset": start, "scenes": batch}, ensure_ascii=False))
            batch_prompts = result.get("prompts", [])
            if len(batch_prompts) != len(batch):
                raise RuntimeError(f"prompt batch {start // 6 + 1} returned the wrong count")
            prompts.extend(str(item.get("prompt", item)) if isinstance(item, dict) else str(item)
                           for item in batch_prompts)
    durations = _durations(duration, count)
    scenes = [Scene(index=i, title=str(raw_scenes[i].get("title", f"Scene {i + 1}")),
                    duration=durations[i], direction=str(raw_scenes[i].get("direction", "")),
                    prompt=prompts[i], transition=str(raw_scenes[i].get("transition", "continue")))
              for i in range(count)]
    return StoryPlan(character_description=character, synopsis=str(outline.get("synopsis", idea)), scenes=scenes)


async def create_plan(image_path: Path, duration: float, clip_duration: float, idea: str, cfg: Settings,
                      scene_image_paths: list[Path] | None = None) -> StoryPlan:
    count = math.ceil(duration / clip_duration)
    if not cfg.llm_url:
        return _fallback(count, duration, clip_duration, idea)
    return await _create_plan_staged(image_path, duration, clip_duration, idea, cfg,
                                     scene_image_paths or [])

    mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode()
    scene_image_paths = scene_image_paths or []
    async with httpx.AsyncClient(timeout=120) as client:
        model = cfg.llm_model
        if not model:
            models_url = cfg.llm_url.rsplit("/chat/completions", 1)[0] + "/models"
            models_response = await _llm_request(client, "GET", models_url)
            available = models_response.json().get("data", [])
            if not available:
                raise RuntimeError("Vision LLM server returned no available models")
            model = available[0]["id"]
    payload = {
        "model": model,
        "response_format": {"type": "json_object"},
        "temperature": 0.65,
        "max_tokens": 6000,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": f"Create a {duration}-second story in exactly {count} consecutive scenes, each at most {clip_duration} seconds. User's story direction: {idea}"},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                {"type": "text", "text": "The image above is the invariant character reference. The following images, if any, are ordered scene checkpoints. Make the story pass through them in exactly that order."},
                *[
                    {"type": "image_url", "image_url": {"url": f"data:{mimetypes.guess_type(path.name)[0] or 'image/png'};base64,{base64.b64encode(path.read_bytes()).decode()}"}}
                    for path in scene_image_paths
                ],
            ]},
        ],
    }
    headers = {"Authorization": f"Bearer {cfg.llm_api_key}"} if cfg.llm_api_key else {}
    async with httpx.AsyncClient(timeout=120) as client:
        response = await _llm_request(client, "POST", cfg.llm_url, json=payload, headers=headers)
        raw = response.json()["choices"][0]["message"]["content"]
    if isinstance(raw, list):
        raw = "".join(part.get("text", "") for part in raw if isinstance(part, dict))
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    doc = json.loads(raw)
    if not isinstance(doc.get("scenes"), list) or len(doc["scenes"]) != count:
        raise RuntimeError(f"Vision LLM must return exactly {count} scenes")
    if not str(doc.get("character_description", "")).strip() or not str(doc.get("synopsis", "")).strip():
        raise RuntimeError("Vision LLM response is missing character_description or synopsis")
    scenes = []
    durations = _durations(duration, count)
    for i in range(count):
        source = doc["scenes"][i]
        if not isinstance(source, dict) or not str(source.get("prompt", "")).strip():
            raise RuntimeError(f"Vision LLM scene {i + 1} is missing its video prompt")
        length = durations[i]
        scenes.append(Scene(index=i, title=source.get("title", f"Scene {i + 1}"), duration=length,
                            prompt=source["prompt"],
                            transition=source.get("transition", "continue")))
    return StoryPlan(character_description=doc["character_description"], synopsis=doc["synopsis"], scenes=scenes)
