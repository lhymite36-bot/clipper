"""Original, generated stock SFX (whoosh, impact, riser). No third-party rips."""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

from clipper.paths import user_data_dir

NAMES = ("whoosh", "impact", "riser")


def sfx_dir() -> Path:
    path = user_data_dir() / "sfx"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_sfx() -> dict[str, Path]:
    dest_dir = sfx_dir()
    paths: dict[str, Path] = {}
    for name in NAMES:
        dest = dest_dir / f"{name}.wav"
        if not dest.is_file() or dest.stat().st_size < 500:
            _write_sfx(dest, name)
        paths[name] = dest
    return paths


def _write_sfx(dest: Path, name: str, rate: int = 44100) -> None:
    rng = np.random.default_rng(abs(hash(name)) % (2**31))
    if name == "whoosh":
        seconds = 0.55
        n = int(seconds * rate)
        t = np.arange(n) / rate
        noise = rng.normal(0, 1, n)
        # High-pass-ish sweep: more high end as it goes.
        tone = np.sin(2 * math.pi * (400 + 2400 * (t / seconds)) * t) * 0.15
        env = np.sin(math.pi * np.clip(t / seconds, 0, 1)) ** 1.2
        samples = (0.35 * noise * env + tone) * 0.5
    elif name == "impact":
        seconds = 0.35
        n = int(seconds * rate)
        t = np.arange(n) / rate
        click = np.exp(-t * 28) * rng.normal(0, 1, n) * 0.6
        boom = np.exp(-t * 10) * np.sin(2 * math.pi * (90 * np.exp(-t * 6)) * t)
        samples = 0.55 * click + 0.7 * boom
    else:  # riser
        seconds = 0.9
        n = int(seconds * rate)
        t = np.arange(n) / rate
        freq = 220 * (2 ** (t / seconds * 2.2))
        tone = np.sin(2 * math.pi * freq * t)
        noise = rng.normal(0, 1, n) * (t / seconds)
        env = (t / seconds) ** 1.4
        samples = (0.55 * tone + 0.25 * noise) * env
    fade = int(0.01 * rate)
    samples = np.asarray(samples, dtype=np.float64)
    samples[:fade] *= np.linspace(0, 1, fade)
    samples[-fade:] *= np.linspace(1, 0, fade)
    samples = np.clip(samples, -0.89, 0.89)
    pcm = (samples * 32767.0).astype(np.int16)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())


def plan_hits(duration: float, peak: float | None, *, hook: bool = True) -> list[tuple[str, float]]:
    """When to play each effect, in output-timeline seconds."""
    hits: list[tuple[str, float]] = []
    if hook:
        hits.append(("whoosh", 0.05))
    if peak is not None and 0.2 < peak < max(0.4, duration - 0.04):
        hits.append(("riser", max(0.05, peak - 0.75)))
        hits.append(("impact", peak))
    return hits
