import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    gateway_url: str = os.getenv("GATEWAY_URL", "http://127.0.0.1:8630")
    gateway_preset: str = os.getenv("GATEWAY_PRESET", "nvfp4-fast")
    data_dir: Path = Path(os.getenv("REALTIME_VIDEO_DATA", "data")).resolve()
    llm_url: str | None = os.getenv("VISION_LLM_URL")
    llm_api_key: str | None = os.getenv("VISION_LLM_API_KEY")
    llm_model: str | None = os.getenv("VISION_LLM_MODEL")
    poll_interval: float = float(os.getenv("JOB_POLL_INTERVAL", "0.35"))


settings = Settings()
