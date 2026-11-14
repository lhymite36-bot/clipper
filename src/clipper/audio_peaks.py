"""Loudness / energy analysis used by the local viral-moment heuristic."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from clipper.ffmpeg_utils import extract_wav, find_ffmpeg, run


def load_mono_f32(path: Path, rate: int = 16000) -> np.ndarray:
    """Load audio as float32 mono. Prefers a wav already extracted."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        try:
            return _read_wav_mono(path, rate)
        except Exception:
            pass
    tmp = path.with_suffix(".peak.wav") if path.suffix.lower() != ".wav" else path
    if path.suffix.lower() != ".wav":
        extract_wav(path, tmp, rate=rate)
        path = tmp
    return _read_wav_mono(path, rate)


def _read_wav_mono(path: Path, rate: int) -> np.ndarray:
    ffmpeg = find_ffmpeg()
    proc = run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-f",
            "f32le",
            "pipe:1",
        ]
    )
    data = proc.stdout or b""
    if not data:
        return np.zeros(0, dtype=np.float32)
    count = len(data) // 4
    samples = struct.unpack("<" + "f" * count, data[: count * 4])
    return np.array(samples, dtype=np.float32)


def rms_series(samples: np.ndarray, rate: int = 16000, hop: float = 0.25) -> tuple[np.ndarray, np.ndarray]:
    """Return (times, rms) with one value every `hop` seconds."""
    if samples.size == 0:
        return np.zeros(0), np.zeros(0)
    hop_n = max(1, int(rate * hop))
    n = (len(samples) // hop_n) * hop_n
    if n == 0:
        return np.array([0.0]), np.array([float(np.sqrt(np.mean(samples**2)))])
    framed = samples[:n].reshape(-1, hop_n)
    rms = np.sqrt(np.mean(framed**2, axis=1) + 1e-12)
    times = (np.arange(len(rms)) + 0.5) * hop
    return times, rms


def zscore(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    mu = float(np.mean(x))
    sd = float(np.std(x))
    if sd < 1e-9:
        return np.zeros_like(x)
    return (x - mu) / sd
