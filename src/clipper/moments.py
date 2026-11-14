"""Pick the top N viral moments: free LLM first, local heuristic fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from clipper.audio_peaks import load_mono_f32, rms_series, zscore
from clipper.transcribe import Transcript, Word

# Words / phrases that often show up in clips people actually watch.
LAUGHTER = {
    "haha", "hahaha", "hahahaha", "ha", "lol", "lmao", "lmfao", "rofl",
    "laugh", "laughs", "laughing", "laughed", "giggle", "giggles",
    "chuckle", "hilarious", "funny", "joke",
}
SURPRISE = {
    "wait", "what", "wow", "whoa", "whoah", "omg", "oh", "no", "way",
    "insane", "crazy", "unbelievable", "shocked", "shocking", "holy",
    "bro", "dude", "whoa", "amazing", "unreal", "wild", "huge",
    "never", "can't", "cannot", "won't", "stop",
}
HOOKS = {
    "secret", "secrets", "actually", "nobody", "never", "always", "tip",
    "hack", "mistake", "mistakes", "first", "last", "finally", "truth",
    "reason", "because", "if", "when", "here's", "heres", "watch",
    "happened", "story", "remember", "important", "listen", "look",
    "warning", "careful", "don't", "dont", "stop", "wait", "before",
}
QUESTION_STARTS = {"why", "how", "what", "when", "where", "who", "is", "are", "do", "did", "can", "should"}


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

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

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
        }


def _norm_token(word: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", word.lower())


def word_score(token: str) -> float:
    t = _norm_token(token)
    if not t:
        return 0.0
    score = 0.0
    if t in LAUGHTER:
        score += 3.0
    if t in SURPRISE:
        score += 1.6
    if t in HOOKS:
        score += 1.3
    if t in QUESTION_STARTS:
        score += 0.6
    if token.isupper() and len(token) > 2:
        score += 0.8
    if token.endswith("!"):
        score += 0.7
    if token.endswith("?"):
        score += 0.9
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


def _energy_at(times: np.ndarray, energy: np.ndarray, t: float) -> float:
    if times.size == 0:
        return 0.0
    idx = int(np.clip(np.searchsorted(times, t), 0, len(energy) - 1))
    return float(energy[idx])


def heuristic_moments(
    transcript: Transcript,
    duration: float,
    count: int,
    *,
    wav: Path | None = None,
    min_dur: float = 15.0,
    max_dur: float = 60.0,
) -> list[Moment]:
    duration = float(duration or transcript.duration or 0.0)
    if duration <= 0:
        return []

    # Short videos: just return the whole thing (or as much as max_dur).
    if duration <= min_dur + 1:
        hook, title = _hook_from_text(transcript.text)
        return [
            Moment(
                start=0.0,
                end=duration,
                score=1.0,
                reason="Source is already short enough to post as one clip",
                hook=hook,
                title=title,
                source="heuristic",
            )
        ]

    times, energy = _energy_profile(wav, duration)
    words = transcript.words
    # Score each 0.5s bin: keywords + loudness.
    bin_hop = 0.5
    n_bins = int(np.ceil(duration / bin_hop))
    scores = np.zeros(n_bins, dtype=np.float64)
    reasons: list[list[str]] = [[] for _ in range(n_bins)]

    for w in words:
        s = word_score(w.word)
        if s <= 0:
            continue
        idx = int(np.clip(w.start / bin_hop, 0, n_bins - 1))
        scores[idx] += s
        tag = _norm_token(w.word)
        if tag and tag not in reasons[idx] and len(reasons[idx]) < 4:
            reasons[idx].append(tag)

    for i in range(n_bins):
        t = (i + 0.5) * bin_hop
        e = _energy_at(times, energy, t)
        if e > 1.0:
            scores[i] += min(e, 4.0)
            if e > 2.0 and "loud moment" not in reasons[i]:
                reasons[i].append("loud moment")

    # Slight boost at the very start (hooks often land in the first 20s).
    early = int(min(20.0, duration) / bin_hop)
    scores[:early] *= 1.08

    bounds = _sentence_bounds(transcript, duration)
    picked: list[Moment] = []

    def overlaps(a: float, b: float) -> bool:
        return any(not (b <= m.start + 0.4 or a >= m.end - 0.4) for m in picked)

    # Candidate peaks: local maxima, highest first.
    order = list(np.argsort(-scores))
    seen_peaks: set[int] = set()
    for idx in order:
        if scores[idx] <= 0.15:
            break
        # Skip if a nearby bin already used as a peak center
        if any(abs(idx - p) <= 4 for p in seen_peaks):
            continue
        seen_peaks.add(idx)
        peak_t = (idx + 0.5) * bin_hop
        start, end = _grow_window(peak_t, duration, bounds, min_dur, max_dur)
        if overlaps(start, end):
            continue
        hook, title = _hook_from_text(transcript.text_in(start, end) or transcript.text)
        why = reasons[idx] or ["energy peak"]
        picked.append(
            Moment(
                start=round(max(0.0, start), 3),
                end=round(min(duration, end), 3),
                score=float(scores[idx]),
                reason="Local heuristic: " + ", ".join(why[:4]),
                hook=hook,
                title=title,
                source="heuristic",
            )
        )
        if len(picked) >= count:
            break

    if not picked:
        # Evenly spaced fallback so we still produce clips.
        span = min(max_dur, max(min_dur, duration / max(count, 1)))
        t = 0.0
        while t < duration - 1 and len(picked) < count:
            end = min(duration, t + span)
            if end - t >= min(min_dur, duration):
                hook, title = _hook_from_text(transcript.text_in(t, end) or transcript.text)
                picked.append(
                    Moment(
                        start=round(t, 3),
                        end=round(end, 3),
                        score=0.1,
                        reason="Evenly spaced fallback (little speech/energy found)",
                        hook=hook,
                        title=title,
                        source="heuristic",
                    )
                )
            t += span

    # If a long first window left unused footage, pack extra clips into the gaps.
    if len(picked) < count:
        picked.sort(key=lambda m: m.start)
        cursor = 0.0
        gaps: list[tuple[float, float]] = []
        for m in picked:
            if m.start - cursor >= min_dur:
                gaps.append((cursor, m.start))
            cursor = max(cursor, m.end)
        if duration - cursor >= min_dur:
            gaps.append((cursor, duration))
        for a, b in gaps:
            if len(picked) >= count:
                break
            end = min(b, a + max_dur)
            if end - a >= min(min_dur, duration):
                hook, title = _hook_from_text(transcript.text_in(a, end) or transcript.text)
                picked.append(
                    Moment(
                        start=round(a, 3),
                        end=round(end, 3),
                        score=0.15,
                        reason="Filled leftover gap after the top-scoring window",
                        hook=hook,
                        title=title,
                        source="heuristic",
                    )
                )
    picked.sort(key=lambda m: m.start)
    return picked[:count]


def _grow_window(
    peak: float,
    duration: float,
    bounds: list[tuple[float, float]],
    min_dur: float,
    max_dur: float,
) -> tuple[float, float]:
    # Start around the peak, snap to sentence bounds, then expand to min_dur.
    start = max(0.0, peak - 4.0)
    end = min(duration, peak + 8.0)
    if bounds:
        containing = [b for b in bounds if b[0] <= peak <= b[1] + 0.15]
        if containing:
            start = containing[0][0]
            end = containing[0][1]
        # expand to neighbouring sentences until min_dur
        while end - start < min_dur:
            left = [b for b in bounds if b[1] <= start + 0.05]
            right = [b for b in bounds if b[0] >= end - 0.05]
            grew = False
            # Prefer expanding toward the side that keeps the peak more centered
            # but always stay inside max_dur.
            options: list[tuple[str, tuple[float, float]]] = []
            if left:
                options.append(("l", left[-1]))
            if right:
                options.append(("r", right[0]))
            if not options:
                break
            # Pick the closer neighbour
            options.sort(key=lambda it: abs((it[1][0] + it[1][1]) / 2 - peak))
            for side, (a, b) in options:
                new_start, new_end = start, end
                if side == "l":
                    new_start = a
                else:
                    new_end = b
                if new_end - new_start <= max_dur + 0.05:
                    start, end = new_start, new_end
                    grew = True
                    break
            if not grew:
                break

    if end - start < min_dur:
        missing = min_dur - (end - start)
        start = max(0.0, start - missing / 2)
        end = min(duration, start + min_dur)
        start = max(0.0, end - min_dur)
    if end - start > max_dur:
        # Keep the peak inside the window
        start = min(max(0.0, peak - max_dur / 3), duration - max_dur)
        end = start + max_dur
    start = max(0.0, start)
    end = min(duration, end)
    return start, end


def _hook_from_text(text: str) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return "WAIT FOR IT", "Wait for it"
    # Prefer the first punchy sentence, capped.
    parts = re.split(r"(?<=[.!?])\s+", text)
    sentence = parts[0] if parts else text
    words = sentence.split()
    hook_words = words[:8]
    hook = " ".join(hook_words).strip(" ,;:")
    hook = hook.upper()
    if len(hook) > 48:
        hook = " ".join(hook_words[:6]).upper()
    if not hook.endswith(("!", "?")) and len(hook.split()) <= 6:
        hook = hook.rstrip(".") + "!"
    title = " ".join(w.capitalize() if not w.isupper() else w for w in hook_words)
    title = title.rstrip("!?.") 
    if len(title) < 20 and len(parts) > 1:
        extra = parts[1].split()[:6]
        title = (title + " " + " ".join(extra)).strip()
    return hook[:60], title[:80]


def select_moments(
    transcript: Transcript,
    duration: float,
    count: int,
    *,
    wav: Path | None = None,
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
        log(f"Using {len(llm)} moment(s) from the free LLM")
        return llm[:count]

    log("No LLM key or the free LLM failed — using the local loudness/keyword heuristic")
    return heuristic_moments(
        transcript, duration, count, wav=wav, min_dur=min_dur, max_dur=max_dur
    )
