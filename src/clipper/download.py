"""Download a URL with yt-dlp, or accept a local video file."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from clipper.ffmpeg_utils import FFmpegError, find_ffmpeg, probe_duration

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".mpeg", ".mpg", ".wmv"}


def is_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _safe_filename(name: str) -> str:
    keep = "-_.() []"
    cleaned = "".join(ch if ch.isalnum() or ch in keep else "_" for ch in name)
    return cleaned.strip(" ._")[:80] or "source"


def download(source: str, workdir: Path, progress=None) -> tuple[Path, dict]:
    """Return (local_video_path, info_dict)."""
    workdir.mkdir(parents=True, exist_ok=True)
    log = progress or (lambda *_a, **_k: None)

    if not is_url(source):
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Video file not found: {source}")
        info = {
            "title": path.stem,
            "webpage_url": str(path),
            "duration": _duration_or_zero(path),
            "extractor": "local",
        }
        return path, info

    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp") from exc

    outtmpl = str(workdir / "source.%(ext)s")
    ffmpeg = None
    try:
        ffmpeg = str(Path(find_ffmpeg()).parent)
    except FFmpegError:
        pass

    info: dict = {}

    def hook(d):
        if d.get("status") == "downloading":
            frac = d.get("_percent_str") or ""
            log(f"Downloading {frac}".strip())
        elif d.get("status") == "finished":
            log("Download finished, merging if needed…")

    opts = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "noplaylist": True,
        "overwrites": True,
    }
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg

    log("Downloading video…")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source, download=True)
        if info and "entries" in info and info["entries"]:
            info = info["entries"][0]
        prepared = ydl.prepare_filename(info)
    path = Path(prepared)
    if not path.is_file():
        # merge may have changed extension to mp4
        matches = sorted(workdir.glob("source.*"))
        matches = [m for m in matches if m.suffix.lower() in VIDEO_EXTS or m.suffix.lower() == ".mp4"]
        if not matches:
            raise RuntimeError(f"Download succeeded but no video file was found in {workdir}")
        path = matches[0]
    # Prefer mp4 if both exist
    mp4 = workdir / "source.mp4"
    if mp4.is_file():
        path = mp4

    meta = {
        "title": (info or {}).get("title") or path.stem,
        "webpage_url": (info or {}).get("webpage_url") or source,
        "duration": (info or {}).get("duration") or _duration_or_zero(path),
        "uploader": (info or {}).get("uploader") or "",
        "extractor": (info or {}).get("extractor") or "",
        "license": (info or {}).get("license") or "",
    }
    log(f"Source ready: {meta['title']}")
    return path, meta


def _duration_or_zero(path: Path) -> float:
    try:
        return probe_duration(path)
    except FFmpegError:
        return 0.0
