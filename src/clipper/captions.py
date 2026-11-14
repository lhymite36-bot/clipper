"""Build ASS subtitles: word-by-word highlights plus an optional hook."""

from __future__ import annotations

import re
from pathlib import Path

from clipper.transcribe import Transcript, Word

PLAY_X = 1080
PLAY_Y = 1920


def _pkg_data() -> Path:
    return Path(__file__).resolve().parent / "data"


def find_font(prefer: str) -> Path | None:
    data = _pkg_data()
    mapping = {
        "hook": data / "Anton-Regular.ttf",
        "body": data / "Montserrat-ExtraBold.ttf",
        "anton": data / "Anton-Regular.ttf",
        "montserrat": data / "Montserrat-ExtraBold.ttf",
    }
    path = mapping.get(prefer.lower())
    if path and path.is_file():
        return path
    # Fallback to any bundled font
    for cand in (data / "Montserrat-ExtraBold.ttf", data / "Anton-Regular.ttf"):
        if cand.is_file():
            return cand
    return None


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def group_words(words: list[Word], max_words: int = 5, max_duration: float = 2.8) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for w in words:
        token = (w.word or "").strip()
        if not token:
            continue
        if not current:
            current = [w]
            continue
        dur = w.end - current[0].start
        gap = w.start - current[-1].end
        if len(current) >= max_words or dur > max_duration or gap > 0.55:
            groups.append(current)
            current = [w]
        else:
            current.append(w)
    if current:
        groups.append(current)
    return groups


def _style_block(body_font: str, hook_font: str) -> str:
    # Alignment 2 = bottom-center, 8 = top-center.
    # Outline + shadow so captions pop on any background.
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {PLAY_X}
PlayResY: {PLAY_Y}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{body_font},78,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,70,70,260,1
Style: Hook,{hook_font},92,&H0000E5FF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,7,3,8,80,80,160,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _phrase_line(group: list[Word], active_index: int) -> str:
    bits = []
    for i, w in enumerate(group):
        token = _esc(w.word.strip())
        if i == active_index:
            bits.append(r"{\c&H0000E5FF&\fscx112\fscy112}" + token + r"{\r}")
        else:
            bits.append(token)
    # Join like transcribe._join_words but simpler: space unless punctuation
    out = ""
    for i, token in enumerate(bits):
        raw = group[i].word.strip()
        if out and raw[:1] not in ",.!?;:)'\"" and not raw.startswith("'"):
            out += " "
        out += token
    return out


def build_ass(
    transcript: Transcript,
    dest: Path,
    *,
    hook: str | None = None,
    hook_duration: float = 2.8,
) -> Path:
    body_font = "Montserrat ExtraBold"
    hook_font = "Anton"
    # If the bundled fonts are registered via fontsdir, these names match
    # the internal TTF names reasonably well; libass also matches by file.
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    lines = [_style_block(body_font, hook_font)]
    if hook and hook.strip():
        text = _esc(hook.strip().upper())
        lines.append(
            f"Dialogue: 1,0:00:00.00,{_ass_time(hook_duration)},Hook,,0,0,0,,{{\\fad(120,200)}}{text}\n"
        )

    groups = group_words(transcript.words)
    for group in groups:
        for i, w in enumerate(group):
            start = max(0.0, w.start)
            if i + 1 < len(group):
                end = max(start + 0.05, group[i + 1].start)
            else:
                end = max(start + 0.12, w.end + 0.08)
            text = _phrase_line(group, i)
            lines.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}\n"
            )

    dest.write_text("".join(lines), encoding="utf-8")
    return dest


def fonts_dir() -> Path | None:
    data = _pkg_data()
    if (data / "Montserrat-ExtraBold.ttf").is_file() or (data / "Anton-Regular.ttf").is_file():
        return data
    return None
