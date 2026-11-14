"""Free TTS for recap narration: Gemini TTS first, then edge-tts neural voices."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import struct
import wave
from dataclasses import dataclass, field
from pathlib import Path

from clipper.transcribe import Transcript, Word

# Expressive narrator voices. Gemini names first; edge-tts names after the dash.
GEMINI_VOICES = [
    "Fenrir",  # deep
    "Charon",
    "Kore",
    "Puck",
    "Orus",
    "Aoede",
    "Leda",
    "Zephyr",
]
EDGE_VOICES = [
    "en-US-AndrewNeural",
    "en-US-AriaNeural",
    "en-US-BrianNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural",
    "en-GB-RyanNeural",
    "en-GB-SoniaNeural",
    "en-US-AvaNeural",
    "en-US-EmmaNeural",
]
DEFAULT_VOICE = "en-US-AndrewNeural"
GEMINI_TTS_MODELS = [
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
    "gemini-2.0-flash-preview-tts",
]


@dataclass
class TTSResult:
    path: Path
    voice: str
    backend: str  # gemini | edge-tts
    words: list[Word] = field(default_factory=list)
    duration: float = 0.0
    text: str = ""


def list_voices() -> list[dict[str, str]]:
    out = [{"id": v, "backend": "gemini", "label": f"{v} (Gemini TTS)"} for v in GEMINI_VOICES]
    out += [{"id": v, "backend": "edge-tts", "label": v} for v in EDGE_VOICES]
    return out


def resolve_voice(name: str | None) -> str:
    if not name or name.strip().lower() in {"auto", "default", ""}:
        return DEFAULT_VOICE
    raw = name.strip()
    # Accept "andrew", "Fenrir", "en-US-AndrewNeural"
    key = raw.lower().replace("_", "-")
    for v in EDGE_VOICES + GEMINI_VOICES:
        if v.lower() == key or v.lower().split("-")[-1].replace("neural", "") == key.replace("neural", ""):
            return v
        if key in v.lower():
            return v
    return raw


def synthesize(
    text: str,
    dest: Path,
    *,
    voice: str | None = None,
    gemini_key: str | None = None,
    progress=None,
) -> TTSResult:
    """Narrate `text` to a WAV file. One voice, with word timings when possible."""
    log = progress or (lambda *_a, **_k: None)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    voice = resolve_voice(voice)
    text = _prep_text(text)
    if not text.strip():
        raise ValueError("Nothing to narrate")

    # Gemini TTS first when the requested voice is a Gemini name, or for auto
    # when a free key is present. Any billing / 4xx / empty audio falls back.
    want_gemini = voice in GEMINI_VOICES
    key = _gemini_key(gemini_key)
    if key and (want_gemini or voice == DEFAULT_VOICE):
        g_voice = voice if voice in GEMINI_VOICES else "Fenrir"
        log(f"Trying Gemini TTS ({g_voice})…")
        try:
            result = _gemini_tts(text, dest, g_voice, key)
            if result and result.duration > 0.3:
                log(f"Gemini TTS: {result.duration:.1f}s, voice {g_voice}")
                return result
        except Exception as exc:  # noqa: BLE001 — free-tier soft fail
            log(f"Gemini TTS unavailable ({_safe_err(exc)}); falling back to edge-tts")

    edge_voice = voice if voice in EDGE_VOICES else DEFAULT_VOICE
    log(f"Synthesizing with edge-tts ({edge_voice})…")
    result = _edge_tts(text, dest, edge_voice)
    log(f"edge-tts: {result.duration:.1f}s, voice {edge_voice}")
    return result


def _gemini_key(explicit: str | None) -> str:
    from clipper.llm import load_keys

    gemini, _groq = load_keys(explicit, None)
    return gemini


def _safe_err(exc: Exception) -> str:
    msg = str(exc)
    msg = re.sub(r"key=[^&\s]+", "key=…", msg)
    return msg[:160]


def _prep_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    # Light pause between sentences so the recap breathes.
    text = re.sub(r"([.!?])\s+", r"\1 ", text)
    return text


def _gemini_tts(text: str, dest: Path, voice: str, key: str) -> TTSResult | None:
    import httpx

    # Style prefix: ask for a dramatic narrator without putting it in the audio
    # if the model would read it aloud — we use the speechConfig + a short cue.
    spoken = (
        "Read this movie recap in a gripping, dramatic narrator voice, "
        "with urgency and warmth, not a flat monotone:\n\n" + text
    )
    last = None
    for model in GEMINI_TTS_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(
                    url,
                    params={"key": key},
                    json={
                        "contents": [{"parts": [{"text": spoken}]}],
                        "generationConfig": {
                            "temperature": 0.8,
                            "responseModalities": ["AUDIO"],
                            "speechConfig": {
                                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
                            },
                        },
                    },
                )
            if r.status_code >= 400:
                # Never retry a billing / payment error against a paid path.
                body = r.text.lower()
                if any(s in body for s in ("billing", "payment", "must enable", "paid")):
                    raise RuntimeError("Gemini TTS is not on the free tier for this key")
                last = f"HTTP {r.status_code}"
                continue
            data = r.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            audio_b64 = ""
            mime = "audio/l16;rate=24000"
            for p in parts:
                inline = p.get("inlineData") or p.get("inline_data") or {}
                if inline.get("data"):
                    audio_b64 = inline["data"]
                    mime = inline.get("mimeType") or inline.get("mime_type") or mime
                    break
            if not audio_b64:
                last = "no audio in response"
                continue
            raw = base64.b64decode(audio_b64)
            wav_path = dest.with_suffix(".wav")
            _write_pcm_wav(wav_path, raw, mime)
            duration = _wav_duration(wav_path)
            words = _estimate_words(text, duration)
            return TTSResult(wav_path, voice, "gemini", words, duration, text)
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            continue
    if last:
        raise RuntimeError(last)
    return None


def _write_pcm_wav(path: Path, raw: bytes, mime: str) -> None:
    # Gemini typically returns raw PCM L16. If it returned a container, write as-is
    # and let ffmpeg normalize later.
    if raw[:4] == b"RIFF" or raw[:3] == b"ID3" or raw[:4] == b"fLaC" or raw[:4] == b"OggS":
        path.write_bytes(raw)
        return
    rate = 24000
    m = re.search(r"rate=(\d+)", mime or "")
    if m:
        rate = int(m.group(1))
    channels = 1
    sampwidth = 2
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(raw)


def _edge_tts(text: str, dest: Path, voice: str) -> TTSResult:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError(
            "edge-tts is not installed. Run: pip install edge-tts"
        ) from exc

    async def _run() -> tuple[bytes, list[Word]]:
        comm = edge_tts.Communicate(text, voice=voice, rate="+4%", pitch="+0Hz")
        audio = bytearray()
        words: list[Word] = []
        async for chunk in comm.stream():
            typ = chunk.get("type")
            if typ == "audio":
                audio.extend(chunk.get("data") or b"")
            elif typ == "WordBoundary":
                # offset / duration are in 100-nanosecond units
                start = float(chunk.get("offset", 0)) / 10_000_000
                dur = float(chunk.get("duration", 0)) / 10_000_000
                token = (chunk.get("text") or "").strip()
                if token:
                    words.append(Word(token, start, start + max(0.05, dur)))
        return bytes(audio), words

    audio, words = asyncio.run(_run())
    if len(audio) < 1000:
        raise RuntimeError("edge-tts returned empty audio")
    mp3 = dest.with_suffix(".mp3")
    mp3.write_bytes(audio)
    wav_path = dest.with_suffix(".wav")
    _to_wav(mp3, wav_path)
    duration = _wav_duration(wav_path)
    if not words:
        words = _estimate_words(text, duration)
    else:
        # Clamp to duration
        for w in words:
            w.start = max(0.0, min(w.start, duration))
            w.end = max(w.start + 0.04, min(w.end, duration))
    return TTSResult(wav_path, voice, "edge-tts", words, duration, text)


def _to_wav(src: Path, dest: Path) -> None:
    from clipper.ffmpeg_utils import find_ffmpeg, run

    ffmpeg = find_ffmpeg()
    run([ffmpeg, "-y", "-i", str(src), "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(dest)])
    if not dest.is_file():
        raise RuntimeError(f"Could not convert TTS audio to wav: {dest}")


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 1
            return frames / float(rate)
    except Exception:
        from clipper.ffmpeg_utils import probe_duration

        return probe_duration(path)


def _estimate_words(text: str, duration: float) -> list[Word]:
    tokens = re.findall(r"[A-Za-z0-9']+|[.,!?]", text)
    tokens = [t for t in tokens if t.strip()]
    if not tokens or duration <= 0:
        return []
    # Weight punctuation as a short pause, words by character length.
    weights = [0.25 if re.fullmatch(r"[.,!?]", t) else max(0.35, len(t) * 0.08) for t in tokens]
    total = sum(weights) or 1.0
    t, words = 0.0, []
    for tok, w in zip(tokens, weights):
        dur = duration * (w / total)
        if not re.fullmatch(r"[.,!?]", tok):
            words.append(Word(tok, t, t + dur))
        t += dur
    return words


def transcript_from_tts(tts: TTSResult) -> Transcript:
    text = tts.text or " ".join(w.word for w in tts.words)
    return Transcript(text=text, language="en", segments=[], words=list(tts.words), duration=tts.duration)
