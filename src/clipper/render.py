"""Cut, reframe, caption and encode a single Short as H.264 MP4."""

from __future__ import annotations

from pathlib import Path

from clipper.captions import build_ass, fonts_dir
from clipper.ffmpeg_utils import find_ffmpeg, run
from clipper.reframe import plan_reframe
from clipper.transcribe import Transcript


def _escape_filter_path(path: Path) -> str:
    # ffmpeg filter args: escape \, :, ' and use forward slashes.
    text = path.resolve().as_posix()
    text = text.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    return text


def render_clip(
    source: Path,
    dest: Path,
    start: float,
    end: float,
    transcript: Transcript,
    *,
    hook: str | None = None,
    style: str = "auto",
    captions: bool = True,
    progress=None,
) -> Path:
    log = progress or (lambda *_a, **_k: None)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = dest.parent
    duration = max(0.2, end - start)

    vf, resolved, _face = plan_reframe(source, start, end, style=style, progress=log)
    log(f"Reframe style: {resolved}")

    if captions:
        clip_transcript = transcript.shifted(start, end)
        ass_path = work / (dest.stem + ".ass")
        build_ass(clip_transcript, ass_path, hook=hook)
        fonts = fonts_dir()
        fonts_arg = ""
        if fonts:
            fonts_arg = f":fontsdir='{_escape_filter_path(fonts)}'"
        # subtitles filter needs the ASS path escaped
        vf = f"{vf},subtitles='{_escape_filter_path(ass_path)}'{fonts_arg}"

    ffmpeg = find_ffmpeg()
    # Accurate cut: decode from a little before start, then -ss after -i
    # For speed + accuracy a pre-roll of ~1s is a good compromise; for
    # short clips we just decode from the start timestamp with -ss before -i
    # and accept keyframe-adjacent cuts (ASS times are clip-relative).
    args = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-level",
        "4.2",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-movflags",
        "+faststart",
        "-shortest",
        str(dest),
    ]
    log(f"Encoding {dest.name}…")
    run(args)
    if not dest.is_file() or dest.stat().st_size < 1000:
        raise RuntimeError(f"Encoder did not produce a valid file: {dest}")
    return dest
