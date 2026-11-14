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
    "theres", "there's", "makes", "telling", "doesnt", "doesn't", "made",
    "come", "came", "thing", "things", "something", "everything", "nothing",
    "people", "stuff", "want", "need", "them", "then", "when", "just",
    "well", "back", "even", "still", "because", "gonna", "wanna", "yeah",
}

DEFAULT_TAGS = ["shorts", "youtubeshorts"]
BLOCK_TAGS = {
    "fyp", "foryou", "foryoupage", "viral", "xyzbca", "tiktok",
    "dontcheckthesound", "waitforit", "clip", "video", "youtube",
}


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
    music_credit: str = "",
    geo: list[str] | None = None,
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
        moment.description = build_description(
            moment,
            transcript,
            source_title=source_title,
            source_url=source_url,
            uploader=uploader,
            music_credit=music_credit,
            geo=geo,
        )
    elif music_credit and music_credit not in (moment.description or ""):
        moment.description = (moment.description or "").rstrip() + "\n\n" + music_credit

    moment.hashtags = clean_hashtags(moment.hashtags, clip_text + " " + (source_title or ""))
    return moment


SOUND_WORDS = {
    "sound", "sounds", "audio", "listen", "hear", "heard", "volume",
    "loud", "silence", "mute", "bass", "beat", "song", "music",
}


def is_sound_payoff(peak_kind: str = "", hook: str = "", text: str = "") -> bool:
    """Only treat a clip as a sound gag when the payoff is really on the soundtrack."""
    if (peak_kind or "").lower() != "loud":
        return False
    blob = f"{hook} {text}".lower()
    tokens = set(re.findall(r"[a-z']+", blob))
    return bool(tokens & SOUND_WORDS)


def build_description(
    moment: Moment,
    transcript: Transcript,
    *,
    source_title: str = "",
    source_url: str = "",
    uploader: str = "",
    music_credit: str = "",
    geo: list[str] | None = None,
) -> str:
    hook = (moment.title or moment.hook or "").strip().rstrip(".")
    if hook.isupper() and len(hook) > 3:
        hook = hook.title()
    reason = re.sub(r"^Payoff:\s*", "", moment.reason or "").strip()
    if hook and reason:
        punct = "" if hook.endswith(("?", "!")) else "."
        body = f"{hook}{punct} {reason[0].upper() + reason[1:] if reason else reason}".strip()
        if not body.endswith((".", "!", "?")):
            body += "."
    elif hook:
        body = hook if hook.endswith(("?", "!")) else hook + "."
    elif source_title:
        body = f"A {moment.duration:.0f}-second moment from {source_title}."
    else:
        body = "A short moment from the original video."
    # Keep it to two sentences, never a raw transcript dump.
    sentences = re.split(r"(?<=[.!?])\s+", body)
    body = " ".join(sentences[:2]).strip()

    credits = []
    if uploader and source_title:
        credits.append(f"Clipped from: {uploader} — {source_title}.")
    elif uploader:
        credits.append(f"Original by {uploader}.")
    elif source_title:
        credits.append(f"Clipped from: {source_title}.")
    if source_url and source_url.startswith("http"):
        credits.append(f"Full video: {source_url}")
    if music_credit:
        credits.append(music_credit)
    if geo:
        credits.append("Campaign regions: " + ", ".join(geo) + ".")
    credits.append("Posted as a YouTube Short. Please credit the original creator.")
    return "\n\n".join([body] + [c for c in credits if c]).strip()


def clean_hashtags(existing: list[str] | None, text: str = "") -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        key = re.sub(r"[^a-z0-9]", "", (raw or "").lower().lstrip("#"))
        if not key or key in seen or key in STOP or key in BLOCK_TAGS or key.isdigit() or len(key) < 3:
            return
        seen.add(key)
        tags.append(key)

    for t in DEFAULT_TAGS:
        add(t)
    for t in existing or []:
        add(t)
    # At most 3 content tags, and only reasonably long words.
    for word in keywords(text, limit=8):
        if len(word) >= 5:
            add(word)
        if len(tags) >= 5:
            break
    return tags[:5]


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
