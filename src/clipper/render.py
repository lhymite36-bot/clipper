"""Cut, reframe, caption and encode a single Short as H.264 MP4."""

from __future__ import annotations

from pathlib import Path

from clipper.captions import build_ass, fonts_dir
from clipper.ffmpeg_utils import find_ffmpeg, run
from clipper.reframe import plan_reframe
from clipper.style import (
    HookBanner,
    LayoutPlan,
    StyleSpec,
    grade_filter,
    hook_bar_filter,
    output_duration,
    speed_filter,
    speed_segments,
    src_to_out,
)
from clipper.transcribe import Transcript


def _escape_filter_path(path: Path) -> str:
    text = path.resolve().as_posix()
    text = text.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    return text


def punch_in_filter(
    peak_in_clip: float,
    *,
    zoom: float = 1.12,
    attack: float = 0.45,
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Zoom toward the center starting just before the payoff, then hold."""
    start = max(0.0, float(peak_in_clip) - 0.08)
    z = max(1.01, float(zoom))
    expr = f"min({z:.3f},1+({z:.3f}-1)*max(0,min(1,(t-{start:.3f})/{attack:.3f})))"
    return (
        f"scale=w='trunc(iw*({expr})/2)*2':h='trunc(ih*({expr})/2)*2':eval=frame,"
        f"crop={width}:{height}:(in_w-{width})/2:(in_h-{height})/2"
    )


def render_clip(
    source: Path,
    dest: Path,
    start: float,
    end: float,
    transcript: Transcript,
    *,
    hook: str | None = None,
    hook_banner: HookBanner | None = None,
    style: str = "auto",
    captions: bool = True,
    peak: float | None = None,
    punch: bool = True,
    spec: StyleSpec | None = None,
    layout: LayoutPlan | None = None,
    music: Path | str | None = None,
    music_volume: float = 0.22,
    progress=None,
) -> Path:
    log = progress or (lambda *_a, **_k: None)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = dest.parent
    duration = max(0.2, end - start)
    peak_rel = None if peak is None else max(0.0, min(duration, peak - start))

    if layout is None:
        vf, resolved, _face = plan_reframe(source, start, end, style=style, progress=log)
        log(f"Reframe style: {resolved}")
        layout = LayoutPlan("tight", vf, 384, 0, 72, 260)
    vf = layout.vf
    log(f"Layout: {layout.mode}")

    grade = grade_filter(spec.grade if spec else "none")
    if grade:
        vf = f"{vf},{grade}"
        log(f"Grade: {spec.grade}")

    segs = speed_segments(
        duration,
        peak_rel,
        enabled=bool(spec and spec.speed_ramps and peak_rel is not None),
    )
    out_dur = output_duration(segs)
    time_map = (lambda t, _s=segs: src_to_out(t, _s)) if speed_filter(segs) else None
    if time_map:
        log(f"Speed ramps around the peak ({out_dur:.1f}s output)")

    # Punch uses the timestamp at the filter that applies it. We punch before
    # ramps, so this is source-relative time inside the trimmed clip.
    want_punch = punch if spec is None else (spec.punch and punch)
    if want_punch and peak_rel is not None:
        vf = f"{vf},{punch_in_filter(peak_rel)}"
        log(f"Punch-in at {peak_rel:.2f}s")

    banner_text = hook_banner.display if hook_banner else (hook or "")
    keywords = hook_banner.keywords if hook_banner else []
    bar = hook_bar_filter(layout)
    if bar and banner_text.strip():
        vf = f"{vf},{bar}"

    word_captions = bool(captions)
    if spec is not None:
        if spec.captions in {"none", "minimal"}:
            word_captions = False
        elif spec.captions == "words":
            word_captions = True
        # "auto" keeps the captions= flag from the caller

    sub_vf = ""
    if banner_text.strip() or word_captions:
        clip_transcript = transcript.shifted(start, end)
        ass_path = work / (dest.stem + ".ass")
        build_ass(
            clip_transcript,
            ass_path,
            hook=banner_text or None,
            hook_keywords=keywords,
            hook_margin_v=layout.hook_margin_v,
            caption_margin_v=layout.caption_margin_v,
            hook_font_size=68 if layout.mode == "bars" else 64,
            word_captions=word_captions,
            duration=duration,
            time_map=time_map,
        )
        fonts = fonts_dir()
        fonts_arg = f":fontsdir='{_escape_filter_path(fonts)}'" if fonts else ""
        sub_vf = f"subtitles='{_escape_filter_path(ass_path)}'{fonts_arg}"

    ffmpeg = find_ffmpeg()
    music_path = Path(music) if music else None
    use_music = bool(music_path and music_path.is_file())
    if music and not use_music:
        log(f"Music file not found, skipping bed: {music}")

    # Fast path: no ramps, no music — a single -vf graph.
    if not time_map and not use_music:
        if sub_vf:
            vf = f"{vf},{sub_vf}"
        args = [
            ffmpeg, "-y",
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
            "-i", str(source),
            "-vf", vf,
            *_encode_tail(duration),
            str(dest),
        ]
        log(f"Encoding {dest.name}…")
        run(args)
    else:
        parts = [
            f"[0:v]trim=start=0:duration={duration:.4f},setpts=PTS-STARTPTS,{vf}[vcore]",
            f"[0:a]atrim=start=0:duration={duration:.4f},asetpts=PTS-STARTPTS[acore]",
        ]
        v_lab, a_lab = "vcore", "acore"
        sp = speed_filter(segs, v_in="vcore", a_in="acore", v_out="vr", a_out="ar") if time_map else None
        if sp:
            v_fc, a_fc = sp
            parts.append(v_fc)
            parts.append(a_fc)
            v_lab, a_lab = "vr", "ar"
        # Subtitles go on the output timeline (times already remapped).
        if sub_vf:
            parts.append(f"[{v_lab}]{sub_vf}[vout]")
            v_lab = "vout"
        maps = ["-map", f"[{v_lab}]"]
        extra_inputs: list[str] = []
        if use_music:
            from clipper.music import audio_mix_filter

            extra_inputs = ["-stream_loop", "-1", "-i", str(music_path)]
            mix = audio_mix_filter(volume=music_volume, duration=out_dur)
            mix = mix.replace("[0:a]", f"[{a_lab}]")
            parts.append(mix)
            maps += ["-map", "[aout]"]
            log(f"Mixing music bed ({music_path.name})")
        else:
            maps += ["-map", f"[{a_lab}]"]

        args = [
            ffmpeg, "-y",
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
            "-i", str(source),
            *extra_inputs,
            "-filter_complex", ";".join(parts),
            *maps,
            *_encode_tail(out_dur),
            str(dest),
        ]
        log(f"Encoding {dest.name}…")
        run(args)

    if not dest.is_file() or dest.stat().st_size < 1000:
        raise RuntimeError(f"Encoder did not produce a valid file: {dest}")
    return dest


def _encode_tail(duration: float) -> list[str]:
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100",
        "-movflags", "+faststart", "-t", f"{duration:.3f}",
    ]
