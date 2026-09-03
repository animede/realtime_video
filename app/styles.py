from __future__ import annotations


ANIME_STYLE_LOCK = (
    "MANDATORY VISUAL STYLE FOR EVERY FRAME: Japanese anime visual style, specifically hand-drawn 2D "
    "anime with cohesive cel or soft anime shading, simplified illustrated facial anatomy, deliberately "
    "drawn hair highlights, and painted anime backgrounds. Outlines may be subtle or absent. Keep the "
    "character design on-model and visually consistent. "
    "Do not drift into photorealism, live action, realistic skin or fur, photographic texture, 3D CGI, "
    "plastic materials, or game-engine rendering"
)

REALISTIC_STYLE_LOCK = (
    "MANDATORY VISUAL STYLE FOR EVERY FRAME: photorealistic live-action cinematography, natural skin, "
    "fur and material detail, physically plausible light and camera optics. Do not use anime line art, "
    "cel shading, illustration, cartoon rendering, or 3D CGI"
)


def apply_visual_style(prompt: str, visual_style: str) -> str:
    """Apply the selected rendering style at the final generation boundary.

    This intentionally repeats the constraint after the scene prompt: long prompts and
    chained image conditioning otherwise tend to weaken style instructions over time.
    """
    lock = ANIME_STYLE_LOCK if visual_style == "anime" else REALISTIC_STYLE_LOCK
    return f"{lock}. {prompt.strip()} {lock}."
