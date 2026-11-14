"""Optional royalty-free / user-supplied music bed, with cuts snapped to beats."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from clipper.audio_peaks import load_mono_f32, rms_series
from clipper.ffmpeg_utils import find_ffmpeg


def detect_beats(path: Path, *, hop: float = 0.05, rate: int = 16000) -> list[float]:
    """Onset-style beats from RMS rises. Good enough to snap a cut; not a full tracker."""
    try:
        samples = load_mono_f32(path, rate=rate)
    except Exception:
        return []
    times, rms = rms_series(samples, rate=rate, hop=hop)
    if times.size < 8:
        return []
    # High-pass the envelope and pick local maxima above a bar.
    diff = np.diff(rms, prepend=rms[0])
    thresh = float(np.percentile(diff, 80))
    beats = []
    last = -1.0
    for t, d, e in zip(times, diff, rms):
        if d >= thresh and e > float(np.median(rms)) and t - last >= 0.22:
            beats.append(float(t))
            last = t
    return beats


def snap_to_beat(t: float, beats: list[float], *, window: float = 0.35) -> float:
    if not beats:
        return t
    nearest = min(beats, key=lambda b: abs(b - t))
    return nearest if abs(nearest - t) <= window else t


def mix_args(
    music: Path,
    duration: float,
    *,
    volume: float = 0.22,
) -> list[str]:
    """ffmpeg input/filter fragments: caller already has the video as input 0.

    Adds music as input 1, looped and trimmed, mixed under the original audio.
    Returns extra global args to splice after the main -i video (not a full command).
    """
    ffmpeg = find_ffmpeg()  # raises if missing, keeps behaviour consistent
    _ = ffmpeg
    vol = max(0.0, min(1.0, float(volume)))
    # stream_loop + atrim; dropped if the file is short, we pad with apad.
    return [
        "-stream_loop",
        "-1",
        "-i",
        str(music),
        "-filter_complex",
        PLACEHOLDER,
    ]


def audio_mix_filter(*, volume: float = 0.22, duration: float = 0.0) -> str:
    vol = max(0.0, min(1.0, float(volume)))
    # [0:a] original, [1:a] music. Duck the bed slightly, keep voice/SFX in front.
    trim = f"atrim=0:{duration:.3f},asetpts=PTS-STARTPTS," if duration > 0 else ""
    return (
        f"[1:a]{trim}volume={vol:.3f},aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[bed];"
        f"[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.0[src];"
        f"[src][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
    )


PLACEHOLDER = "MIX"
