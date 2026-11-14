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


def _style_block(
    body_font: str,
    hook_font: str,
    *,
    hook_size: int = 72,
    hook_margin_v: int = 80,
    caption_margin_v: int = 260,
    hook_colour: str = "&H00FFFFFF&",
) -> str:
    # Alignment 2 = bottom-center, 8 = top-center.
    # Hook is a static white banner; keywords are recoloured in the Dialogue text.
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {PLAY_X}
PlayResY: {PLAY_Y}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{body_font},78,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,70,70,{caption_margin_v},1
Style: Hook,{hook_font},{hook_size},{hook_colour},&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,7,1,8,64,64,{hook_margin_v},1

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
    out = ""
    for i, token in enumerate(bits):
        raw = group[i].word.strip()
        if out and raw[:1] not in ",.!?;:)'\"" and not raw.startswith("'"):
            out += " "
        out += token
    return out


def wrap_hook(text: str, max_chars: int = 26, max_lines: int = 2) -> str:
    """Split a long hook onto two lines near the midpoint (viral Shorts style)."""
    text = " ".join((text or "").split())
    if max_lines < 2 or len(text) <= max_chars:
        return text
    mid = len(text) / 2
    best = None
    best_score = 1e9
    for i, ch in enumerate(text):
        if ch != " " or i < 4 or i > len(text) - 4:
            continue
        left, right = text[:i], text[i + 1 :]
        if not left or not right:
            continue
        # Prefer a break close to the middle, slightly early so the top line
        # isn't longer than the bottom.
        score = abs(i - mid) + (4 if i > mid + 2 else 0)
        if score < best_score:
            best_score = score
            best = (left, right)
    if not best:
        return text
    return best[0] + "\n" + best[1]


def build_ass(
    transcript: Transcript,
    dest: Path,
    *,
    hook: str | None = None,
    hook_duration: float | None = None,
    hook_keywords: list[str] | None = None,
    hook_font_size: int = 72,
    hook_margin_v: int = 80,
    caption_margin_v: int = 260,
    word_captions: bool = True,
    duration: float | None = None,
    time_map=None,
) -> Path:
    """Write an ASS file.

    The hook is a *static* banner (full clip duration unless hook_duration is set).
    Keywords inside the hook are painted yellow. Word-by-word captions can be
    turned off for montages. `time_map` remaps source-relative times to the
    output timeline (used for speed ramps).
    """
    body_font = "Montserrat ExtraBold"
    hook_font = "Anton"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _t(seconds: float) -> float:
        return float(time_map(seconds)) if time_map else seconds

    clip_end = duration
    if clip_end is None:
        if transcript.words:
            clip_end = max(w.end for w in transcript.words) + 0.4
        else:
            clip_end = hook_duration or 3.0
    # Static banner unless a short duration was explicitly requested *and*
    # no clip duration was given (legacy 2.8s fade).
    banner_end = clip_end if (hook_duration is None or duration is not None) else hook_duration
    banner_end = max(0.3, _t(banner_end))

    lines = [
        _style_block(
            body_font,
            hook_font,
            hook_size=hook_font_size,
            hook_margin_v=hook_margin_v,
            caption_margin_v=caption_margin_v,
        )
    ]
    if hook and hook.strip():
        from clipper.style import colorize_keywords

        wrapped = wrap_hook(hook.strip())
        text = colorize_keywords(_esc(wrapped), hook_keywords or [])
        # No fade-in: the first frame is the Shorts thumbnail, so the hook
        # has to be fully visible at t=0.
        lines.append(
            f"Dialogue: 1,0:00:00.00,{_ass_time(banner_end)},Hook,,0,0,0,,{text}\n"
        )

    if word_captions:
        groups = group_words(transcript.words)
        for group in groups:
            cursor = 0.0
            for i, w in enumerate(group):
                start = max(0.0, cursor, w.start)
                if i + 1 < len(group):
                    end = max(start + 0.05, group[i + 1].start)
                else:
                    end = max(start + 0.12, w.end + 0.08)
                if end <= start:
                    end = start + 0.05
                text = _phrase_line(group, i)
                lines.append(
                    f"Dialogue: 0,{_ass_time(_t(start))},{_ass_time(_t(end))},Default,,0,0,0,,{text}\n"
                )
                cursor = end

    dest.write_text("".join(lines), encoding="utf-8")
    return dest


def fonts_dir() -> Path | None:
    data = _pkg_data()
    if (data / "Montserrat-ExtraBold.ttf").is_file() or (data / "Anton-Regular.ttf").is_file():
        return data
    return None
