"""Local transcription with word timestamps via faster-whisper."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from clipper.ffmpeg_utils import extract_wav


@dataclass
class Word:
    word: str
    start: float
    end: float
    probability: float = 1.0


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    text: str
    language: str
    segments: list[Segment]
    words: list[Word]
    duration: float

    def text_in(self, start: float, end: float) -> str:
        parts = [w.word for w in self.words if w.start >= start - 0.05 and w.end <= end + 0.05]
        if parts:
            return _join_words(parts)
        bits = []
        for seg in self.segments:
            if seg.end < start or seg.start > end:
                continue
            bits.append(seg.text.strip())
        return " ".join(bits).strip()

    def words_in(self, start: float, end: float) -> list[Word]:
        return [w for w in self.words if w.end > start and w.start < end]

    def shifted(self, start: float, end: float) -> "Transcript":
        """Clip-relative transcript (times start at 0)."""
        words = []
        for w in self.words_in(start, end):
            words.append(
                Word(
                    word=w.word,
                    start=max(0.0, w.start - start),
                    end=max(0.0, min(end, w.end) - start),
                    probability=w.probability,
                )
            )
        segs = []
        for s in self.segments:
            if s.end <= start or s.start >= end:
                continue
            segs.append(
                Segment(
                    start=max(0.0, s.start - start),
                    end=min(end, s.end) - start,
                    text=s.text,
                    words=[
                        Word(w.word, max(0.0, w.start - start), max(0.0, min(end, w.end) - start), w.probability)
                        for w in s.words
                        if w.end > start and w.start < end
                    ],
                )
            )
        text = _join_words([w.word for w in words]) or " ".join(s.text for s in segs).strip()
        return Transcript(text=text, language=self.language, segments=segs, words=words, duration=end - start)


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


LATIN_HINT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'")


def looks_english(text: str) -> bool:
    """True when the transcript is mostly Latin letters (English / Hinglish captions)."""
    letters = [c for c in (text or "") if c.isalpha() or c in "'"]
    if len(letters) < 8:
        return False
    latin = sum(1 for c in letters if c in LATIN_HINT)
    return latin / max(1, len(letters)) >= 0.7


def resolve_language(requested: str | None, detected: str | None, text: str = "") -> str:
    """Honour an explicit language; in auto mode, prefer English when the text is Latin."""
    req = (requested or "auto").strip().lower()
    det = (detected or "").strip().lower() or "en"
    if req and req not in {"auto", "detect", ""}:
        return req
    if det in {"en", "eng"}:
        return "en"
    if looks_english(text):
        return "en"
    return det


def default_model_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "Clipper" / "models"
    return Path.home() / ".cache" / "clipper" / "models"


def transcribe(
    video: Path | str,
    workdir: Path,
    *,
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str | None = None,
    language: str | None = "auto",
    progress=None,
) -> Transcript:
    log = progress or (lambda *_a, **_k: None)
    video = Path(video)
    wav = workdir / "audio.wav"
    log("Extracting audio…")
    extract_wav(video, wav)

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        ) from exc

    compute_type = compute_type or os.environ.get("CLIPPER_COMPUTE_TYPE") or "int8"
    download_root = os.environ.get("CLIPPER_MODEL_DIR") or str(default_model_dir())
    Path(download_root).mkdir(parents=True, exist_ok=True)
    log(f"Transcribing with Whisper {model_size} (first run downloads the model)…")

    model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
        download_root=download_root,
    )
    # Pass raw samples, not a file path. faster-whisper's file path uses
    # PyAV (`av.open(..., metadata_errors=...)`), which broke on newer av
    # builds. We already extracted a 16 kHz mono wav with ffmpeg.
    from clipper.audio_peaks import load_mono_f32

    audio = load_mono_f32(wav, rate=16000)
    lang = (language or "auto").strip().lower()
    transcribe_kw = dict(word_timestamps=True, vad_filter=True, beam_size=1)
    if lang and lang not in {"auto", "detect", ""}:
        transcribe_kw["language"] = lang
        log(f"Forcing language={lang}")
    def _consume(segments_iter, info, silent=False):
        segments: list[Segment] = []
        words: list[Word] = []
        texts: list[str] = []
        last_end = 0.0
        for seg in segments_iter:
            seg_words = []
            for w in seg.words or []:
                token = (w.word or "").strip()
                if not token:
                    continue
                ww = Word(word=token, start=float(w.start), end=float(w.end), probability=float(w.probability or 1.0))
                seg_words.append(ww)
                words.append(ww)
                last_end = max(last_end, ww.end)
            text = (seg.text or "").strip()
            texts.append(text)
            segments.append(Segment(start=float(seg.start), end=float(seg.end), text=text, words=seg_words))
            last_end = max(last_end, float(seg.end))
            if not silent:
                log(f"  [{seg.start:7.1f}–{seg.end:7.1f}] {text}")
        detected = getattr(info, "language", None) or "en"
        body = " ".join(x for x in texts if x).strip()
        duration = float(getattr(info, "duration", 0) or last_end)
        return segments, words, body, detected, duration

    segments_iter, info = model.transcribe(audio, **transcribe_kw)
    segments, words, body, detected, duration = _consume(segments_iter, info)
    language = resolve_language(language, detected, body)
    if (
        language == "en"
        and detected not in {"en", "eng"}
        and looks_english(body)
        and lang in {"auto", "detect", ""}
    ):
        log(f"Language auto-fix: detected {detected}, re-running Whisper in English for clearer captions…")
        segments_iter, info = model.transcribe(audio, language="en", word_timestamps=True, vad_filter=True, beam_size=1)
        segments, words, body, detected, duration = _consume(segments_iter, info)
        language = "en"
    transcript = Transcript(
        text=body,
        language=language,
        segments=segments,
        words=words,
        duration=duration,
    )
    log(f"Transcript ready ({len(words)} words, language={language})")
    return transcript
