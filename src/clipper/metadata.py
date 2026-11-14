"""Suggested title, description and hashtags for each clip."""

from __future__ import annotations

import re
from collections import Counter

from clipper.moments import Moment, make_hook
from clipper.transcribe import Transcript

STOP = {
    "the", "a", "an", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "as", "is", "it", "its", "this", "that",
    "these", "those", "i", "you", "he", "she", "we", "they", "me", "my", "your",
    "our", "their", "be", "am", "are", "was", "were", "been", "being", "have",
    "has", "had", "do", "does", "did", "not", "no", "so", "than", "then", "too",
    "very", "just", "about", "into", "over", "after", "before", "out", "also",
    "can", "will", "would", "should", "could", "there", "here", "what", "when",
    "where", "which", "who", "how", "why", "all", "each", "few", "more", "most",
    "other", "some", "such", "only", "own", "same", "than", "too", "and", "im",
    "it's", "dont", "don't", "that's", "gonna", "yeah", "yes", "ok", "okay",
    "uh", "um", "like", "really", "going", "get", "got", "know", "think",
}

DEFAULT_TAGS = ["shorts", "youtubeshorts", "fyp", "clip"]


def keywords(text: str, limit: int = 6) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9']{3,}", text or "")
    cleaned = [_norm(t) for t in tokens]
    cleaned = [t for t in cleaned if t not in STOP and not t.isdigit()]
    counts = Counter(cleaned)
    return [w for w, _n in counts.most_common(limit)]


def _norm(token: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", token.lower())


def fill_metadata(
    moment: Moment,
    transcript: Transcript,
    *,
    source_title: str = "",
    source_url: str = "",
    uploader: str = "",
) -> Moment:
    clip_text = transcript.text_in(moment.start, moment.end) or transcript.text
    auto_hook, auto_title = make_hook(
        transcript,
        moment.start,
        moment.end,
        peak=moment.peak,
        peak_kind=moment.peak_kind,
    )
    # Honour an intentionally empty hook (no speech / no verified promise).
    if moment.hook is None:
        moment.hook = auto_hook
    if not moment.title or moment.title.lower() in {"clip", "wait for it"}:
        moment.title = auto_title if auto_title and auto_title.lower() != "clip" else (moment.hook.title() if moment.hook else (source_title or "Clip"))
    # Keep titles Shorts-friendly and punchy
    title = moment.title.strip()
    if source_title and source_title.lower() not in title.lower() and len(title) < 45:
        # Don't force the long-video title in; just keep the hook title
        pass
    if not title.lower().endswith("#shorts") and len(title) < 70:
        title = title.rstrip(".") 
    moment.title = title[:80]

    if not moment.description:
        snippet = re.sub(r"\s+", " ", clip_text).strip()
        if len(snippet) > 240:
            snippet = snippet[:237].rsplit(" ", 1)[0] + "…"
        credit_bits = []
        if uploader:
            credit_bits.append(f"Original by {uploader}.")
        elif source_title:
            credit_bits.append(f"Clipped from: {source_title}.")
        if source_url and source_url.startswith("http"):
            credit_bits.append(f"Full video: {source_url}")
        credit = " ".join(credit_bits)
        if snippet:
            body = snippet
        elif source_title:
            body = f"A {moment.duration:.0f}-second moment from {source_title}."
        else:
            body = "A short moment from the original video."
        moment.description = "\n\n".join(
            p for p in [body, credit, "Posted as a YouTube Short. Please credit the original creator."] if p
        ).strip()

    tags = list(moment.hashtags)
    lower = {t.lower().lstrip("#") for t in tags}
    for t in DEFAULT_TAGS + keywords(clip_text + " " + source_title):
        key = t.lower().lstrip("#")
        if key and key not in lower:
            tags.append(key)
            lower.add(key)
    moment.hashtags = tags[:12]
    return moment


def render_sidecar(moment: Moment, index: int, *, preset: str = "", layout: str = "") -> str:
    tags = " ".join(f"#{t.lstrip('#')}" for t in moment.hashtags)
    options = ""
    titles = list(getattr(moment, "title_options", None) or [])
    if titles:
        listed = "\n".join(f"- {t}" for t in titles)
        options = f"Title options:\n{listed}\n\n"
    extra = ""
    if preset or layout:
        extra = f"Preset: {preset or '-'}  Layout: {layout or '-'}\n"
    return (
        f"Title:\n{moment.title}\n\n"
        f"{options}"
        f"Description:\n{moment.description}\n\n"
        f"Hashtags:\n{tags}\n\n"
        f"Hook:\n{moment.hook}\n\n"
        f"Timestamp: {moment.start:.2f}s – {moment.end:.2f}s ({moment.duration:.1f}s)\n"
        f"Peak: {'' if moment.peak is None else f'{moment.peak:.2f}s'} {moment.peak_kind}\n"
        f"Why this moment: {moment.reason}\n"
        f"Picked by: {moment.source}\n"
        f"{extra}"
        f"Clip index: {index}\n"
    )
