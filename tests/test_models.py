from pathlib import Path
from dataclasses import replace

from fastapi.testclient import TestClient

from app import main
from app.models import Run, RunStatus, Scene, StoryPlan
from app.gateway import VIDEO_PROFILES
from app.vocals import apply_mouth_direction, has_active_vocals


def test_run_defaults_to_planning():
    run = Run(requested_duration=30, clip_duration=5)
    assert run.status == RunStatus.PLANNING
    assert len(run.id) == 32


def test_video_profiles_match_probed_settings():
    assert VIDEO_PROFILES["16fps-resolution"] == (640, 352, 16, 81)
    assert VIDEO_PROFILES["16fps-4x3-resolution"] == (512, 384, 16, 81)
    assert VIDEO_PROFILES["16fps-5x3"] == (640, 384, 16, 81)
    assert VIDEO_PROFILES["16fps-3x2"] == (576, 384, 16, 81)
    assert VIDEO_PROFILES["16fps-portrait-3x4"] == (384, 512, 16, 81)
    assert VIDEO_PROFILES["16fps-portrait"] == (384, 640, 16, 81)
    assert VIDEO_PROFILES["20fps-hq"] == (576, 320, 20, 97)
    assert VIDEO_PROFILES["20fps-4x3-balanced"] == (512, 384, 20, 97)
    assert VIDEO_PROFILES["24fps-fast"] == (512, 288, 24, 121)
    assert VIDEO_PROFILES["24fps-3x2"] == (480, 320, 24, 121)
    assert VIDEO_PROFILES["24fps-portrait"] == (288, 512, 24, 121)


def test_audio_conditioning_is_disabled_during_non_vocal_scenes():
    assert not has_active_vocals(0.0)
    assert not has_active_vocals(0.349)
    assert has_active_vocals(0.35)
    prompt = apply_mouth_direction("A calm intro shot.", 0.0)
    assert "lips remain gently sealed" in prompt
    assert "every frame" in prompt
    assert "microphone lowered" in prompt


def test_completed_run_can_regenerate_with_another_profile(monkeypatch):
    run = Run(
        status=RunStatus.COMPLETED,
        requested_duration=5,
        clip_duration=5,
        plan=StoryPlan(
            character_description="character",
            synopsis="story",
            scenes=[Scene(index=0, title="scene", duration=5, prompt="prompt", status="ready",
                          video_url="/old-video")],
        ),
    )
    main.orchestrator.register(run)
    main.run_inputs[run.id] = (Path("character.png"), None, [], "idea")
    monkeypatch.setattr(main.orchestrator, "start", lambda *args: None)

    response = TestClient(main.app).post(
        f"/api/runs/{run.id}/generate", data={"video_profile": "16fps-resolution"}
    )

    assert response.status_code == 202
    assert run.video_profile == "16fps-resolution"
    assert run.generation_revision == 1
    assert run.plan.scenes[0].status == "waiting"
    assert run.plan.scenes[0].video_url is None
    main.orchestrator.runs.pop(run.id, None)
    main.run_inputs.pop(run.id, None)


def test_saved_scenario_restores_as_generatable_run(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "settings", replace(main.settings, data_dir=tmp_path))
    run = Run(
        status=RunStatus.AWAITING_CONFIRMATION,
        requested_duration=5,
        clip_duration=5,
        story_direction="quiet story",
        plan=StoryPlan(
            character_description="character",
            synopsis="saved story",
            scenes=[Scene(index=0, title="scene", duration=5, prompt="saved prompt")],
        ),
    )
    folder = tmp_path / run.id
    folder.mkdir()
    (folder / "character.png").write_bytes(b"image")
    main.save_scenario(run)
    main.orchestrator.runs.pop(run.id, None)
    main.run_inputs.pop(run.id, None)

    assert main.restore_persisted_run(run.id)
    restored = main.orchestrator.runs[run.id]
    assert restored.status == RunStatus.AWAITING_CONFIRMATION
    assert restored.plan.scenes[0].prompt == "saved prompt"
    assert main.run_inputs[run.id][3] == "quiet story"
    main.orchestrator.runs.pop(run.id, None)
    main.run_inputs.pop(run.id, None)
