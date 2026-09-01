from __future__ import annotations

from enum import StrEnum
from time import time
from uuid import uuid4

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Scene(BaseModel):
    index: int
    title: str
    duration: float
    prompt: str
    direction: str = ""
    transition: str = "continue"
    status: str = "waiting"
    video_url: str | None = None
    generation_seconds: float | None = None
    error: str | None = None


class StoryPlan(BaseModel):
    character_description: str
    synopsis: str
    scenes: list[Scene]


class Run(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    status: RunStatus = RunStatus.PLANNING
    requested_duration: float
    clip_duration: float
    video_profile: str = "20fps-hq"
    generation_revision: int = 0
    audio_url: str | None = None
    story_direction: str = ""
    created_at: float = Field(default_factory=time)
    plan: StoryPlan | None = None
    error: str | None = None
    cancelled: bool = False
