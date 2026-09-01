from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


VOCAL_ACTIVE_RATIO = 0.35


_SCRIPT = r'''
import json, sys
from pathlib import Path
import librosa, numpy as np
integration = Path(sys.argv[4]).resolve()
if not integration.is_dir():
    raise RuntimeError(f"LIPSYNC_APP_DIR does not exist: {integration}")
sys.path.insert(0, str(integration))
from app.services.audio import separate_vocals
source, work, durations = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(sys.argv[3])
vocals = separate_vocals(source, work)
y, sr = librosa.load(vocals, sr=16000, mono=True)
hop = 1600
rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
db = librosa.amplitude_to_db(np.maximum(rms, 1e-8), ref=np.max)
ratios, start = [], 0.0
for duration in durations:
    a, b = int(start * sr / hop), int((start + duration) * sr / hop)
    window = db[a:max(a + 1, b)]
    ratios.append(float(np.mean(window > -35)) if len(window) else 0.0)
    start += duration
print(json.dumps(ratios))
'''


async def analyze_vocal_ratios(audio: Path, durations: list[float], work_dir: Path) -> list[float]:
    project_parent = Path(__file__).resolve().parents[2]
    integration = Path(os.getenv("LIPSYNC_APP_DIR", project_parent / "Minimax-H3-lipsync-mv")).resolve()
    integration_python = integration / ".venv/bin/python"
    python = os.getenv("VOCAL_ANALYSIS_PYTHON", str(integration_python if integration_python.exists() else Path(sys.executable)))
    env = os.environ.copy()
    env.setdefault("STEM_API_URL", "http://127.0.0.1:8889")
    demucs_python = project_parent / "easy_music_v2/.venv/bin/python"
    if demucs_python.exists():
        env.setdefault("DEMUCS_PYTHON", str(demucs_python))
    proc = await asyncio.create_subprocess_exec(
        python, "-c", _SCRIPT, str(audio), str(work_dir), json.dumps(durations), str(integration),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(f"vocal analysis failed: {stderr.decode()[-700:]}")
    return list(map(float, json.loads(stdout.decode().strip().splitlines()[-1])))


def apply_mouth_direction(prompt: str, vocal_ratio: float) -> str:
    if vocal_ratio >= VOCAL_ACTIVE_RATIO:
        rule = ("Medium close-up performance framing, front-facing or three-quarter face view. "
                "The full face and unobstructed mouth remain clearly visible. The character sings naturally; "
                "the lips and jaw articulate in synchronization with the supplied vocal audio. ")
    else:
        rule = ("MANDATORY NON-VOCAL PERFORMANCE: The character does not sing, speak, mouth words, "
                "hum, or imitate phonemes at any point. The upper and lower lips remain gently sealed "
                "together in every frame from the first frame through the final frame. The jaw stays still; "
                "allow only blinking, breathing, and subtle head or body motion. Keep any microphone lowered "
                "and clearly away from the mouth. Do not create an open-mouth smile. ")
        reminder = (" End-state requirement: lips are still visibly closed and the jaw has made no "
                    "speech-like movement throughout the entire shot.")
        return rule + prompt + reminder
    return rule + prompt


def has_active_vocals(vocal_ratio: float) -> bool:
    return vocal_ratio >= VOCAL_ACTIVE_RATIO
