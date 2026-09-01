from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .config import Settings


VIDEO_PROFILES = {
    "16fps-resolution": (640, 352, 16, 81),
    "16fps-4x3-resolution": (512, 384, 16, 81),
    "16fps-5x3": (640, 384, 16, 81),
    "16fps-3x2": (576, 384, 16, 81),
    "16fps-portrait-3x4": (384, 512, 16, 81),
    "16fps-portrait": (384, 640, 16, 81),
    "20fps-hq": (576, 320, 20, 97),
    "20fps-4x3-balanced": (512, 384, 20, 97),
    "24fps-fast": (512, 288, 24, 121),
    "24fps-3x2": (480, 320, 24, 121),
    "24fps-portrait": (288, 512, 24, 121),
}


class GatewayClient:
    def __init__(self, cfg: Settings):
        self.cfg = cfg

    async def upload(self, path: Path) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            with path.open("rb") as stream:
                response = await client.post(
                    f"{self.cfg.gateway_url}/api/v1/assets",
                    files={"file": (path.name, stream)},
                )
                if response.is_error:
                    raise RuntimeError(
                        f"gateway asset upload failed ({response.status_code}): {response.text[:500]}"
                    )
                return response.json()["id"]

    async def generate(self, prompt: str, seconds: float, seed: int, asset_ids: list[str],
                       audio_start: float | None, has_last_frame: bool = False,
                       video_profile: str = "20fps-hq") -> dict:
        mode = "a2v" if audio_start is not None else ("flf2v" if has_last_frame else "i2v")
        width, height, fps, frames = VIDEO_PROFILES.get(video_profile, VIDEO_PROFILES["20fps-hq"])
        body = {
            "backend": "ltx25", "mode": mode,
            "params": {"prompt": prompt, "width": width, "height": height, "num_frames": frames,
                       "fps": fps, "steps": 8, "guidance_scale": 3.0, "seed": seed},
            "asset_ids": asset_ids,
            "extra": {"upscale": False, "decoder": "vae"},
            "auto_load": True, "preset": self.cfg.gateway_preset,
        }
        if audio_start is not None:
            body["extra"].update(audio_start=audio_start, audio_duration=seconds)
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{self.cfg.gateway_url}/api/v1/generate", json=body)
            response.raise_for_status()
            job_id = response.json()["id"]
            while True:
                await asyncio.sleep(self.cfg.poll_interval)
                state_response = await client.get(f"{self.cfg.gateway_url}/api/v1/jobs/{job_id}")
                state_response.raise_for_status()
                state = state_response.json()
                if state["status"] == "completed":
                    return state
                if state["status"] in {"failed", "interrupted"}:
                    raise RuntimeError(state.get("error") or f"generation {state['status']}")

    def absolute_url(self, path: str) -> str:
        return urljoin(self.cfg.gateway_url.rstrip("/") + "/", path.lstrip("/"))
