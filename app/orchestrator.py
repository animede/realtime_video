from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import httpx

from .config import Settings
from .gateway import GatewayClient
from .models import Run, RunStatus
from .vocals import analyze_vocal_ratios, apply_mouth_direction, has_active_vocals


class Orchestrator:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.gateway = GatewayClient(cfg)
        self.runs: dict[str, Run] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        cfg.data_dir.mkdir(parents=True, exist_ok=True)

    def start(self, run: Run, character_path: Path, audio_path: Path | None,
              scene_image_paths: list[Path] | None = None) -> None:
        self.runs[run.id] = run
        self.tasks[run.id] = asyncio.create_task(
            self._generate(run, character_path, audio_path, scene_image_paths or [])
        )

    def register(self, run: Run) -> None:
        self.runs[run.id] = run

    async def _download(self, url: str, target: Path) -> None:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with target.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        output.write(chunk)

    async def _last_frame(self, video: Path, target: Path) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-sseof", "-0.08", "-i", str(video), "-frames:v", "1", str(target),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode:
            raise RuntimeError(f"ffmpeg could not extract the last frame: {stderr.decode()[-500:]}")

    async def _media_duration(self, path: Path) -> float:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode:
            raise RuntimeError(f"ffprobe could not read audio duration: {stderr.decode()[-500:]}")
        return float(stdout.decode().strip())

    async def _generate(self, run: Run, character_path: Path, audio_path: Path | None,
                        scene_image_paths: list[Path]) -> None:
        assert run.plan
        run.status = RunStatus.GENERATING
        folder = self.cfg.data_dir / run.id
        folder.mkdir(parents=True, exist_ok=True)
        generation_folder = folder / f"generation-{run.generation_revision:03}"
        generation_folder.mkdir(parents=True, exist_ok=True)
        current_scene = None
        try:
            character_id = await self.gateway.upload(character_path)
            audio_id = await self.gateway.upload(audio_path) if audio_path else None
            scene_image_ids = [await self.gateway.upload(path) for path in scene_image_paths]
            audio_total = await self._media_duration(audio_path) if audio_path else None
            vocal_ratios = ([0.0] * len(run.plan.scenes))
            if audio_path:
                vocal_ratios = await analyze_vocal_ratios(
                    audio_path, [scene.duration for scene in run.plan.scenes], folder / "vocal-analysis"
                )
            chain_id = scene_image_ids[0] if scene_image_ids else character_id
            anchors: dict[int, str] = {}
            if len(scene_image_ids) > 1:
                last_boundary = len(run.plan.scenes)
                for image_index, asset_id in enumerate(scene_image_ids[1:], start=1):
                    boundary = round(image_index * last_boundary / (len(scene_image_ids) - 1))
                    anchors[boundary] = asset_id
            elapsed = 0.0
            for scene in run.plan.scenes:
                current_scene = scene
                if run.cancelled:
                    run.status = RunStatus.CANCELLED
                    return
                scene.status = "generating"
                target_id = anchors.get(scene.index + 1)
                vocal_active = bool(audio_id) and has_active_vocals(vocal_ratios[scene.index])
                assets = ([audio_id] if vocal_active else []) + [chain_id] + ([target_id] if target_id else [])
                audio_offset = None
                if vocal_active and audio_total is not None:
                    audio_offset = min(elapsed, max(0.0, audio_total - scene.duration - 0.15))
                generation_prompt = apply_mouth_direction(scene.prompt, vocal_ratios[scene.index]) if audio_id else scene.prompt
                result = await self.gateway.generate(generation_prompt, scene.duration, 1000 + scene.index,
                                                     assets, audio_offset,
                                                     has_last_frame=target_id is not None,
                                                     video_profile=run.video_profile)
                video_path = result["result"]["video_url"]
                scene.generation_seconds = result["result"].get("generation_seconds")
                local_video = generation_folder / f"scene-{scene.index:03}.mp4"
                await self._download(self.gateway.absolute_url(video_path), local_video)
                scene.video_url = (f"/api/runs/{run.id}/generations/{run.generation_revision}"
                                   f"/scenes/{scene.index}/video")
                scene.status = "ready"
                if scene.index + 1 < len(run.plan.scenes):
                    frame = generation_folder / f"chain-{scene.index:03}.png"
                    await self._last_frame(local_video, frame)
                    chain_id = target_id or await self.gateway.upload(frame)
                elapsed += scene.duration
            run.status = RunStatus.COMPLETED
        except asyncio.CancelledError:
            run.status = RunStatus.CANCELLED
            raise
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error = str(exc)
            if current_scene is not None:
                current_scene.status = "failed"
                current_scene.error = str(exc)

    def cancel(self, run_id: str) -> None:
        run = self.runs[run_id]
        run.cancelled = True
