from app.styles import apply_visual_style


def test_anime_style_is_locked_before_and_after_scene_prompt():
    result = apply_visual_style("The character turns toward the camera.", "anime")

    assert result.count("MANDATORY VISUAL STYLE FOR EVERY FRAME") == 2
    assert "hand-drawn 2D anime" in result
    assert "Outlines may be subtle or absent" in result
    assert "Do not drift into photorealism" in result
    assert "The character turns toward the camera." in result


def test_realistic_style_rejects_anime_rendering():
    result = apply_visual_style("A quiet close-up.", "realistic")

    assert "photorealistic live-action cinematography" in result
    assert "Do not use anime line art" in result
