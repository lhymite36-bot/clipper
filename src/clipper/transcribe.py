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


def default_model_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "Clipper" / "models"
    return Path.home() / ".cache" / "clipper" / "models"


def transcribe(
    video: Path | str,
    workdir: Path,
    *,
    model_size: str = "tiny",
    device: str = "cpu",
    compute_type: str | None = None,
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
    segments_iter, info = model.transcribe(
        audio,
        word_timestamps=True,
        vad_filter=True,
        beam_size=1,
    )

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
        log(f"  [{seg.start:7.1f}–{seg.end:7.1f}] {text}")

    language = getattr(info, "language", None) or "en"
    duration = float(getattr(info, "duration", 0) or last_end)
    transcript = Transcript(
        text=" ".join(t for t in texts if t).strip(),
        language=language,
        segments=segments,
        words=words,
        duration=duration,
    )
    log(f"Transcript ready ({len(words)} words, language={language})")
    return transcript
