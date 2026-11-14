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
    peak: float | None = None
    peak_kind: str = ""
    preset: str = ""
    layout: str = ""
    title_options: list[str] = field(default_factory=list)

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
    captions: bool | str = True,
    gemini_key: str | None = None,
    groq_key: str | None = None,
    keep_work: bool = False,
    punch: bool = True,
    preset: str = "auto",
    layout: str | None = None,
    grade: str | None = None,
    music: Path | str | None = None,
    music_volume: float = 0.22,
    loop: bool = True,
    speed_ramps: bool | None = None,
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

    from clipper.ffmpeg_utils import probe_size
    from clipper.reframe import detect_face_center
    from clipper.style import (
        HookBanner,
        build_hook_banner,
        pick_keywords,
        plan_layout,
        resolve_spec,
        snap_calm_end,
        suggest_titles,
    )
    from clipper.moments import _is_generic_hook

    try:
        src_w, src_h = probe_size(video)
    except Exception:
        src_w, src_h = 1920, 1080
    src_aspect = src_w / max(src_h, 1)

    captions_mode: str | None
    if captions is False or (isinstance(captions, str) and captions.lower() in {"0", "false", "off", "none"}):
        captions_mode = "none"
    elif isinstance(captions, str) and captions.lower() in {"words", "minimal", "auto"}:
        captions_mode = captions.lower()
    else:
        captions_mode = "auto"

    spec = resolve_spec(
        preset,
        transcript=transcript,
        duration=duration,
        src_aspect=src_aspect,
        layout=layout,
        grade=grade,
        captions=captions_mode,
        punch=False if punch is False else None,
        speed_ramps=speed_ramps,
        loop=loop,
    )
    log(f"Preset: {spec.name} (layout={spec.layout}, grade={spec.grade}, captions={spec.captions})")

    music_path = Path(music) if music else None
    if music and not (music_path and music_path.is_file()):
        log(f"Music file not found, continuing without a bed: {music}")
        music_path = None

    moments = select_moments(
        transcript,
        duration,
        count,
        wav=workdir / "audio.wav",
        video=video,
        min_dur=min(min_dur, duration),
        max_dur=max_dur,
        gemini_key=gemini_key,
        groq_key=groq_key,
        source_title=source_title,
        progress=log,
    )
    if not moments:
        raise RuntimeError(
            "No clip-worthy peak was found (a laugh, reaction, punchline, "
            "loud spike, scene change or action beat). Clipper will not pad "
            "the count with clips that have no payoff."
        )

    results: list[ClipResult] = []
    for i, moment in enumerate(moments, start=1):
        if spec.loop:
            new_end = snap_calm_end(
                video, moment.start, moment.end, moment.peak, enabled=True
            )
            if new_end < moment.end - 0.05:
                log(f"Loop: trimmed end {moment.end:.2f}s → {new_end:.2f}s for a calmer last frame")
                moment.end = new_end

        fill_metadata(moment, transcript, source_title=source_title, source_url=source_url, uploader=uploader)

        user_hook = (hook or "").strip()
        if user_hook and not (_is_generic_hook(user_hook) and not moment.payoff_in_last_30()):
            banner = HookBanner(
                text=user_hook,
                keywords=pick_keywords(user_hook, 2),
                titles=suggest_titles(user_hook, peak_kind=moment.peak_kind, has_speech=True),
            )
        else:
            banner = build_hook_banner(
                transcript,
                moment.start,
                moment.end,
                peak=moment.peak,
                peak_kind=moment.peak_kind,
                hook_case=spec.hook_case,
                existing=moment.hook or "",
            )
        moment.hook = banner.display
        if banner.titles:
            moment.title_options = banner.titles
            # Heuristic titles should follow the curiosity-gap hook, not a literal line.
            if moment.source != "llm" or not moment.title or moment.title.lower() in {"clip", "wait for it"}:
                moment.title = banner.titles[0]

        face = detect_face_center(video, moment.start, moment.end)
        layout_plan = plan_layout(
            src_w,
            src_h,
            preferred=spec.layout,
            crop_style=style,
            face=face,
            tight_subject=spec.name == "sports-montage",
        )

        used_hook = moment.hook
        name = f"{i:02d}-{_slug(moment.title or used_hook or 'clip')}.mp4"
        dest = out_dir / name
        log(f"Rendering clip {i}/{len(moments)} ({moment.start:.1f}s–{moment.end:.1f}s)…")
        render_clip(
            video,
            dest,
            moment.start,
            moment.end,
            transcript,
            hook=used_hook or None,
            hook_banner=banner,
            style=style,
            captions=captions_mode != "none",
            peak=moment.peak,
            punch=punch and spec.punch,
            spec=spec,
            layout=layout_plan,
            music=music_path,
            music_volume=music_volume,
            progress=log,
        )
        sidecar = dest.with_suffix(".txt")
        sidecar.write_text(
            render_sidecar(moment, i, preset=spec.name, layout=layout_plan.mode),
            encoding="utf-8",
        )
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
                peak=moment.peak,
                peak_kind=moment.peak_kind,
                preset=spec.name,
                layout=layout_plan.mode,
                title_options=list(moment.title_options),
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
