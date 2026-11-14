"""Optional encode test. Skips when ffmpeg is missing."""

from pathlib import Path

import pytest

from clipper.ffmpeg_utils import FFmpegError, find_ffmpeg, probe_duration, probe_size, run
from clipper.render import punch_in_filter, render_clip
from clipper.transcribe import Transcript, Word


def _ffmpeg_or_skip() -> str:
    try:
        return find_ffmpeg()
    except FFmpegError:
        pytest.skip("ffmpeg is not installed")


def test_render_vertical_clip_with_captions(tmp_path: Path):
    ffmpeg = _ffmpeg_or_skip()
    src = tmp_path / "src.mp4"
    # 18s 1280x720 color bars + stereo tone, H.264
    run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=25:duration=18",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=18",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(src),
        ]
    )
    words = [
        Word("Wait", 1.0, 1.3),
        Word("for", 1.3, 1.5),
        Word("it!", 1.5, 2.0),
        Word("This", 5.0, 5.3),
        Word("is", 5.3, 5.5),
        Word("insane", 5.5, 6.2),
    ]
    tr = Transcript("Wait for it! This is insane", "en", [], words, 18)
    dest = tmp_path / "short.mp4"
    render_clip(src, dest, 0.5, 16.5, tr, hook="WAIT FOR IT", style="blur", captions=True)
    assert dest.is_file() and dest.stat().st_size > 10_000
    w, h = probe_size(dest)
    assert (w, h) == (1080, 1920)
    dur = probe_duration(dest)
    assert 14 <= dur <= 17.5


def test_punch_in_filter_is_timed_to_the_peak():
    vf = punch_in_filter(12.5, zoom=1.12, attack=0.45)
    assert "eval=frame" in vf
    assert "crop=1080:1920" in vf
    assert "12.42" in vf or "12.4" in vf  # peak - 0.08
    assert "1.12" in vf


def test_render_with_punch_in(tmp_path: Path):
    ffmpeg = _ffmpeg_or_skip()
    src = tmp_path / "src.mp4"
    run(
        [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25:duration=18",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=18",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(src),
        ]
    )
    words = [
        Word("This", 5.0, 5.3),
        Word("is", 5.3, 5.5),
        Word("insane", 5.5, 6.2),
    ]
    tr = Transcript("This is insane", "en", [], words, 18)
    dest = tmp_path / "punched.mp4"
    render_clip(src, dest, 0.5, 16.5, tr, hook="THIS IS INSANE", style="blur",
                captions=True, peak=6.0, punch=True)
    assert dest.is_file() and dest.stat().st_size > 10_000
    w, h = probe_size(dest)
    assert (w, h) == (1080, 1920)



def test_encode_tail_includes_loudnorm():
    from clipper.render import LOUDNORM, _encode_tail

    args = _encode_tail(16.0)
    assert "-af" in args
    assert LOUDNORM in args
    assert "TP=-1.5" in LOUDNORM
    no_af = _encode_tail(16.0, af=False)
    assert "-af" not in no_af
