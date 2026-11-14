"""Map each script sentence to short, non-continuous movie shots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from clipper.recap_script import RecapLine
from clipper.transcribe import Transcript

# Recap-channel cuts stay short so the original scene never plays out in full.
MIN_SHOT = 2.0
MAX_SHOT = 5.0
# Transformative playback rate (applied at render time).
PLAY_SPEED = 1.05

BEAT_WINDOW = {
    "hook": (0.02, 0.22),
    "setup": (0.06, 0.38),
    "conflict": (0.28, 0.72),
    "twist": (0.62, 0.92),
    "cta": (0.82, 0.96),
}


@dataclass
class Scene:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2.0


@dataclass
class Shot:
    src_start: float
    src_end: float
    line_index: int
    beat: str
    mirror: bool = False
    zoom: float = 1.08
    # How long this shot should last on the output timeline (after speed).
    out_duration: float = 0.0
    reason: str = ""


def detect_scenes(video: Path | str | None, duration: float, progress=None) -> list[Scene]:
    log = progress or (lambda *_a, **_k: None)
    if not video or not Path(video).is_file() or duration <= 0:
        return []
    video = Path(video)
    scenes = _pyscenedetect(video, log)
    if not scenes:
        log("PySceneDetect unavailable or found nothing; using frame-difference cuts")
        scenes = _diff_scenes(video, duration)
    # Drop tiny flashes and opening/closing credits-ish slivers.
    cleaned: list[Scene] = []
    for s in scenes:
        a, b = max(0.0, s.start), min(duration, s.end)
        if b - a < 0.8:
            if cleaned:
                cleaned[-1] = Scene(cleaned[-1].start, b)
            continue
        cleaned.append(Scene(a, b))
    if not cleaned:
        # Even grid so we still have cut points.
        step = 4.0
        t = 0.4
        while t < duration - 1.0:
            cleaned.append(Scene(t, min(duration, t + step)))
            t += step
    log(f"Found {len(cleaned)} scenes in {duration:.0f}s")
    return cleaned


def _pyscenedetect(video: Path, log) -> list[Scene]:
    try:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import ContentDetector
    except Exception:
        return []
    try:
        vid = open_video(str(video))
        mgr = SceneManager()
        mgr.add_detector(ContentDetector(threshold=27.0, min_scene_len=15))
        mgr.detect_scenes(vid, show_progress=False)
        raw = mgr.get_scene_list()
        out = []
        for a, b in raw:
            out.append(Scene(a.get_seconds(), b.get_seconds()))
        return out
    except Exception as exc:  # noqa: BLE001
        log(f"PySceneDetect failed ({exc})")
        return []


def _diff_scenes(video: Path, duration: float) -> list[Scene]:
    from clipper.visual_peaks import frame_diff_series

    times, z = frame_diff_series(video, duration, fps=4.0)
    if times.size < 4:
        return []
    cuts = [0.0]
    for t, v in zip(times, z):
        if v >= 2.2 and t - cuts[-1] >= 1.6:
            cuts.append(float(t))
    cuts.append(duration)
    return [Scene(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]


def load_srt(path: Path | str) -> Transcript:
    """Parse a simple .srt into a Transcript (word times estimated per cue)."""
    from clipper.transcribe import Word, Segment, Transcript, _join_words

    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").strip())
    words: list[Word] = []
    segs: list[Segment] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        # Skip index-only first line
        if lines[0].isdigit() and len(lines) > 1:
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start, end = _parse_srt_times(lines[0])
        text = re.sub(r"<[^>]+>", "", " ".join(lines[1:])).strip()
        if start is None or not text:
            continue
        segs.append(Segment(start, end, text))
        toks = re.findall(r"[A-Za-z0-9']+|[.,!?]", text)
        toks = [t for t in toks if not re.fullmatch(r"[.,!?]", t)]
        if not toks:
            continue
        span = max(0.1, end - start)
        step = span / len(toks)
        for i, tok in enumerate(toks):
            words.append(Word(tok, start + i * step, start + (i + 1) * step))
    duration = words[-1].end if words else (segs[-1].end if segs else 0.0)
    text = _join_words([w.word for w in words]) or " ".join(s.text for s in segs)
    return Transcript(text=text, language="en", segments=segs, words=words, duration=duration)


def _parse_srt_times(line: str) -> tuple[float | None, float | None]:
    m = re.search(
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})",
        line,
    )
    if not m:
        return None, None
    g = [int(x) for x in m.groups()]
    def ts(h, m_, s, ms):
        if ms < 10:
            ms *= 100
        elif ms < 100:
            ms *= 10
        return h * 3600 + m_ * 60 + s + ms / 1000.0
    return ts(*g[:4]), ts(*g[4:])


def align_shots(
    lines: list[RecapLine],
    line_durations: list[float],
    scenes: list[Scene],
    transcript: Transcript | None,
    movie_duration: float,
    *,
    mirror: bool = True,
    progress=None,
) -> list[Shot]:
    """Cover each spoken line with 2–5 s shots, never a long continuous take."""
    log = progress or (lambda *_a, **_k: None)
    if not lines:
        return []
    used: list[tuple[float, float]] = []
    shots: list[Shot] = []
    for i, (line, vo_dur) in enumerate(zip(lines, line_durations)):
        vo_dur = max(1.2, float(vo_dur))
        # After PLAY_SPEED the clip is shorter, so pull a little extra source.
        need = vo_dur * PLAY_SPEED
        pieces = _split_need(need)
        center, why = _target_time(line, transcript, movie_duration)
        for j, piece in enumerate(pieces):
            start, end, scene_why = _pick_window(
                center if j == 0 else center + 3.0 * j,
                piece,
                scenes,
                movie_duration,
                used,
            )
            used.append((start, end))
            zoom = 1.06 + (0.02 * ((i + j) % 4))
            shots.append(
                Shot(
                    src_start=start,
                    src_end=end,
                    line_index=i,
                    beat=line.beat,
                    mirror=bool(mirror and ((i + j) % 3 == 2)),
                    zoom=zoom,
                    out_duration=min(MAX_SHOT, (end - start) / PLAY_SPEED),
                    reason=why if j == 0 else scene_why,
                )
            )
    log(f"Planned {len(shots)} shots for {len(lines)} lines")
    return shots


def _split_need(need: float) -> list[float]:
    """Split a needed source duration into 2–5 s pieces (cuts every 2–4 s out)."""
    if need <= MAX_SHOT:
        return [max(MIN_SHOT, need)]
    pieces = []
    left = need
    while left > 0.15:
        # Prefer ~3.2 s source pieces.
        take = 3.4 if left > MAX_SHOT + 0.4 else left
        take = min(MAX_SHOT, max(MIN_SHOT, take))
        if left - take < 1.2 and left > MAX_SHOT:
            take = left / 2.0
        pieces.append(take)
        left -= take
        if len(pieces) > 12:
            break
    return pieces or [MIN_SHOT]


def _target_time(line: RecapLine, transcript: Transcript | None, duration: float) -> tuple[float, str]:
    lo_frac, hi_frac = BEAT_WINDOW.get(line.beat, (0.1, 0.9))
    beat_lo, beat_hi = duration * lo_frac, duration * hi_frac
    beat_mid = (beat_lo + beat_hi) / 2.0
    if transcript and (transcript.words or transcript.segments):
        hit = _keyword_time(line, transcript, beat_lo, beat_hi)
        if hit is not None:
            return hit, "transcript keyword"
        # Broader search
        hit = _keyword_time(line, transcript, 0.0, duration)
        if hit is not None:
            return hit, "transcript keyword (whole film)"
    return beat_mid, f"beat window {line.beat}"


def _keyword_time(line: RecapLine, transcript: Transcript, lo: float, hi: float) -> float | None:
    needles = [k.lower() for k in (line.keywords or []) if len(k) >= 3]
    needles += [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9']{3,}", line.text)]
    stop = {"this", "that", "with", "from", "they", "them", "have", "what", "when", "then", "into"}
    needles = [n for n in needles if n not in stop]
    if not needles:
        return None
    best_t, best = None, 0
    words = transcript.words or []
    if words:
        # Sliding window of ~6 s
        i = 0
        while i < len(words):
            t0 = words[i].start
            if t0 > hi:
                break
            j = i
            bag = []
            while j < len(words) and words[j].end - t0 <= 6.0:
                bag.append(words[j].word.lower().strip(".,!?"))
                j += 1
            if t0 + 3.0 >= lo:
                score = sum(1 for n in needles if n in bag or any(n in b or b in n for b in bag if len(b) >= 4))
                if score > best:
                    best, best_t = score, t0 + 1.0
            i += 2
    if best >= 2 or (best >= 1 and best_t is not None):
        return best_t
    return None


def _pick_window(
    center: float,
    length: float,
    scenes: list[Scene],
    duration: float,
    used: list[tuple[float, float]],
) -> tuple[float, float, str]:
    length = min(MAX_SHOT, max(MIN_SHOT, length))
    # Prefer a scene that contains the target and hasn't been heavily used.
    candidates = list(scenes) or [Scene(0.0, duration)]
    scored = []
    for sc in candidates:
        overlap_used = sum(_overlap(sc.start, sc.end, a, b) for a, b in used)
        dist = abs(sc.mid - center)
        # Prefer scenes long enough to hold the shot, close to the target, unused.
        score = -dist - overlap_used * 8.0 + min(sc.duration, 8.0) * 0.15
        scored.append((score, sc))
    scored.sort(key=lambda x: -x[0])
    for _score, sc in scored[:8]:
        start, end = _window_inside(sc, center, length, duration)
        if start is None:
            continue
        if any(_overlap(start, end, a, b) > 1.0 for a, b in used):
            # Try a different slice of the same scene.
            start, end = _window_inside(sc, sc.start + 0.4, length, duration)
            if start is None or any(_overlap(start, end, a, b) > 1.0 for a, b in used):
                continue
        return start, end, "scene cut"
    # Last resort: clamp around the center, still short.
    start = min(max(0.2, center - length / 2.0), max(0.0, duration - length - 0.2))
    end = min(duration - 0.05, start + length)
    return start, end, "fallback window"


def _window_inside(sc: Scene, center: float, length: float, duration: float) -> tuple[float | None, float | None]:
    if sc.duration < 1.2:
        return None, None
    length = min(length, max(MIN_SHOT, sc.duration - 0.15), MAX_SHOT)
    start = center - length / 2.0
    start = max(sc.start + 0.05, min(start, sc.end - length - 0.05))
    end = start + length
    if end > sc.end - 0.02:
        end = sc.end - 0.02
        start = end - length
    start = max(0.0, start)
    end = min(duration, end)
    if end - start < 1.2:
        return None, None
    return start, end


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))
