"""Write a recap-channel style script from a title, transcript and optional plot."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from clipper.transcribe import Transcript

SHORT_WORDS = (115, 155)
# Default "long" is a YouTube recap; demos can target 2–3 minutes via target_seconds.
LONG_WORDS = (1300, 2000)
WPM = 150

# Supplementary plot cards for well-known public-domain / CC open movies.
# Used only as fallback context when the user didn't pass a plot file.
PLOT_CARDS = {
    "sintel": (
        "Sintel, a lone young woman, finds a wounded baby dragon she names Scales and "
        "raises it. The dragon is stolen. She hunts through a harsh world, fights a "
        "shaman, and finally faces an adult dragon. The twist: the adult dragon is "
        "Scales' mother, and Sintel's fight has tragic consequences. She leaves with "
        "a new young dragon."
    ),
    "night of the living dead": (
        "In 1968, Barbara flees a cemetery attack and hides in a farmhouse with Ben "
        "and other survivors as the dead walk. Tension inside the house is as deadly "
        "as the ghouls outside. By dawn, almost no one is left, and a final tragic "
        "mistake ends the last survivor."
    ),
    "tears of steel": (
        "In a ruined Rotterdam, a group of soldiers and scientists fight robot "
        "invaders while one man, Thom, is consumed by a memory of a woman he loved. "
        "The battle and the memory collide."
    ),
    "big buck bunny": (
        "A big, gentle bunny is harassed by a flying squirrel and two sidekicks. "
        "He turns the tables in a cartoon showdown."
    ),
    "caminandes": (
        "A clueless llama's simple goal (crossing a fence, avoiding a penguin) "
        "turns into a slapstick disaster."
    ),
}


@dataclass
class RecapLine:
    text: str
    beat: str = "setup"  # hook | setup | conflict | twist | cta
    keywords: list[str] = field(default_factory=list)


@dataclass
class RecapScript:
    title: str
    hook: str
    format: str  # short | long
    spoilers: bool
    lines: list[RecapLine] = field(default_factory=list)
    youtube_title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)
    source_used: str = "heuristic"

    @property
    def full_text(self) -> str:
        return " ".join(ln.text.strip() for ln in self.lines if ln.text.strip())

    @property
    def word_count(self) -> int:
        return len(re.findall(r"[A-Za-z0-9']+", self.full_text))

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def target_word_count(fmt: str, target_seconds: float | None = None) -> tuple[int, int]:
    if target_seconds and target_seconds > 0:
        mid = int(target_seconds * WPM / 60)
        return max(80, int(mid * 0.88)), max(100, int(mid * 1.12))
    return SHORT_WORDS if fmt == "short" else LONG_WORDS


def target_seconds_for(fmt: str, target_seconds: float | None = None) -> float:
    if target_seconds and target_seconds > 0:
        return float(target_seconds)
    return 52.0 if fmt == "short" else 11 * 60.0


def plot_card_for(title: str) -> str:
    key = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    for name, card in PLOT_CARDS.items():
        if name in key or key in name:
            return card
    return ""


def load_plot_source(path: Path | str | None, text: str | None = None) -> str:
    bits = []
    if text and text.strip():
        bits.append(text.strip())
    if path:
        p = Path(path)
        if p.is_file():
            bits.append(p.read_text(encoding="utf-8", errors="replace")[:20000])
    return "\n\n".join(bits).strip()


def write_script(
    title: str,
    transcript: Transcript | None,
    *,
    fmt: str = "short",
    spoilers: bool = True,
    plot: str = "",
    target_seconds: float | None = None,
    gemini_key: str | None = None,
    groq_key: str | None = None,
    llm: bool = True,
    progress=None,
) -> RecapScript:
    log = progress or (lambda *_a, **_k: None)
    fmt = "short" if fmt == "short" else "long"
    lo, hi = target_word_count(fmt, target_seconds)
    plot = (plot or "").strip() or plot_card_for(title)
    tr_text = ""
    if transcript is not None:
        from clipper.llm import _clip_transcript

        tr_text = _clip_transcript(transcript, max_chars=14000 if fmt == "long" else 8000)

    log(f"Writing a {fmt} recap script for {title!r} ({lo}–{hi} words, spoilers={spoilers})…")
    script = None
    if llm:
        try:
            script = _llm_script(
                title, tr_text, plot, fmt, spoilers, lo, hi, gemini_key, groq_key
            )
        except Exception as exc:  # noqa: BLE001
            log(f"LLM script failed ({exc}); using the local fallback")
            script = None
    if script is None or not script.lines:
        log("Using the local fallback script writer")
        script = _heuristic_script(title, transcript, plot, fmt, spoilers, lo, hi)
        script.source_used = "heuristic"
    else:
        script.source_used = "llm"
    if not script.hook:
        script.hook = script.lines[0].text if script.lines else title
    if not script.youtube_title:
        script.youtube_title = _default_yt_title(title, script.hook, fmt)
    if not script.description:
        script.description = _default_description(title, script, spoilers)
    if not script.tags:
        script.tags = _default_tags(title)
    if fmt == "long" and not script.chapters:
        script.chapters = _chapters_from_lines(script.lines)
    return script


def _llm_script(title, tr_text, plot, fmt, spoilers, lo, hi, gemini_key, groq_key) -> RecapScript | None:
    from clipper.llm import complete_json

    spoiler_rule = (
        "Include the ending and the key twist — this is a full recap with spoilers."
        if spoilers
        else "NO SPOILERS. Tease the twist but do not reveal the ending or the identity of any secret. Stop before the finale."
    )
    length = "45–60 second YouTube Short" if fmt == "short" else "long YouTube recap"
    prompt = f"""You write viral YouTube movie-recap voiceovers (channels that retell a film in a gripping narrator style).

Movie title: {title}

Write a {length} recap script of {lo}–{hi} words.
Style:
- Open with a strong hook in the first sentence (curiosity gap, "This man…", "This girl…", "Nobody expected…").
- Tell the story in present tense, short punchy sentences, suspense, then a twist beat, then a CTA (like, subscribe, watch the full film).
- {spoiler_rule}
- Stay true to the source. Do not invent characters, plot points, or a payoff the film does not have.
- No copyrighted song lyrics. No claim that this is the official film.

Plot notes (may be empty):
{plot or "(none)"}

Timed transcript / dialogue from the video (may be incomplete, especially for mostly-silent films):
{tr_text or "(no transcript)"}

Return JSON only:
{{
  "hook": "short on-screen hook, max 10 words",
  "youtube_title": "catchy title under 80 chars, no false promise",
  "description": "YouTube description, 2–4 short paragraphs, must include a sentence that this is a commentary/review recap and must credit the original film",
  "tags": ["tag1", "tag2"],
  "lines": [
    {{"text": "spoken sentence.", "beat": "hook|setup|conflict|twist|cta", "keywords": ["visual", "cues"]}}
  ],
  "chapters": [{{"title": "The hunt begins", "beat": "conflict"}}]
}}
Each line.keywords should be 1–4 concrete visual nouns from that beat (so we can find a matching shot).
"""
    data = complete_json(prompt, gemini_key=gemini_key, groq_key=groq_key)
    if not data:
        return None
    return _parse_script(data, title, fmt, spoilers)


def _parse_script(data: dict, title: str, fmt: str, spoilers: bool) -> RecapScript | None:
    raw_lines = data.get("lines") or data.get("script") or []
    lines: list[RecapLine] = []
    if isinstance(raw_lines, str):
        raw_lines = [{"text": s} for s in _split_sentences(raw_lines)]
    for item in raw_lines:
        if isinstance(item, str):
            text, beat, keys = item, "setup", []
        elif isinstance(item, dict):
            text = (item.get("text") or item.get("line") or item.get("narration") or "").strip()
            beat = (item.get("beat") or item.get("role") or "setup").lower().strip()
            keys = item.get("keywords") or item.get("visuals") or []
            if isinstance(keys, str):
                keys = [k.strip() for k in re.split(r"[,/]+", keys) if k.strip()]
        else:
            continue
        if not text:
            continue
        if beat not in {"hook", "setup", "conflict", "twist", "cta"}:
            beat = "setup"
        # Split run-on lines so we can cut every 2–4s.
        for sent in _split_sentences(text) or [text]:
            lines.append(RecapLine(text=sent.strip(), beat=beat, keywords=[str(k) for k in keys][:4]))
    if not lines:
        return None
    hook = (data.get("hook") or lines[0].text).strip()
    tags = data.get("tags") or []
    tags = [str(t).lstrip("#") for t in tags if str(t).strip()]
    chapters = data.get("chapters") or []
    clean_ch = []
    for ch in chapters:
        if isinstance(ch, dict) and (ch.get("title") or ch.get("name")):
            clean_ch.append({"title": str(ch.get("title") or ch.get("name")), "beat": ch.get("beat") or ""})
    return RecapScript(
        title=title,
        hook=hook[:80],
        format=fmt,
        spoilers=spoilers,
        lines=lines,
        youtube_title=str(data.get("youtube_title") or data.get("title") or "")[:80],
        description=str(data.get("description") or ""),
        tags=tags,
        chapters=clean_ch,
    )


def _heuristic_script(
    title: str,
    transcript: Transcript | None,
    plot: str,
    fmt: str,
    spoilers: bool,
    lo: int,
    hi: int,
) -> RecapScript:
    who = "This film"
    tlow = title.lower()
    if "sintel" in tlow:
        who = "This girl"
    elif any(w in tlow for w in ("man", "dead", "bunny", "steel")):
        who = "This man" if "bunny" not in tlow else "This bunny"

    hook = f"{who} would risk everything for what they found."
    if plot:
        # First clause of the plot card as a more specific hook.
        first = re.split(r"(?<=[.!?])\s+", plot.strip())[0]
        if 6 <= len(first.split()) <= 22:
            hook = first.rstrip(".") + "."

    sentences = _split_sentences(plot) if plot else []
    if sentences and not spoilers:
        spoiler_re = re.compile(
            r"\b(dies?|died|dead|kills?|killed|ending|mother|twist|finale|spoiler)\b",
            re.I,
        )
        sentences = [s for s in sentences if not spoiler_re.search(s)]
    if transcript and transcript.words:
        # Pull a few distinctive spoken lines as colour, not as the spine.
        spoken = []
        buf = []
        for w in transcript.words:
            buf.append(w.word)
            if w.word.endswith((".", "!", "?")) and len(buf) >= 4:
                sent = " ".join(buf).strip()
                if 4 <= len(sent.split()) <= 16:
                    spoken.append(sent)
                buf = []
        # Keep a handful of mid-film lines.
        if spoken:
            pick = spoken[1:: max(1, len(spoken) // 6)][:6]
            sentences.extend(pick)
    if not sentences:
        sentences = [
            f"{title} begins with a world that already feels dangerous.",
            "Someone is looking for something they cannot afford to lose.",
            "Every step forward costs more than the last.",
            "And just when it seems the search is over, the story turns."
            if spoilers
            else "The ending is waiting, and it is not what you think.",
        ]

    # Build a recap-shaped spine around whatever we have.
    hook_line = hook
    setup = sentences[: max(2, len(sentences) // 3)]
    mid = sentences[len(setup) : max(len(setup) + 2, (len(sentences) * 2) // 3)]
    rest = sentences[len(setup) + len(mid) :]
    if not spoilers:
        rest = [s for s in rest if not re.search(r"\b(dies?|dead|kills?|ending|mother|twist)\b", s, re.I)]
        rest.append("What happens at the end is better seen than spoiled.")
    cta = f"If you want the full story, watch {title} — and if this recap helped you, like and subscribe."

    lines = [RecapLine(hook_line, "hook", _keywords(hook_line))]
    for s in setup:
        lines.append(RecapLine(s, "setup", _keywords(s)))
    for s in mid:
        lines.append(RecapLine(s, "conflict", _keywords(s)))
    for s in rest:
        beat = "twist" if any(w in s.lower() for w in ("but", "twist", "mother", "actually", "finally")) else "conflict"
        lines.append(RecapLine(s, beat, _keywords(s)))
    lines.append(RecapLine(cta, "cta", [title.split()[0]] if title else []))

    # Stretch or trim toward the word window.
    text = " ".join(ln.text for ln in lines)
    words = len(re.findall(r"[A-Za-z0-9']+", text))
    if words < lo and plot:
        extra = _split_sentences(plot)
        if not spoilers:
            extra = [s for s in extra if not re.search(
                r"\b(dies?|died|dead|kills?|killed|ending|mother|twist|finale|spoiler)\b", s, re.I
            )]
        for s in extra:
            if any(s == ln.text for ln in lines):
                continue
            lines.insert(-1, RecapLine(s, "conflict", _keywords(s)))
            words += len(s.split())
            if words >= lo:
                break
    if words < lo:
        lines = _stretch_lines(lines, lo, who, title)
    return RecapScript(title=title, hook=_short_hook(hook_line), format=fmt, spoilers=spoilers, lines=lines)



def _stretch_lines(lines: list[RecapLine], lo: int, who: str, title: str) -> list[RecapLine]:
    """Pad a short fallback script toward the target length with original commentary, not repeated plot dumps."""
    bridges = [
        f"And still, {who.lower()} keeps moving.",
        "The world does not get kinder from here.",
        "Every choice feels like it might be the last one.",
        "Hope is a dangerous thing to carry this far.",
        "You can feel the story tightening, one cut at a time.",
        "Nothing about this road is accidental.",
        "The quiet is worse than the fights.",
        "What looked like a rescue is starting to look like a test.",
        "There is no map for what comes next.",
        "People in this world do not give second chances.",
        "The search is no longer just a search.",
        f"If you blink, you miss why {title} still hits so hard.",
        "That is the moment the recap has been walking you toward.",
        "Hold that image. It matters more than it first appears.",
        "The next beat is where the story stops being simple.",
    ]
    cta = lines[-1] if lines and lines[-1].beat == "cta" else None
    body = list(lines[:-1] if cta else lines)
    words = sum(len(re.findall(r"[A-Za-z0-9']+", ln.text)) for ln in lines)
    i = 0
    existing = {ln.text for ln in body}
    # Re-voice existing beats with short commentary after each one.
    while words < lo and body:
        src = body[i % len(body)]
        bridge = bridges[i % len(bridges)]
        if i >= len(bridges):
            bridge = f"{bridge} {src.text.rstrip('.')}, and the cost keeps rising."
        if bridge not in existing:
            beat = src.beat if src.beat != "hook" else "setup"
            body.append(RecapLine(bridge, beat, _keywords(bridge) or src.keywords))
            existing.add(bridge)
            words += len(bridge.split())
        i += 1
        if i > 400:
            break
    if cta:
        body.append(cta)
    return body


def _short_hook(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9']+|[!?]", text)
    # Keep up to ~9 words for the on-screen bar.
    body = [w for w in re.findall(r"[A-Za-z0-9']+|[.,!?]", text)]
    out, n = [], 0
    for tok in text.split():
        out.append(tok)
        n += 1
        if n >= 9:
            break
    hook = " ".join(out).strip(" ,;")
    if not hook.endswith(("?", "!", "…", ".")):
        hook = hook.rstrip(".") + "?" if hook.lower().startswith(("is", "what", "why", "who")) else hook
    return hook[:80]


def _keywords(text: str) -> list[str]:
    stop = {
        "the", "a", "an", "and", "or", "but", "if", "in", "on", "at", "to", "for", "of",
        "with", "this", "that", "she", "he", "they", "her", "his", "their", "is", "was",
        "are", "be", "as", "from", "it", "its", "into", "then", "than", "not", "no",
    }
    words = re.findall(r"[A-Za-z][A-Za-z0-9']{2,}", text or "")
    out = []
    for w in words:
        lw = w.lower()
        if lw not in stop and lw not in {x.lower() for x in out}:
            out.append(w)
        if len(out) >= 4:
            break
    return out


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Further split very long sentences at commas / dashes.
        if len(p.split()) > 28:
            bits = re.split(r"(?<=,)\s+|\s+[—–-]\s+", p)
            out.extend(b.strip(" ,") for b in bits if b.strip(" ,"))
        else:
            out.append(p)
    return out


def _default_yt_title(title: str, hook: str, fmt: str) -> str:
    suffix = " (Short Recap)" if fmt == "short" else " — Full Recap"
    base = hook.rstrip(".?") 
    if len(base) < 50:
        return (base + f" | {title}" + suffix)[:80]
    return (f"{title} Recap" + suffix)[:80]


def _default_description(title: str, script: RecapScript, spoilers: bool) -> str:
    warn = "Spoiler warning: this recap covers the ending." if spoilers else "Spoiler-free: the ending is not revealed."
    return (
        f"{script.hook}\n\n"
        f"A commentary/review recap of {title}. This is an independent recap and is not "
        f"the official film. Please support and credit the original creators.\n\n"
        f"{warn}\n\n"
        f"If you liked this, watch the original and consider leaving a like."
    )


def _default_tags(title: str) -> list[str]:
    slug = re.sub(r"[^a-z0-9]+", "", title.lower())
    tags = ["recap", "movierecap", "filmrecap", "commentary", "review", "explained", "storyexplained"]
    if slug:
        tags.insert(0, slug)
        tags.insert(1, f"{slug}recap")
    return tags[:12]


def _chapters_from_lines(lines: list[RecapLine]) -> list[dict]:
    chapters, seen = [], set()
    labels = {
        "hook": "The hook",
        "setup": "How it starts",
        "conflict": "The search",
        "twist": "The turn",
        "cta": "The end",
    }
    for ln in lines:
        if ln.beat in seen:
            continue
        seen.add(ln.beat)
        chapters.append({"title": labels.get(ln.beat, ln.beat.title()), "beat": ln.beat})
    return chapters
