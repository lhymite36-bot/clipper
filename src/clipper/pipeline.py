"""End-to-end clipping pipeline."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from clipper.download import download
from clipper.ffmpeg_utils import probe_duration
from clipper.metadata import fill_metadata, render_sidecar
from clipper.moments import Moment, select_moments
from clipper.render import render_clip
from clipper.transcribe import transcribe


@dataclass
class ClipResult:
    index: int
    path: str
    sidecar: str
    start: float
    end: float
    duration: float
    hook: str
    reason: str
    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)
    style: str = ""
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _slug(text: str, fallback: str = "clip") -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip()).strip("-")
    return (text[:40] or fallback).lower()


def run_pipeline(
    source: str,
    out_dir: Path | str,
    *,
    count: int = 5,
    model: str = "tiny",
    hook: str | None = None,
    style: str = "auto",
    min_dur: float = 15.0,
    max_dur: float = 60.0,
    captions: bool = True,
    gemini_key: str | None = None,
    groq_key: str | None = None,
    keep_work: bool = False,
    progress=None,
) -> list[ClipResult]:
    log = progress or (lambda *_a, **_k: None)
    if count < 1:
        raise ValueError("--count must be at least 1")
    if min_dur <= 0 or max_dur < min_dur:
        raise ValueError("Invalid duration window")

    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = out_dir / "_work"
    workdir.mkdir(parents=True, exist_ok=True)

    video, info = download(source, workdir, progress=log)
    duration = float(info.get("duration") or 0) or probe_duration(video)
    source_title = info.get("title") or Path(source).stem
    source_url = info.get("webpage_url") or (source if source.startswith("http") else "")
    uploader = info.get("uploader") or ""

    transcript = transcribe(video, workdir, model_size=model, progress=log)
    if not transcript.duration:
        transcript.duration = duration

    moments = select_moments(
        transcript,
        duration,
        count,
        wav=workdir / "audio.wav",
        min_dur=min(min_dur, duration),
        max_dur=max_dur,
        gemini_key=gemini_key,
        groq_key=groq_key,
        source_title=source_title,
        progress=log,
    )
    if not moments:
        raise RuntimeError("Could not find any clip-worthy moments in this video.")

    results: list[ClipResult] = []
    for i, moment in enumerate(moments, start=1):
        fill_metadata(moment, transcript, source_title=source_title, source_url=source_url, uploader=uploader)
        used_hook = hook if hook else moment.hook
        name = f"{i:02d}-{_slug(moment.title or used_hook or 'clip')}.mp4"
        dest = out_dir / name
        log(f"Rendering clip {i}/{len(moments)} ({moment.start:.1f}s–{moment.end:.1f}s)…")
        render_clip(
            video,
            dest,
            moment.start,
            moment.end,
            transcript,
            hook=used_hook,
            style=style,
            captions=captions,
            progress=log,
        )
        sidecar = dest.with_suffix(".txt")
        sidecar.write_text(render_sidecar(moment, i), encoding="utf-8")
        results.append(
            ClipResult(
                index=i,
                path=str(dest),
                sidecar=str(sidecar),
                start=moment.start,
                end=moment.end,
                duration=moment.duration,
                hook=used_hook or "",
                reason=moment.reason,
                title=moment.title,
                description=moment.description,
                hashtags=list(moment.hashtags),
                style=style,
                source=moment.source,
            )
        )
        log(f"Saved {dest.name} — {moment.title}")

    manifest = {
        "source": source,
        "source_title": source_title,
        "source_url": source_url,
        "duration": duration,
        "count": len(results),
        "clips": [r.to_dict() for r in results],
    }
    (out_dir / "clips.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"Done. {len(results)} clip(s) in {out_dir}")

    if not keep_work:
        # Keep the downloaded source in case the user wants to re-cut; drop wav.
        wav = workdir / "audio.wav"
        if wav.exists():
            try:
                wav.unlink()
            except OSError:
                pass
    return results
