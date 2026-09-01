import asyncio
from pathlib import Path

import pytest

from app.config import Settings
from app.planner import create_plan


def test_fallback_plan_covers_exact_duration(tmp_path: Path):
    image = tmp_path / "character.png"
    image.write_bytes(b"not decoded by fallback")
    cfg = Settings(data_dir=tmp_path, llm_url=None)
    plan = asyncio.run(create_plan(image, 31, 5, "night walk", cfg))
    assert len(plan.scenes) == 7
    assert sum(scene.duration for scene in plan.scenes) == pytest.approx(31)
    assert all(scene.duration <= 5 for scene in plan.scenes)
    assert all("Same character" in scene.prompt for scene in plan.scenes)


def test_short_remainder_is_distributed(tmp_path: Path):
    image = tmp_path / "character.png"
    image.write_bytes(b"x")
    plan = asyncio.run(create_plan(image, 6.5, 3, "", Settings(data_dir=tmp_path, llm_url=None)))
    assert sum(scene.duration for scene in plan.scenes) == pytest.approx(6.5)
    assert max(scene.duration for scene in plan.scenes) - min(scene.duration for scene in plan.scenes) < .002
    assert min(scene.duration for scene in plan.scenes) >= 1
