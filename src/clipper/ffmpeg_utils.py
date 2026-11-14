"""Locate ffmpeg/ffprobe and run them."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def _bundle_dir() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _candidates(name: str) -> list[Path]:
    found: list[Path] = []
    bundled = _bundle_dir()
    if bundled:
        found.append(bundled / name)
        found.append(bundled / "ffmpeg" / name)
        # PyInstaller onedir
        internal = bundled / "_internal" / name
        found.append(internal)
    env = os.environ.get("FFMPEG_BINARY") if name.startswith("ffmpeg") else os.environ.get("FFPROBE_BINARY")
    if env:
        found.append(Path(env))
    which = shutil.which(name)
    if which:
        found.append(Path(which))
    # Common Windows locations
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    extras = [
        Path(local) / "Programs" / "Clipper" / name,
        Path(local) / "Microsoft" / "WinGet" / "Links" / name,
        Path(pf) / "ffmpeg" / "bin" / name,
        Path(pf86) / "ffmpeg" / "bin" / name,
        Path("C:/ffmpeg/bin") / name,
    ]
    found.extend(extras)
    return found


def find_binary(name: str) -> str:
    exe = name if os.name != "nt" else (name if name.endswith(".exe") else f"{name}.exe")
    base = name[:-4] if name.endswith(".exe") else name
    for cand in _candidates(exe) + _candidates(base):
        if cand and cand.is_file():
            return str(cand)
    # shutil.which already tried; last resort
    which = shutil.which(base) or shutil.which(exe)
    if which:
        return which
    raise FFmpegError(
        f"{base} was not found. Install FFmpeg and make sure it is on your PATH, "
        "or place ffmpeg.exe next to Clipper."
    )


def find_ffmpeg() -> str:
    return find_binary("ffmpeg")


def find_ffprobe() -> str:
    return find_binary("ffprobe")


def run(args: list[str], *, check: bool = True, capture: bool = True, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args,
            check=check,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            input=stdin,
        )
    except FileNotFoundError as exc:
        raise FFmpegError(f"Could not run {args[0]}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode("utf-8", "replace")[-4000:]
        raise FFmpegError(f"Command failed ({exc.returncode}): {' '.join(args[:6])}...\n{err}") from exc


def probe_duration(path: Path | str) -> float:
    ffprobe = find_ffprobe()
    proc = run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    text = (proc.stdout or b"").decode().strip()
    try:
        return float(text)
    except ValueError as exc:
        raise FFmpegError(f"Could not read duration of {path}: {text!r}") from exc


def probe_size(path: Path | str) -> tuple[int, int]:
    ffprobe = find_ffprobe()
    proc = run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(path),
        ]
    )
    text = (proc.stdout or b"").decode().strip().splitlines()[0] if proc.stdout else ""
    try:
        w, h = text.split("x")
        return int(w), int(h)
    except (ValueError, IndexError) as exc:
        raise FFmpegError(f"Could not read video size of {path}: {text!r}") from exc


def extract_wav(video: Path | str, wav: Path | str, rate: int = 16000) -> Path:
    ffmpeg = find_ffmpeg()
    wav = Path(wav)
    wav.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-c:a",
            "pcm_s16le",
            str(wav),
        ]
    )
    return wav
