"""Scene-change / action scores from low-res frame differences."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from clipper.audio_peaks import zscore
from clipper.ffmpeg_utils import find_ffmpeg


def frame_diff_series(
    video: Path | str,
    duration: float,
    *,
    fps: float = 4.0,
    width: int = 160,
    height: int = 90,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (times, z-scored frame-to-frame difference). Empty on failure."""
    try:
        ffmpeg = find_ffmpeg()
    except Exception:
        return np.zeros(0), np.zeros(0)
    frame_size = width * height  # gray8
    args = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(video),
        "-t",
        f"{max(0.2, float(duration)):.3f}",
        "-vf",
        f"fps={fps},scale={width}:{height},format=gray",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return np.zeros(0), np.zeros(0)
    assert proc.stdout is not None
    prev: np.ndarray | None = None
    diffs: list[float] = []
    times: list[float] = []
    t = 0.0
    hop = 1.0 / fps
    try:
        while True:
            data = proc.stdout.read(frame_size)
            if not data or len(data) < frame_size:
                break
            frame = np.frombuffer(data, dtype=np.uint8).astype(np.float32)
            if prev is not None:
                diffs.append(float(np.mean(np.abs(frame - prev))))
                times.append(t)
            prev = frame
            t += hop
            if t > duration + 1:
                break
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
    if not diffs:
        return np.zeros(0), np.zeros(0)
    return np.array(times, dtype=np.float64), zscore(np.array(diffs, dtype=np.float64))
