from __future__ import annotations

import math
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .gateway import VIDEO_PROFILES
from .models import Run
from .orchestrator import Orchestrator
from .planner import create_plan


app = FastAPI(title="Realtime Video", version="0.1.0")
orchestrator = Orchestrator(settings)
run_inputs: dict[str, tuple[Path, Path | None, list[Path], str]] = {}
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(static_dir / "index.html")


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}


async def save_upload(upload: UploadFile, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as output:
        shutil.copyfileobj(upload.file, output)


def save_scenario(run: Run) -> None:
    folder = settings.data_dir / run.id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "scenario.json"
    temporary = folder / "scenario.json.tmp"
    temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(target)


def restore_persisted_run(run_id: str) -> bool:
    if run_id in orchestrator.runs:
        return True
    if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        return False
    folder = settings.data_dir / run_id
    scenario_path = folder / "scenario.json"
    if not scenario_path.exists():
        return False
    try:
        run = Run.model_validate_json(scenario_path.read_text(encoding="utf-8"))
        character_path = next(folder.glob("character.*"))
    except (OSError, StopIteration, ValueError):
        return False
    audio_path = next(iter(sorted(folder.glob("music.*"))), None)
    scene_paths = sorted(folder.glob("reference-*"))
    run.status = "awaiting_confirmation"
    run.cancelled = False
    run.error = None
    if run.plan:
        for scene in run.plan.scenes:
            scene.status = "waiting"
            scene.video_url = None
            scene.generation_seconds = None
            scene.error = None
    orchestrator.register(run)
    run_inputs[run.id] = (character_path, audio_path, scene_paths, run.story_direction)
    return True


@app.post("/api/runs", response_model=Run, status_code=202)
async def create_run(duration: float = Form(...), clip_duration: float = Form(5.0), idea: str = Form(""),
                     video_profile: str = Form("20fps-hq"),
                     character: UploadFile = File(...), audio: UploadFile | None = File(None),
                     scene_images: list[UploadFile] = File(default=[])):
    if not 5 <= duration <= 300:
        raise HTTPException(400, "duration must be between 5 and 300 seconds")
    if not 2 <= clip_duration <= 8:
        raise HTTPException(400, "clip_duration must be between 2 and 8 seconds")
    if not idea.strip():
        raise HTTPException(400, "物語の方向性を入力してください")
    if video_profile not in VIDEO_PROFILES:
        raise HTTPException(400, "unknown video profile")
    supplied_scene_images = [item for item in scene_images if item.filename]
    if len(supplied_scene_images) > math.ceil(duration / clip_duration) + 1:
        raise HTTPException(400, "シーン画像が動画区間数に対して多すぎます")
    run = Run(requested_duration=duration, clip_duration=clip_duration, video_profile=video_profile,
              story_direction=idea)
    folder = settings.data_dir / run.id
    suffix = Path(character.filename or "character.png").suffix or ".png"
    character_path = folder / f"character{suffix}"
    await save_upload(character, character_path)
    scene_paths: list[Path] = []
    for index, upload in enumerate(supplied_scene_images):
        image_suffix = Path(upload.filename or "scene.png").suffix or ".png"
        scene_path = folder / f"reference-{index:03}{image_suffix}"
        await save_upload(upload, scene_path)
        scene_paths.append(scene_path)
    audio_path = None
    if audio is not None and bool(audio.filename):
        audio_suffix = Path(audio.filename or "music.wav").suffix or ".wav"
        audio_path = folder / f"music{audio_suffix}"
        await save_upload(audio, audio_path)
        run.audio_url = f"/api/runs/{run.id}/audio"
    try:
        run.plan = await create_plan(character_path, duration, clip_duration, idea, settings, scene_paths)
    except Exception as exc:
        raise HTTPException(502, f"scenario planning failed: {exc}") from exc
    run.status = "awaiting_confirmation"
    orchestrator.register(run)
    run_inputs[run.id] = (character_path, audio_path, scene_paths, idea)
    save_scenario(run)
    return run


@app.post("/api/runs/{run_id}/regenerate", response_model=Run)
async def regenerate_scenario(run_id: str):
    if not restore_persisted_run(run_id) or run_id not in run_inputs:
        raise HTTPException(404, "run not found")
    run = orchestrator.runs[run_id]
    if run.status == "generating":
        raise HTTPException(409, "scenario cannot be regenerated during video generation")
    character_path, _, scene_paths, idea = run_inputs[run_id]
    run.status = "planning"
    try:
        run.plan = await create_plan(character_path, run.requested_duration, run.clip_duration,
                                     idea, settings, scene_paths)
        run.status = "awaiting_confirmation"
        run.error = None
        save_scenario(run)
    except Exception as exc:
        run.status = "awaiting_confirmation"
        run.error = f"scenario planning failed: {exc}"
        raise HTTPException(502, run.error) from exc
    return run


@app.post("/api/runs/{run_id}/generate", response_model=Run, status_code=202)
async def start_generation(run_id: str, video_profile: str | None = Form(None)):
    if not restore_persisted_run(run_id) or run_id not in run_inputs:
        raise HTTPException(404, "run not found")
    run = orchestrator.runs[run_id]
    if run.status == "generating":
        raise HTTPException(409, "video generation is already running")
    task = orchestrator.tasks.get(run_id)
    if task is not None and not task.done():
        raise HTTPException(409, "video generation is still stopping")
    if video_profile is not None:
        if video_profile not in VIDEO_PROFILES:
            raise HTTPException(400, "unknown video profile")
        run.video_profile = video_profile
    run.generation_revision += 1
    run.cancelled = False
    run.error = None
    assert run.plan
    for scene in run.plan.scenes:
        scene.status = "waiting"
        scene.video_url = None
        scene.generation_seconds = None
        scene.error = None
    character_path, audio_path, scene_paths, _ = run_inputs[run_id]
    orchestrator.start(run, character_path, audio_path, scene_paths)
    return run


@app.get("/api/runs/{run_id}", response_model=Run)
async def get_run(run_id: str):
    if not restore_persisted_run(run_id):
        raise HTTPException(404, "run not found")
    return orchestrator.runs[run_id]


@app.delete("/api/runs/{run_id}", status_code=204)
async def cancel_run(run_id: str):
    if not restore_persisted_run(run_id):
        raise HTTPException(404, "run not found")
    orchestrator.cancel(run_id)


@app.get("/api/runs/{run_id}/scenes/{scene_index}/video")
async def scene_video(run_id: str, scene_index: int):
    path = settings.data_dir / run_id / f"scene-{scene_index:03}.mp4"
    if not path.exists():
        raise HTTPException(404, "scene is not ready")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/runs/{run_id}/generations/{revision}/scenes/{scene_index}/video")
async def generation_scene_video(run_id: str, revision: int, scene_index: int):
    path = settings.data_dir / run_id / f"generation-{revision:03}" / f"scene-{scene_index:03}.mp4"
    if not path.exists():
        raise HTTPException(404, "scene is not ready")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/runs/{run_id}/audio")
async def run_audio(run_id: str):
    inputs = run_inputs.get(run_id)
    if inputs is None or inputs[1] is None or not inputs[1].exists():
        raise HTTPException(404, "audio is not available")
    return FileResponse(inputs[1], filename=inputs[1].name)


@app.get("/api/runs/{run_id}/scenario")
async def download_scenario(run_id: str):
    path = settings.data_dir / run_id / "scenario.json"
    if not path.exists():
        raise HTTPException(404, "scenario is not available")
    return FileResponse(path, media_type="application/json", filename=f"scenario-{run_id}.json")
