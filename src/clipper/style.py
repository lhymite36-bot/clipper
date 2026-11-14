"""Style presets, layout, speed ramps, grades, curiosity hooks and titles.

The looks follow three high-performing Shorts styles:
- story-skit: 16:9 picture in a 9:16 frame, hook on a black bar
- cinematic-edit: letterboxed, moody grade, hook on the bar, few captions
- sports-montage: tight 9:16 crop, speed ramps, high contrast
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from dataclasses import dataclass, field, replace

from clipper.reframe import TARGET_ASPECT, TARGET_H, TARGET_W, build_vf, choose_style
from clipper.transcribe import Transcript

PRESET_ALIASES = {
    "auto": "auto",
    "cinematic": "cinematic-edit",
    "cinematic-edit": "cinematic-edit",
    "story": "story-skit",
    "story-skit": "story-skit",
    "skit": "story-skit",
    "sports": "sports-montage",
    "sports-montage": "sports-montage",
    "montage": "sports-montage",
}

# ASS BGR yellow used for 1–2 hook keywords (same family as the caption highlight).
KEYWORD_COLOUR = r"{\c&H0000E5FF&}"
KEYWORD_RESET = r"{\r}"


@dataclass
class StyleSpec:
    name: str
    layout: str  # auto | tight | bars | blur
    grade: str  # none | moody | contrast | warm
    captions: str  # auto | words | none | minimal
    speed_ramps: bool
    punch: bool
    hook_case: str  # upper | title
    loop: bool
    hook_bar: bool = True  # draw / use a top bar for the hook


@dataclass
class LayoutPlan:
    mode: str  # tight | bars | blur
    vf: str
    top_bar: int
    bottom_bar: int
    hook_margin_v: int  # ASS MarginV from the top (alignment 8)
    caption_margin_v: int  # ASS MarginV from the bottom (alignment 2)


@dataclass
class SpeedSeg:
    src_start: float
    src_end: float
    speed: float

    @property
    def out_duration(self) -> float:
        return max(0.0, self.src_end - self.src_start) / max(self.speed, 0.05)


@dataclass
class HookBanner:
    text: str
    keywords: list[str] = field(default_factory=list)
    emoji: str = ""
    titles: list[str] = field(default_factory=list)

    @property
    def display(self) -> str:
        # Emoji is kept on the object for titles, but Montserrat has no emoji
        # glyphs, so the burned-in banner is text-only (no tofu boxes).
        return (self.text or "").strip()


PRESETS: dict[str, StyleSpec] = {
    "cinematic-edit": StyleSpec(
        name="cinematic-edit",
        layout="bars",
        grade="moody",
        captions="none",
        speed_ramps=False,
        punch=False,
        hook_case="upper",
        loop=True,
    ),
    "story-skit": StyleSpec(
        name="story-skit",
        layout="auto",
        grade="warm",
        captions="words",
        speed_ramps=False,
        punch=True,
        hook_case="title",
        loop=True,
    ),
    "sports-montage": StyleSpec(
        name="sports-montage",
        layout="tight",
        grade="contrast",
        captions="none",
        speed_ramps=True,
        punch=True,
        hook_case="title",
        loop=True,
    ),
}

GRADE_FILTERS = {
    "none": "",
    "moody": "eq=saturation=0.72:contrast=1.18:brightness=-0.05,colorbalance=rs=-0.05:gs=0.01:bs=0.08",
    "contrast": "eq=contrast=1.28:saturation=1.06:gamma=0.96",
    "warm": "eq=saturation=1.06:gamma=1.02:contrast=1.05,colorbalance=rs=0.06:gs=0.02:bs=-0.03",
}


def normalize_preset(name: str | None) -> str:
    key = (name or "auto").strip().lower().replace("_", "-").replace(" ", "-")
    return PRESET_ALIASES.get(key, "auto")


def pick_preset(transcript: Transcript | None, duration: float, src_aspect: float = 16 / 9) -> str:
    """Choose a preset when the user didn't pick one."""
    words = list(getattr(transcript, "words", None) or [])
    spoken = 0.0
    if words:
        spoken = sum(max(0.0, w.end - w.start) for w in words)
    coverage = spoken / max(duration, 0.01)
    if coverage >= 0.28 or len(words) >= 24:
        return "story-skit"
    if src_aspect >= 1.4 and coverage < 0.12:
        return "cinematic-edit"
    if coverage < 0.18:
        return "sports-montage"
    return "story-skit"


def resolve_spec(
    preset: str | None,
    *,
    transcript: Transcript | None = None,
    duration: float = 0.0,
    src_aspect: float = 16 / 9,
    layout: str | None = None,
    grade: str | None = None,
    captions: str | None = None,
    punch: bool | None = None,
    speed_ramps: bool | None = None,
    loop: bool | None = None,
) -> StyleSpec:
    name = normalize_preset(preset)
    if name == "auto":
        name = pick_preset(transcript, duration, src_aspect)
    spec = PRESETS[name]
    if layout and layout != "auto":
        spec = replace(spec, layout=layout)
    if grade and grade != "auto":
        spec = replace(spec, grade=grade)
    if captions and captions != "auto":
        spec = replace(spec, captions=captions)
    if punch is False:
        spec = replace(spec, punch=False)
    if punch is True and spec.punch is False:
        # Explicit --punch (or UI check) can turn it back on.
        pass
    if speed_ramps is True:
        spec = replace(spec, speed_ramps=True)
    if speed_ramps is False:
        spec = replace(spec, speed_ramps=False)
    if loop is False:
        spec = replace(spec, loop=False)
    return spec


def choose_layout_mode(
    src_w: int,
    src_h: int,
    *,
    preferred: str,
    has_face: bool,
    tight_subject: bool = False,
) -> str:
    preferred = (preferred or "auto").lower()
    if preferred in {"tight", "bars", "blur"}:
        return preferred
    aspect = src_w / max(src_h, 1)
    # Close-up / already-vertical / a clearly tracked subject → fill the frame.
    if tight_subject or aspect <= TARGET_ASPECT + 0.08:
        return "tight"
    if has_face and aspect <= 1.2:
        return "tight"
    # Wide footage (typical 16:9) keeps the full picture and puts the hook on a bar.
    if aspect >= 1.3:
        return "bars"
    return "tight"


def plan_layout(
    src_w: int,
    src_h: int,
    *,
    preferred: str = "auto",
    crop_style: str = "auto",
    face: tuple[float, float] | None = None,
    tight_subject: bool = False,
) -> LayoutPlan:
    mode = choose_layout_mode(
        src_w, src_h, preferred=preferred, has_face=bool(face), tight_subject=tight_subject
    )
    if mode == "bars":
        # Fit the full picture at 1080 wide, letterbox to 9:16, hook lives in the top bar.
        vf = (
            f"scale={TARGET_W}:-2:force_original_aspect_ratio=decrease,"
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p"
        )
        pic_h = int(round(TARGET_W * src_h / max(src_w, 1)))
        pic_h = min(TARGET_H, pic_h // 2 * 2)
        top = max(0, (TARGET_H - pic_h) // 2)
        bottom = max(0, TARGET_H - pic_h - top)
        # Sit the hook in the lower third of the top bar, just above the picture.
        hook_margin = max(40, top - 210) if top >= 220 else max(24, top // 4)
        caption_margin = bottom + 36
        return LayoutPlan(mode, vf, top, bottom, hook_margin, caption_margin)

    # tight / blur reuse the existing face-or-center / blur-fill crop.
    style = "blur" if mode == "blur" else choose_style(src_w, src_h, crop_style, has_face=bool(face))
    if mode == "tight" and style == "blur":
        style = "face" if face else "center"
    vf = build_vf(src_w, src_h, style, face)
    top = int(TARGET_H * 0.20)
    return LayoutPlan(mode, vf, top, 0, 72, 260)


def grade_filter(name: str | None) -> str:
    return GRADE_FILTERS.get((name or "none").lower(), "")


def hook_bar_filter(layout: LayoutPlan) -> str:
    """Full-width black bar behind the hook when the picture itself is 9:16."""
    if layout.mode != "tight" or layout.top_bar <= 0:
        return ""
    h = int(layout.top_bar)
    return f"drawbox=0:0:{TARGET_W}:{h}:black@0.88:t=fill"


def speed_segments(
    duration: float,
    peak: float | None,
    *,
    enabled: bool,
    slow: float = 0.5,
    fast: float = 1.5,
    slow_hold: float = 1.6,
) -> list[SpeedSeg]:
    """1.5x on dead time, 0.5x for 1–2 s around the peak. Off → one 1x segment."""
    duration = max(0.2, float(duration))
    if not enabled or peak is None:
        return [SpeedSeg(0.0, duration, 1.0)]
    peak = min(max(0.0, float(peak)), duration)
    slow_start = max(0.0, peak - 0.25)
    slow_end = min(duration, peak + max(1.0, slow_hold))
    segs: list[SpeedSeg] = []
    if slow_start > 0.12:
        segs.append(SpeedSeg(0.0, slow_start, fast))
    segs.append(SpeedSeg(slow_start, slow_end, slow))
    if slow_end < duration - 0.05:
        segs.append(SpeedSeg(slow_end, duration, min(fast, 1.2)))
    return segs or [SpeedSeg(0.0, duration, 1.0)]


def output_duration(segs: list[SpeedSeg]) -> float:
    return sum(s.out_duration for s in segs)


def src_to_out(t: float, segs: list[SpeedSeg]) -> float:
    acc = 0.0
    for seg in segs:
        if t <= seg.src_start:
            return acc
        if t < seg.src_end:
            return acc + (t - seg.src_start) / max(seg.speed, 0.05)
        acc += seg.out_duration
    return acc


def speed_filter(
    segs: list[SpeedSeg],
    *,
    v_in: str = "v0",
    a_in: str = "a0",
    v_out: str = "v",
    a_out: str = "a",
) -> tuple[str, str] | None:
    """Return (video_fc, audio_fc). Pads default to v0/a0 in, v/a out.

    Splits the input so each trim can read it. None when everything is 1x.
    """
    if not segs or (len(segs) == 1 and abs(segs[0].speed - 1.0) < 0.01):
        return None
    n = len(segs)
    v_split = "".join(f"[vsrc{i}]" for i in range(n))
    a_split = "".join(f"[asrc{i}]" for i in range(n))
    v_parts = [f"[{v_in}]split={n}{v_split}"]
    a_parts = [f"[{a_in}]asplit={n}{a_split}"]
    v_labels = []
    a_labels = []
    for i, seg in enumerate(segs):
        vlab, alab = f"vs{i}", f"as{i}"
        v_parts.append(
            f"[vsrc{i}]trim=start={seg.src_start:.4f}:end={seg.src_end:.4f},setpts=PTS-STARTPTS,"
            f"setpts={1.0 / seg.speed:.5f}*PTS[{vlab}]"
        )
        # atempo accepts 0.5–2.0; our ramps stay in that range.
        a_parts.append(
            f"[asrc{i}]atrim=start={seg.src_start:.4f}:end={seg.src_end:.4f},asetpts=PTS-STARTPTS,"
            f"atempo={seg.speed:.3f}[{alab}]"
        )
        v_labels.append(f"[{vlab}]")
        a_labels.append(f"[{alab}]")
    v_parts.append("".join(v_labels) + f"concat=n={n}:v=1:a=0[{v_out}]")
    a_parts.append("".join(a_labels) + f"concat=n={n}:v=0:a=1[{a_out}]")
    return ";".join(v_parts), ";".join(a_parts)


def snap_calm_end(
    video: Path | str | None,
    start: float,
    end: float,
    peak: float | None,
    *,
    enabled: bool = True,
    min_hold: float = 1.2,
) -> float:
    """Nudge the out-point back to a calmer frame so the clip loops into the start."""
    if not enabled or video is None:
        return end
    duration = end - start
    if duration < 4.0:
        return end
    floor = start + 3.0
    if peak is not None:
        floor = max(floor, float(peak) + min_hold)
    if floor >= end - 0.2:
        return end
    try:
        times, diffs = _motion_tail(Path(video), max(floor, end - 1.6), end)
    except Exception:
        return end
    if times.size < 3 or diffs.size < 3:
        return end
    # If the last ~0.28s is already as calm as the rest of the tail, keep the end.
    last_cut = times[-1] - 0.28
    last = diffs[times >= last_cut] if last_cut > times[0] else diffs[-2:]
    body = diffs[times < last_cut] if last_cut > times[0] else diffs
    if last.size and body.size and float(last.mean()) <= float(np.median(body)) * 1.15:
        return end
    # Prefer the calmest frame, breaking ties toward the original end.
    best_i = int(np.argmin(diffs + 0.02 * (times[-1] - times)))
    chosen = float(times[best_i]) + 0.08
    return max(floor, min(end, chosen))


def _motion_tail(video: Path, start: float, end: float, fps: float = 8.0):
    """Raw mean-abs frame diffs for a short window. Times are absolute."""
    import subprocess

    import numpy as np

    from clipper.ffmpeg_utils import find_ffmpeg

    width, height = 160, 90
    probe_dur = max(0.3, end - start)
    ffmpeg = find_ffmpeg()
    args = [
        ffmpeg, "-v", "error",
        "-ss", f"{max(0.0, start):.3f}",
        "-t", f"{probe_dur:.3f}",
        "-i", str(video),
        "-vf", f"fps={fps},scale={width}:{height},format=gray",
        "-f", "rawvideo", "pipe:1",
    ]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    prev = None
    diffs, times = [], []
    t = float(start)
    hop = 1.0 / fps
    frame_size = width * height
    try:
        while True:
            data = proc.stdout.read(frame_size)
            if not data or len(data) < frame_size:
                break
            frame = np.frombuffer(data, dtype="uint8").astype("float32")
            if prev is not None:
                diffs.append(float(np.mean(np.abs(frame - prev))))
                times.append(t)
            prev = frame
            t += hop
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
    import numpy as np

    return np.array(times, dtype="float64"), np.array(diffs, dtype="float64")


# --- curiosity-gap hooks & titles ------------------------------------------------

_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "it", "its", "this", "that", "i",
    "you", "he", "she", "we", "they", "me", "my", "your", "our", "be", "am",
    "are", "was", "were", "have", "has", "had", "do", "does", "did", "not",
    "so", "just", "very", "too", "can", "will", "would", "about", "into",
    "then", "than", "ok", "okay", "yeah", "uh", "um", "like", "really",
}

_GENERIC = {
    "wait for it", "wait for this", "you won't believe", "you wont believe",
    "watch this", "don't blink", "dont blink", "just wait",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _is_generic(text: str) -> bool:
    c = _clean(text).lower().strip(" .!?")
    return c in _GENERIC or c.startswith("wait for it") or c.startswith("you won't believe")


def pick_keywords(text: str, limit: int = 2) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z']{2,}", text or "")
    scored = []
    seen = set()
    for tok in tokens:
        low = re.sub(r"[^a-z']", "", tok.lower())
        if low in _STOP or low in seen or len(low) < 4:
            continue
        seen.add(low)
        score = len(low) + (2 if tok[:1].isupper() else 0)
        scored.append((score, tok))
    scored.sort(key=lambda r: -r[0])
    return [t for _s, t in scored[:limit]]


def _apply_case(text: str, hook_case: str) -> str:
    text = _clean(text)
    if hook_case == "upper":
        return text.upper()
    # Title case, but keep short all-caps tokens
    parts = []
    for w in text.split():
        parts.append(w if (w.isupper() and len(w) > 1) else w.capitalize())
    return " ".join(parts)


def _strip_leading_filler(text: str) -> str:
    return re.sub(r"^(so|and|but|well|okay|ok|like|just|then)\s+", "", text.strip(), flags=re.I)


def build_hook_banner(
    transcript: Transcript,
    start: float,
    end: float,
    *,
    peak: float | None,
    peak_kind: str = "",
    hook_case: str = "title",
    existing: str = "",
) -> HookBanner:
    """Curiosity-gap hook that stays true to the payoff. Never a fake promise."""
    from clipper.moments import make_hook, _is_generic_hook

    words = transcript.words_in(start, end) if hasattr(transcript, "words_in") else []
    text = transcript.text_in(start, end) if hasattr(transcript, "text_in") else ""
    has_speech = bool(words or (text or "").strip())
    if not has_speech:
        return HookBanner(text="", titles=["Clip"])

    # Split into sentence-like phrases.
    phrases: list[tuple[str, float]] = []
    buf, buf_t = [], None
    for w in words:
        if buf_t is None:
            buf_t = w.start
        buf.append(w.word)
        if w.word.endswith((".", "!", "?")) or (w.start - buf_t) > 4.5:
            phrases.append((_clean(" ".join(buf)), buf_t or start))
            buf, buf_t = [], None
    if buf:
        phrases.append((_clean(" ".join(buf)), buf_t or start))

    hook = ""
    # 1) A short real question is already a curiosity gap ("Is that a smile?").
    questions = [(p, t) for p, t in phrases if p.endswith("?") and 2 <= len(p.split()) <= 10]
    if questions:
        # Prefer a question near the payoff, else the first one.
        if peak is not None:
            questions.sort(key=lambda pt: abs(pt[1] - peak))
        hook = questions[0][0]

    # 2) "When {real clause}..." from setup before the peak.
    if not hook:
        before = [(p, t) for p, t in phrases if peak is None or t <= (peak + 0.2)]
        candidates = []
        for p, t in before:
            clause = _strip_leading_filler(p).rstrip(".!")
            n = len(clause.split())
            if 3 <= n <= 9 and not _is_generic(clause) and not clause.endswith("?"):
                candidates.append(clause)
        if candidates:
            # Shorter, earlier clauses make better "When..." teasers.
            clause = min(candidates, key=len)
            hook = "When " + clause[0].lower() + clause[1:] if clause[0].isupper() and not clause.startswith("I ") else "When " + clause

    # 3) Incomplete tease from a punchy phrase ("The Art Of...").
    if not hook:
        for p, t in phrases:
            clause = _strip_leading_filler(p).rstrip(".!?")
            toks = clause.split()
            if 3 <= len(toks) <= 6 and not _is_generic(clause):
                hook = " ".join(toks[:4]).rstrip(",;") + "..."
                break

    # 4) Fall back to a specific spoken line (never a fake WAIT FOR IT).
    if not hook or _is_generic(hook):
        spoken, _title = make_hook(transcript, start, end, peak=peak, peak_kind=peak_kind)
        if spoken and not _is_generic_hook(spoken):
            hook = spoken
        elif existing and not _is_generic_hook(existing):
            hook = existing
        else:
            hook = ""

    hook = _clean(hook).strip(" ,;")
    if _is_generic(hook):
        hook = ""
    hook = _apply_case(hook, hook_case)
    keywords = pick_keywords(hook, 2) if hook else []

    emoji = ""
    kind = (peak_kind or "").lower()
    if hook:
        if kind in {"laugh"}:
            emoji = "😂"
        elif kind in {"reaction"}:
            emoji = "😳"
        elif kind in {"action", "scene-change"} and hook_case == "upper":
            emoji = "🔥"

    titles = suggest_titles(hook, peak_kind=kind, has_speech=has_speech)
    return HookBanner(text=hook, keywords=keywords, emoji=emoji, titles=titles)


def suggest_titles(hook: str, *, peak_kind: str = "", has_speech: bool = True) -> list[str]:
    """Title options in curiosity / 'don't check the sound' styles. No false promises."""
    titles: list[str] = []
    base = _clean(hook).rstrip(".…")
    if base:
        titles.append(base)
        if (
            not base.lower().startswith("when ")
            and not base.endswith("?")
            and not base.lower().startswith(("what ", "why ", "how ", "who ", "is ", "are "))
        ):
            titles.append("When " + base[0].lower() + base[1:] if base[0].isupper() else "When " + base)
    if peak_kind in {"laugh", "loud"} and has_speech:
        # Only when the payoff really is on the soundtrack.
        titles.append("Don't check the sound")
    # Dedup, keep order, cap length.
    out, seen = [], set()
    for t in titles:
        t = _clean(t)
        if not t or t.lower() in seen or len(t) > 80:
            continue
        seen.add(t.lower())
        out.append(t)
    return out[:4] or ["Clip"]


def colorize_keywords(text: str, keywords: list[str]) -> str:
    """Wrap up to two keywords in ASS yellow tags. Text is already ASS-escaped."""
    if not text or not keywords:
        return text
    used = 0
    result = text
    for raw in keywords:
        if used >= 2:
            break
        word = raw.strip()
        if not word:
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9])({re.escape(word)})(?![A-Za-z0-9])", re.I)

        def _repl(m, _used=used):
            return f"{KEYWORD_COLOUR}{m.group(1)}{KEYWORD_RESET}"

        new, n = pattern.subn(_repl, result, count=1)
        if n:
            result = new
            used += 1
    return result
