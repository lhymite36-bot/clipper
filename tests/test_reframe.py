from clipper.reframe import TARGET_ASPECT, TARGET_H, TARGET_W, build_vf, choose_style


def test_targets():
    assert TARGET_W == 1080
    assert TARGET_H == 1920
    assert abs(TARGET_ASPECT - 9 / 16) < 1e-6


def test_choose_style_auto_face_wins():
    assert choose_style(1920, 1080, "auto", has_face=True) == "face"
    assert choose_style(1920, 1080, "auto", has_face=False) == "blur"
    assert choose_style(1080, 1080, "auto", has_face=False) == "center"
    assert choose_style(1920, 1080, "face", has_face=False) == "center"
    assert choose_style(1920, 1080, "blur", has_face=True) == "blur"


def test_blur_filter_has_overlay_and_scale():
    vf = build_vf(1920, 1080, "blur")
    assert "gblur" in vf or "boxblur" in vf
    assert "overlay" in vf
    assert "1080:1920" in vf
    assert "yuv420p" in vf


def test_face_crop_centers_near_face():
    vf = build_vf(1920, 1080, "face", face=(0.8, 0.5))
    assert vf.startswith("crop=")
    # crop=w:h:x:y
    w, h, x, y = crop_parts = vf.split(",")[0].split("=")[1].split(":")
    assert int(w) < 1920
    assert int(x) > 100  # shifted right toward the face
    assert "scale=1080:1920" in vf


def test_center_crop_starts_mid_frame():
    vf = build_vf(1920, 1080, "center")
    parts = vf.split("crop=")[1].split(",")[0].split(":")
    w, h, x, y = map(int, parts)
    assert abs((x + w / 2) - 960) <= 2
