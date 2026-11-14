"""Optional free-tier LLM helpers (Gemini, then Groq). Fail soft."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from clipper.moments import Moment, _hook_from_text
from clipper.transcribe import Transcript

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash-lite",
]
GROQ_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "gemma2-9b-it",
    "moonshotai/kimi-k2-instruct",
]


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def load_keys(gemini_key: str | None = None, groq_key: str | None = None) -> tuple[str, str]:
    try:
        from dotenv import load_dotenv

        load_dotenv()
        # Also load a user-level config if present
        home_env = None
        if os.name == "nt":
            local = os.environ.get("LOCALAPPDATA")
            if local:
                home_env = os.path.join(local, "Clipper", ".env")
        else:
            home_env = os.path.expanduser("~/.config/clipper/.env")
        if home_env and os.path.isfile(home_env):
            load_dotenv(home_env, override=False)
    except Exception:
        pass
    gemini = (gemini_key or _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")).strip()
    groq = (groq_key or _env("GROQ_API_KEY")).strip()
    return gemini, groq


def _clip_transcript(transcript: Transcript, max_chars: int = 12000) -> str:
    lines = []
    if transcript.segments:
        for s in transcript.segments:
            lines.append(f"[{_ts(s.start)}–{_ts(s.end)}] {s.text.strip()}")
    elif transcript.words:
        buf, start = [], None
        for w in transcript.words:
            if start is None:
                start = w.start
            buf.append(w.word)
            if w.word.endswith((".", "!", "?")) or w.end - start > 8:
                lines.append(f"[{_ts(start)}–{_ts(w.end)}] {_join(buf)}")
                buf, start = [], None
        if buf and start is not None:
            lines.append(f"[{_ts(start)}–{_ts(transcript.words[-1].end)}] {_join(buf)}")
    else:
        lines.append(transcript.text)
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n…[truncated]"
    return text


def _join(parts: list[str]) -> str:
    return " ".join(p.strip() for p in parts if p.strip())


def _ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:05.2f}"


def _prompt(transcript_text: str, duration: float, count: int, min_dur: float, max_dur: float, source_title: str) -> str:
    title = source_title or "the source video"
    return f"""You are a short-form video editor picking the most viral moments from a long video so they can be posted as YouTube Shorts.

Source title: {title}
Video duration: {duration:.1f} seconds
Transcript with timestamps:
{transcript_text}

Pick the top {count} moments. Each clip MUST be between {min_dur:.0f} and {max_dur:.0f} seconds long, must stay inside 0 and {duration:.1f}, and must not overlap. Prefer moments with a hook in the first 3 seconds, a punchline or payoff, laughter, surprise, a strong opinion, a question, or a clear tip. Avoid intros, outros, and dead air.

Return ONLY valid JSON with this shape:
{{
  "moments": [
    {{
      "start": 12.5,
      "end": 38.0,
      "hook": "SHORT HOOK TEXT IN ALL CAPS",
      "reason": "why this moment works",
      "title": "YouTube Short title under 70 characters",
      "description": "2-3 sentence description that credits the original creator and asks viewers to watch the full video",
      "hashtags": ["shorts", "youtube", "example"]
    }}
  ]
}}
"""


def _parse_moments(payload: Any, duration: float, min_dur: float, max_dur: float, count: int, source: str) -> list[Moment]:
    if isinstance(payload, str):
        payload = _extract_json(payload)
    if not isinstance(payload, dict):
        return []
    items = payload.get("moments") or payload.get("clips") or payload.get("segments") or []
    if isinstance(payload, list):
        items = payload
    out: list[Moment] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start") if "start" in item else item.get("start_s", 0))
            end = float(item.get("end") if "end" in item else item.get("end_s", 0))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        start = max(0.0, start)
        end = min(duration, end)
        # Snap into the allowed duration window when close.
        if end - start < min_dur and duration >= min_dur:
            end = min(duration, start + min_dur)
            if end - start < min_dur:
                start = max(0.0, end - min_dur)
        if end - start > max_dur:
            end = start + max_dur
        if end - start < max(5.0, min(min_dur, duration)):
            continue
        hook = str(item.get("hook") or "").strip()
        title = str(item.get("title") or "").strip()
        if not hook or not title:
            auto_hook, auto_title = _hook_from_text(str(item.get("reason") or title or hook))
            hook = hook or auto_hook
            title = title or auto_title
        tags = item.get("hashtags") or []
        if isinstance(tags, str):
            tags = [t.lstrip("#") for t in tags.replace(",", " ").split() if t.strip()]
        tags = [str(t).lstrip("#") for t in tags if str(t).strip()]
        out.append(
            Moment(
                start=round(start, 3),
                end=round(end, 3),
                score=10.0 - len(out),
                reason=str(item.get("reason") or "LLM pick"),
                hook=hook[:60],
                title=title[:80],
                description=str(item.get("description") or "").strip(),
                hashtags=tags[:12],
                source=source,
            )
        )
        if len(out) >= count:
            break
    # Drop overlaps, keep earlier / higher score
    out.sort(key=lambda m: (-m.score, m.start))
    kept: list[Moment] = []
    for m in out:
        if any(not (m.end <= k.start + 0.4 or m.start >= k.end - 0.4) for k in kept):
            continue
        kept.append(m)
    kept.sort(key=lambda m: m.start)
    return kept


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return {}


def _gemini(prompt: str, key: str) -> str | None:
    last_err = None
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            with httpx.Client(timeout=45.0) as client:
                r = client.post(
                    url,
                    params={"key": key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0.3,
                            "responseMimeType": "application/json",
                        },
                    },
                )
            if r.status_code >= 400:
                last_err = f"{model}: HTTP {r.status_code}"
                continue
            data = r.json()
            parts = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [])
            )
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                return text
        except Exception as exc:  # noqa: BLE001 — soft fail
            last_err = f"{model}: {exc}"
            continue
    if last_err:
        return None
    return None


def _groq(prompt: str, key: str) -> str | None:
    for model in GROQ_MODELS:
        try:
            with httpx.Client(timeout=45.0) as client:
                r = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": "Return only valid JSON."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
            if r.status_code >= 400:
                continue
            text = r.json().get("choices", [{}])[0].get("message", {}).get("content") or ""
            if text.strip():
                return text
        except Exception:  # noqa: BLE001 — soft fail
            continue
    return None


def suggest_moments(
    transcript: Transcript,
    duration: float,
    count: int,
    *,
    min_dur: float = 15.0,
    max_dur: float = 60.0,
    gemini_key: str | None = None,
    groq_key: str | None = None,
    source_title: str = "",
    progress=None,
) -> list[Moment]:
    log = progress or (lambda *_a, **_k: None)
    gemini, groq = load_keys(gemini_key, groq_key)
    if not gemini and not groq:
        return []
    if not (transcript.text or transcript.words or transcript.segments):
        return []

    prompt = _prompt(_clip_transcript(transcript), duration, count, min_dur, max_dur, source_title)
    text = None
    source = "llm"
    if gemini:
        log("Asking Gemini (free tier) to pick viral moments…")
        text = _gemini(prompt, gemini)
        source = "gemini"
    if not text and groq:
        log("Asking Groq (free key) to pick viral moments…")
        text = _groq(prompt, groq)
        source = "groq"
    if not text:
        log("Free LLM did not return usable moments")
        return []
    moments = _parse_moments(text, duration, min_dur, max_dur, count, source)
    return moments
