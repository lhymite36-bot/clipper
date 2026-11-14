"""Pick the top N viral moments: a real payoff, then a window that ends just after it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from clipper.audio_peaks import load_mono_f32, rms_series, zscore
from clipper.transcribe import Transcript, Word

# Payoff cues: the moment something lands (a laugh, a gasp, a punchline).
LAUGHTER = {
    "haha", "hahaha", "hahahaha", "ha", "lol", "lmao", "lmfao", "rofl",
    "laugh", "laughs", "laughing", "laughed", "giggle", "giggles",
    "chuckle", "hilarious", "funny", "joke", "burst",
}
REACTION = {
    "wow", "whoa", "whoah", "omg", "insane", "crazy", "unbelievable",
    "shocked", "shocking", "holy", "unreal", "wild", "amazing",
    "no", "way", "what", "bruh", "dude", "bro", "yes", "oh",
    "whoops", "oops", "yikes", "whoa", "jeez", "dang", "damn",
    "stop", "cannot", "can't", "won't", "never", "huge",
    "knew", "smile", "smiling",
}
PUNCHLINE = {
    "actually", "secret", "truth", "because", "that's", "thats",
    "exactly", "precisely", "boom", "done", "dead", "gone",
    "finally", "revealed", "answer",
}

# Setup cues help place the start of the clip, but they are not the payoff.
SETUP = {
    "wait", "here's", "heres", "look", "listen", "remember", "before",
    "today", "welcome", "so", "okay", "ok", "alright", "first",
    "story", "happened", "watch", "see",
}

QUESTION_STARTS = {"why", "how", "what", "when", "where", "who", "is", "are", "do", "did", "can", "should"}

GENERIC_HOOKS = {
    "wait for it",
    "wait for it!",
    "wait for this",
    "wait for this!",
    "you won't believe",
    "you wont believe",
    "you won't believe this",
    "you have to see this",
    "watch this",
    "watch this!",
    "don't blink",
    "dont blink",
    "just wait",
    "just wait!",
    "you have to see",
}

HOLD_MIN = 1.5
HOLD_MAX = 4.0
# Soft hold when nothing else is coming. Hard cuts / the next sentence
# may land sooner; we still require a tiny gap after the peak.
REACTION_MIN = 0.55
HARD_STOP_MIN = 0.2
# Peak must sit in the last ~30% of the clip (0.5s slack).
PAYOFF_POSITION = 0.70
PAYOFF_SLACK = 0.5
MIN_PEAK_SCORE = 1.7
NMS_SECONDS = 8.0


@dataclass
class Payoff:
    time: float
    score: float
    kind: str
    label: str


@dataclass
class Moment:
    start: float
    end: float
    score: float
    reason: str
    hook: str
    title: str = ""
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    source: str = "heuristic"  # heuristic | llm
    peak: float | None = None
    peak_kind: str = ""
    title_options: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def payoff_in_last_30(self) -> bool:
        if self.peak is None or self.duration <= 0:
            return False
        return self.peak + PAYOFF_SLACK >= self.start + PAYOFF_POSITION * self.duration

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "score": round(self.score, 3),
            "reason": self.reason,
            "hook": self.hook,
            "title": self.title,
            "description": self.description,
            "hashtags": self.hashtags,
            "source": self.source,
            "peak": None if self.peak is None else round(self.peak, 3),
            "peak_kind": self.peak_kind,
            "title_options": list(self.title_options),
        }


def _norm_token(word: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", word.lower())


def word_score(token: str) -> float:
    """General punchiness (used in tests and hook ranking)."""
    t = _norm_token(token)
    if not t:
        return 0.0
    score = 0.0
    if t in LAUGHTER:
        score += 3.0
    if t in REACTION:
        score += 2.0
    if t in PUNCHLINE:
        score += 1.2
    if t in SETUP:
        score += 0.4
    if t in QUESTION_STARTS:
        score += 0.6
    if token.isupper() and len(token) > 2:
        score += 0.8
    if token.endswith("!"):
        score += 0.7
    if token.endswith("?"):
        score += 0.9
    return score


def payoff_word_score(token: str) -> float:
    """Score a word only if it looks like a payoff, not a setup."""
    t = _norm_token(token)
    if not t or t in SETUP:
        return 0.0
    score = 0.0
    if t in LAUGHTER:
        score += 3.2
    if t in REACTION:
        score += 2.0
    if t in PUNCHLINE:
        score += 1.1
    if token.endswith("!"):
        score += 0.7
    if token.endswith("?") and t in REACTION | {"what", "why", "who"}:
        score += 0.8
    if token.isupper() and len(token) > 2 and t in REACTION | LAUGHTER:
        score += 0.5
    return score


def _sentence_bounds(transcript: Transcript, duration: float) -> list[tuple[float, float]]:
    bounds: list[tuple[float, float]] = []
    words = transcript.words
    if not words:
        for s in transcript.segments:
            bounds.append((s.start, s.end))
        return bounds or [(0.0, duration)]

    start = words[0].start
    prev = words[0]
    for w in words[1:]:
        gap = w.start - prev.end
        punct = prev.word.rstrip().endswith((".", "!", "?", ";", ":"))
        if gap >= 0.45 or punct:
            bounds.append((start, prev.end))
            start = w.start
        prev = w
    bounds.append((start, words[-1].end))
    return bounds


def _energy_profile(wav: Path | None, duration: float, hop: float = 0.25) -> tuple[np.ndarray, np.ndarray]:
    if wav and Path(wav).is_file():
        samples = load_mono_f32(Path(wav))
        times, rms = rms_series(samples, hop=hop)
        if times.size:
            return times, zscore(rms)
    n = max(1, int(duration / hop))
    return np.arange(n) * hop, np.zeros(n)


def _value_at(times: np.ndarray, values: np.ndarray, t: float) -> float:
    if times.size == 0:
        return 0.0
    idx = int(np.clip(np.searchsorted(times, t), 0, len(values) - 1))
    return float(values[idx])


def detect_payoffs(
    transcript: Transcript,
    duration: float,
    *,
    wav: Path | None = None,
    video: Path | None = None,
    hop: float = 0.25,
) -> list[Payoff]:
    """Find laugh / reaction / loud-spike / scene-change / action peaks."""
    duration = float(duration or transcript.duration or 0.0)
    if duration <= 0:
        return []

    times, energy = _energy_profile(wav, duration, hop=hop)
    scene_t = scene_z = np.zeros(0)
    if video and Path(video).is_file():
        try:
            from clipper.visual_peaks import frame_diff_series

            scene_t, scene_z = frame_diff_series(video, duration)
        except Exception:
            scene_t, scene_z = np.zeros(0), np.zeros(0)

    n = max(1, int(np.ceil(duration / hop)))
    scores = np.zeros(n, dtype=np.float64)
    kinds: list[list[str]] = [[] for _ in range(n)]
    labels: list[list[str]] = [[] for _ in range(n)]

    for w in transcript.words or []:
        s = payoff_word_score(w.word)
        if s <= 0:
            continue
        idx = int(np.clip(w.start / hop, 0, n - 1))
        scores[idx] += s
        tag = _norm_token(w.word)
        kind = "laugh" if tag in LAUGHTER else "punchline" if tag in PUNCHLINE else "reaction"
        if kind not in kinds[idx]:
            kinds[idx].append(kind)
        if tag and tag not in labels[idx] and len(labels[idx]) < 4:
            labels[idx].append(tag)

    for i in range(n):
        t = (i + 0.5) * hop
        e = _value_at(times, energy, t)
        # Onset: a rise against the local floor is a real spike, not just loud music.
        prev_e = _value_at(times, energy, max(0.0, t - 0.5))
        if e >= 1.7 and e > prev_e + 0.4:
            scores[i] += min(e, 4.0) * 1.15
            if "loud" not in kinds[i]:
                kinds[i].append("loud")
            if e >= 2.0 and "loud spike" not in labels[i]:
                labels[i].append("loud spike")
        elif e >= 2.4:
            scores[i] += min(e, 4.0)
            if "loud" not in kinds[i]:
                kinds[i].append("loud")
        sc = _value_at(scene_t, scene_z, t)
        if sc >= 2.0:
            scores[i] += min(sc, 4.0) * 0.9
            kind = "scene-change" if sc < 3.2 else "action"
            if kind not in kinds[i]:
                kinds[i].append(kind)
            if kind not in labels[i]:
                labels[i].append(kind)

    # Local maxima above the quality bar, highest first.
    payoffs: list[Payoff] = []
    order = list(np.argsort(-scores))
    taken: list[float] = []
    for idx in order:
        if scores[idx] < MIN_PEAK_SCORE:
            break
        # Must be a local max in a ±2-bin neighborhood
        lo, hi = max(0, idx - 2), min(n, idx + 3)
        if scores[idx] < float(np.max(scores[lo:hi])) - 1e-9:
            continue
        if not kinds[idx]:
            continue
        t = (idx + 0.5) * hop
        kind = kinds[idx][0]
        # Prefer a more specific kind if present
        for preferred in ("laugh", "reaction", "punchline", "action", "loud", "scene-change"):
            if preferred in kinds[idx]:
                kind = preferred
                break
        payoffs.append(
            Payoff(
                time=float(t),
                score=float(scores[idx]),
                kind=kind,
                label=", ".join(labels[idx][:4] or kinds[idx][:3]),
            )
        )
    # Nearby peaks are one beat: keep the later landing when scores are close,
    # so a setup reaction ("oh", "what") does not cut off the actual punchline.
    payoffs.sort(key=lambda p: -p.score)
    kept: list[Payoff] = []
    for p in payoffs:
        conflict = [k for k in kept if abs(k.time - p.time) < NMS_SECONDS]
        if not conflict:
            kept.append(p)
            continue
        for k in list(conflict):
            if p.time > k.time and p.score >= 0.65 * k.score:
                kept.remove(k)
                kept.append(p)
                break
    kept.sort(key=lambda p: -p.score)
    return kept


def speech_breaks(transcript: Transcript, min_gap: float = 0.7) -> list[float]:
    """Times just after a pause in speech — natural places to end a clip."""
    words = [w for w in (transcript.words or []) if (w.word or "").strip()]
    breaks: list[float] = []
    for a, b in zip(words, words[1:]):
        if b.start - a.end >= min_gap:
            breaks.append(float(a.end + 0.08))
    return breaks


def scene_cuts(
    video: Path | str | None,
    duration: float,
    *,
    threshold: float = 3.5,
) -> list[float]:
    """Hard cuts from z-scored frame differences. Empty if video is missing."""
    if not video or not Path(video).is_file() or duration <= 0:
        return []
    try:
        from clipper.visual_peaks import frame_diff_series

        times, z = frame_diff_series(Path(video), duration)
    except Exception:
        return []
    if times.size == 0:
        return []
    cuts: list[float] = []
    last = -10.0
    z = [float(v) for v in z]
    for i, t in enumerate(times):
        v = z[i]
        prev = z[i - 1] if i else 0.0
        nxt = z[i + 1] if i + 1 < len(z) else 0.0
        isolated = v >= 2.3 and v >= max(prev, nxt) + 1.2
        if (v >= threshold or isolated) and t - last >= 0.4:
            cuts.append(float(t))
            last = float(t)
    return cuts


def _preferred_end(
    peak: float,
    duration: float,
    bounds: list[tuple[float, float]],
    *,
    cuts: list[float] | None = None,
    breaks: list[float] | None = None,
    hold: float = 2.8,
) -> float:
    """End just after the payoff, but stop before the next scene or sentence."""
    cap = min(duration, peak + HOLD_MAX)
    earliest_hard = min(duration, peak + HARD_STOP_MIN)
    earliest_soft = min(duration, peak + REACTION_MIN)
    stops: list[float] = []
    # Subtract a couple of frames so the first picture of the next shot
    # is not included in the last frame of the clip.
    pad = 0.08
    # A cut at the peak is the end of this shot — don't hold past it.
    for t in list(cuts or []):
        if peak - 0.02 <= t <= cap:
            stops.append(min(cap, max(peak, t - pad)))
    for t in list(breaks or []):
        if earliest_hard <= t <= cap:
            stops.append(t - pad)
    # Do not eat the next sentence: stop just before it starts.
    for a, _b in bounds or []:
        if peak + 0.05 < a <= cap:
            stops.append(max(earliest_hard, a - pad))
            break
    if stops:
        return min(max(min(stops), peak), cap)
    return min(cap, max(earliest_soft, peak + hold))


def window_around_payoff(
    peak: float,
    duration: float,
    bounds: list[tuple[float, float]],
    min_dur: float,
    max_dur: float,
    hold: float = 2.8,
    cuts: list[float] | None = None,
    breaks: list[float] | None = None,
) -> tuple[float, float] | None:
    """Start during the setup; end just after the payoff. Peak stays in the last 30%."""
    duration = float(duration)
    if duration <= 0 or peak < 0 or peak > duration:
        return None

    # Whole-video clip when the source is already short.
    if duration <= min_dur + 1:
        if peak + PAYOFF_SLACK >= PAYOFF_POSITION * duration or duration <= 8:
            return 0.0, duration
        # Peak is too early in a short file — still allow the whole clip if
        # we can end shortly after the peak (the file itself ends there).
        if peak >= duration - HOLD_MAX - 0.5:
            return 0.0, duration
        return None

    hold = min(HOLD_MAX, max(HOLD_MIN, hold))
    end = _preferred_end(peak, duration, bounds, cuts=cuts, breaks=breaks, hold=hold)
    # Don't raise a hard-stop (scene cut / next sentence) back up to a
    # minimum hold — that is how clips used to walk into the next shot.
    end = min(duration, max(end, peak))

    # If the payoff is late enough, we can stretch `end` slightly so a
    # min-duration clip starting at 0 still keeps the peak in the last 30%.
    # end <= (peak + slack) / PAYOFF_POSITION
    max_end_for_last30 = (peak + PAYOFF_SLACK) / PAYOFF_POSITION
    if end - 0.0 < min_dur and duration >= min_dur:
        stretch = min(duration, max_end_for_last30, max(end, min_dur))
        # Don't travel far past the payoff — a little slack past HOLD_MAX is ok
        # when it's the only way to reach min_dur.
        if stretch <= peak + HOLD_MAX + 1.25:
            end = max(end, stretch)

    def latest_start_for(end_t: float) -> float:
        # start <= (peak + slack - PAYOFF_POSITION * end) / (1 - PAYOFF_POSITION)
        last30 = (peak + PAYOFF_SLACK - PAYOFF_POSITION * end_t) / (1.0 - PAYOFF_POSITION)
        target_min = end_t - min(min_dur, end_t)
        return min(last30, target_min, end_t - 1.0)

    start_hi = latest_start_for(end)
    start_lo = max(0.0, end - max_dur)
    # If the payoff is close to t=0, no legal window exists — drop it.
    if start_hi < start_lo - 0.05:
        return None
    start_hi = max(start_lo, start_hi)

    target = min(max(min_dur, 18.0), max_dur, end - start_lo)
    desired = min(max(end - target, start_lo), start_hi)
    if bounds:
        snaps = [a for a, _b in bounds if start_lo - 0.25 <= a <= start_hi + 0.25]
        if snaps:
            desired = min(snaps, key=lambda a: abs(a - desired))
            desired = min(max(desired, start_lo), start_hi)
    start = max(0.0, min(desired, end - 1.0))
    if end - start < min(min_dur, duration) - 0.6:
        # Nudge the start earlier if the last-30% rule still holds.
        need = min(min_dur, duration) - (end - start)
        trial = max(0.0, start - need)
        if peak + PAYOFF_SLACK >= trial + PAYOFF_POSITION * (end - trial):
            start = trial
        elif end < duration:
            end = min(duration, start + min(min_dur, duration))
            if peak + HOLD_MIN > end or peak + PAYOFF_SLACK < start + PAYOFF_POSITION * (end - start):
                return None
    start = max(0.0, start)
    end = min(duration, end)
    if end <= start:
        return None
    if peak + PAYOFF_SLACK < start + PAYOFF_POSITION * (end - start):
        return None
    if end < peak:
        return None
    return start, end


# Back-compat alias used by older tests; now payoff-aware.
def _grow_window(
    peak: float,
    duration: float,
    bounds: list[tuple[float, float]],
    min_dur: float,
    max_dur: float,
) -> tuple[float, float]:
    got = window_around_payoff(peak, duration, bounds, min_dur, max_dur)
    if got:
        return got
    # Last resort for the unit test that only checks bounds: a legal window if possible.
    end = min(duration, peak + 3.0)
    start = max(0.0, end - min_dur)
    return start, end


def _is_generic_hook(text: str) -> bool:
    compact = re.sub(r"\s+", " ", (text or "").strip().lower()).strip(" .!?")
    if compact in GENERIC_HOOKS:
        return True
    # "wait for it something" still counts as generic
    return compact.startswith("wait for it") or compact.startswith("you won't believe")


def _join_words(parts: list[str]) -> str:
    out = ""
    for p in parts:
        token = p.strip()
        if not token:
            continue
        if out and token[0] not in ",.!?;:)'\"" and not token.startswith("'"):
            out += " "
        out += token
    return out.strip()


def _phrases_from_words(words: list[Word], max_words: int = 8) -> list[tuple[str, float, float, float]]:
    """Return (text, start, end, punch_score) phrases."""
    if not words:
        return []
    groups: list[list[Word]] = []
    current: list[Word] = []
    for w in words:
        if not current:
            current = [w]
            continue
        gap = w.start - current[-1].end
        punct = current[-1].word.rstrip().endswith((".", "!", "?", ";", ":"))
        if gap >= 0.45 or punct or len(current) >= max_words:
            groups.append(current)
            current = [w]
        else:
            current.append(w)
    if current:
        groups.append(current)
    phrases = []
    for g in groups:
        text = _join_words([w.word for w in g])
        score = sum(word_score(w.word) for w in g)
        phrases.append((text, g[0].start, g[-1].end, score))
    return phrases


def make_hook(
    transcript: Transcript,
    start: float,
    end: float,
    *,
    peak: float | None,
    peak_kind: str = "",
    has_speech: bool | None = None,
) -> tuple[str, str]:
    """Build a hook that describes this clip. Never invent a fake 'WAIT FOR IT'."""
    words = transcript.words_in(start, end) if hasattr(transcript, "words_in") else [
        w for w in (transcript.words or []) if w.end > start and w.start < end
    ]
    text = transcript.text_in(start, end) if hasattr(transcript, "text_in") else " ".join(w.word for w in words)
    has_speech = bool(words or (text or "").strip()) if has_speech is None else has_speech
    duration = max(0.01, end - start)
    in_last_30 = (
        peak is not None and peak + PAYOFF_SLACK >= start + PAYOFF_POSITION * duration
    )

    if not has_speech:
        # No key, no speech: neutral / no hook — never a fake promise.
        return "", "Clip"

    phrases = _phrases_from_words(words)
    # Prefer a punchy phrase. Tease from the first 50% if it's real content;
    # otherwise use the payoff line itself.
    mid = start + 0.5 * duration
    scored = []
    for phrase, p_start, p_end, score in phrases:
        cleaned = re.sub(r"\s+", " ", phrase).strip()
        if len(cleaned) < 2:
            continue
        if _is_generic_hook(cleaned) and not in_last_30:
            continue
        # Boost phrases near the start (setup tease) or near the peak.
        pos = 0.0
        if p_start <= mid:
            pos += 0.6
        if peak is not None and abs(p_start - peak) < 3:
            pos += 1.2
        scored.append((score + pos, cleaned, p_start))
    scored.sort(key=lambda r: -r[0])

    hook = ""
    if scored and scored[0][0] >= 0.8:
        hook = scored[0][1]
    elif phrases:
        # Fall back to the first non-generic sentence
        for phrase, _a, _b, _s in phrases:
            if not _is_generic_hook(phrase):
                hook = phrase
                break

    hook = re.sub(r"\s+", " ", hook).strip(" ,;:")
    if _is_generic_hook(hook):
        # Only keep a generic hook when the speaker actually said it AND
        # a verified payoff sits in the last 30% of this clip.
        said = _is_generic_hook(text) or any(_is_generic_hook(p[0]) for p in phrases)
        if not (said and in_last_30):
            hook = ""
            # Try the next specific phrase
            for _score, cleaned, _t in scored:
                if not _is_generic_hook(cleaned):
                    hook = cleaned
                    break

    if hook:
        words_h = hook.split()[:8]
        hook = " ".join(words_h).strip()
        hook = hook.upper()
        if len(hook) > 48:
            hook = " ".join(words_h[:6]).upper()
        title = " ".join(w.capitalize() if not w.isupper() else w for w in words_h)
        title = title.rstrip("!?.")
        return hook[:60], title[:80]

    return "", "Clip"


def _hook_from_text(text: str) -> tuple[str, str]:
    """Back-compat wrapper: specific hook from text, never a fake promise."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return "", "Clip"
    tr = Transcript(text=text, language="en", segments=[], words=[], duration=0)
    # Fake a single span so phrase splitting still works
    from clipper.transcribe import Word as W

    parts = text.split()
    words = [W(p, i * 0.3, i * 0.3 + 0.25) for i, p in enumerate(parts)]
    tr = Transcript(text=text, language="en", segments=[], words=words, duration=max(1.0, len(parts) * 0.3))
    return make_hook(tr, 0.0, tr.duration, peak=tr.duration * 0.85, has_speech=True)


def _reason(payoff: Payoff) -> str:
    kind = {
        "laugh": "laughter",
        "reaction": "a reaction",
        "punchline": "a punchline",
        "loud": "a loud spike",
        "scene-change": "a scene change",
        "action": "an action beat",
    }.get(payoff.kind, payoff.kind or "a peak")
    extra = f" ({payoff.label})" if payoff.label else ""
    return f"Payoff: {kind}{extra} at {payoff.time:.1f}s"


def _moment_from_payoff(
    payoff: Payoff,
    transcript: Transcript,
    duration: float,
    bounds: list[tuple[float, float]],
    min_dur: float,
    max_dur: float,
    source: str,
    cuts: list[float] | None = None,
    breaks: list[float] | None = None,
) -> Moment | None:
    window = window_around_payoff(
        payoff.time, duration, bounds, min_dur, max_dur, cuts=cuts, breaks=breaks
    )
    if not window:
        return None
    start, end = window
    hook, title = make_hook(transcript, start, end, peak=payoff.time, peak_kind=payoff.kind)
    return Moment(
        start=round(max(0.0, start), 3),
        end=round(min(duration, end), 3),
        score=float(payoff.score),
        reason=_reason(payoff),
        hook=hook,
        title=title,
        source=source,
        peak=round(payoff.time, 3),
        peak_kind=payoff.kind,
    )


def heuristic_moments(
    transcript: Transcript,
    duration: float,
    count: int,
    *,
    wav: Path | None = None,
    video: Path | None = None,
    min_dur: float = 15.0,
    max_dur: float = 60.0,
) -> list[Moment]:
    """Return at most `count` clips that each contain a real payoff. Never pads."""
    duration = float(duration or transcript.duration or 0.0)
    if duration <= 0 or count < 1:
        return []

    payoffs = detect_payoffs(transcript, duration, wav=wav, video=video)
    bounds = _sentence_bounds(transcript, duration)
    cuts = scene_cuts(video, duration)
    breaks = speech_breaks(transcript)
    picked: list[Moment] = []

    def overlaps(a: float, b: float) -> bool:
        return any(not (b <= m.start + 0.4 or a >= m.end - 0.4) for m in picked)

    for payoff in payoffs:
        if len(picked) >= count:
            break
        moment = _moment_from_payoff(
            payoff, transcript, duration, bounds, min_dur, max_dur, "heuristic",
            cuts=cuts, breaks=breaks,
        )
        if not moment:
            continue
        if overlaps(moment.start, moment.end):
            continue
        picked.append(moment)

    picked.sort(key=lambda m: m.start)
    return picked[:count]


def attach_payoff(
    moment: Moment,
    transcript: Transcript,
    duration: float,
    *,
    wav: Path | None = None,
    video: Path | None = None,
    min_dur: float = 15.0,
    max_dur: float = 60.0,
    reshape: bool = True,
) -> Moment | None:
    """Keep an LLM (or other) moment only if a real payoff is inside it.

    When possible the window is reshaped so it ends just after the payoff.
    Generic hooks are rewritten from the transcript.
    """
    payoffs = detect_payoffs(transcript, duration, wav=wav, video=video)
    inside = [p for p in payoffs if moment.start - 0.2 <= p.time <= moment.end + 0.2]
    if not inside:
        return None
    payoff = max(inside, key=lambda p: p.score)
    bounds = _sentence_bounds(transcript, duration)
    cuts = scene_cuts(video, duration)
    breaks = speech_breaks(transcript)
    if reshape:
        reshaped = _moment_from_payoff(
            payoff, transcript, duration, bounds, min_dur, max_dur, moment.source or "llm",
            cuts=cuts, breaks=breaks,
        )
        if reshaped:
            if moment.title and not reshaped.title:
                reshaped.title = moment.title
            if moment.description:
                reshaped.description = moment.description
            if moment.hashtags:
                reshaped.hashtags = list(moment.hashtags)
            # If the LLM hook is specific and honest, keep it.
            if moment.hook and not _is_generic_hook(moment.hook):
                reshaped.hook = moment.hook.strip()[:60]
            elif moment.hook and _is_generic_hook(moment.hook) and not reshaped.payoff_in_last_30():
                reshaped.hook = ""
            return reshaped
    hook, title = make_hook(
        transcript, moment.start, moment.end, peak=payoff.time, peak_kind=payoff.kind
    )
    if moment.hook and not _is_generic_hook(moment.hook):
        hook = moment.hook.strip()[:60]
    elif _is_generic_hook(moment.hook or hook) and not (
        payoff.time + PAYOFF_SLACK >= moment.start + PAYOFF_POSITION * max(0.01, moment.duration)
    ):
        hook = ""
    moment.peak = payoff.time
    moment.peak_kind = payoff.kind
    moment.score = max(moment.score, payoff.score)
    moment.hook = hook
    if not moment.title:
        moment.title = title
    if not moment.reason or moment.reason in {"LLM pick", "llm"}:
        moment.reason = _reason(payoff)
    return moment


def select_moments(
    transcript: Transcript,
    duration: float,
    count: int,
    *,
    wav: Path | None = None,
    video: Path | None = None,
    min_dur: float = 15.0,
    max_dur: float = 60.0,
    gemini_key: str | None = None,
    groq_key: str | None = None,
    source_title: str = "",
    progress=None,
) -> list[Moment]:
    log = progress or (lambda *_a, **_k: None)
    from clipper.llm import suggest_moments

    llm = suggest_moments(
        transcript,
        duration,
        count,
        min_dur=min_dur,
        max_dur=max_dur,
        gemini_key=gemini_key,
        groq_key=groq_key,
        source_title=source_title,
        progress=log,
    )
    if llm:
        kept: list[Moment] = []
        for raw in llm:
            got = attach_payoff(
                raw,
                transcript,
                duration,
                wav=wav,
                video=video,
                min_dur=min_dur,
                max_dur=max_dur,
            )
            if got:
                kept.append(got)
        if kept:
            log(f"Using {len(kept)} verified moment(s) from the free LLM")
            return kept[:count]
        log("LLM moments had no verifiable payoff — falling back to the local heuristic")

    log("No LLM key or the free LLM failed — using the local loudness/keyword heuristic")
    moments = heuristic_moments(
        transcript,
        duration,
        count,
        wav=wav,
        video=video,
        min_dur=min_dur,
        max_dur=max_dur,
    )
    if not moments:
        log("No clip-worthy peak (laugh, reaction, punchline, loud spike or scene change) was found")
    return moments
