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


def fill_blur_graph(y: int, pic_h: int = 900, *, src: str = "vin", out: str = "vlaid") -> str:
    """Blur-fill a 9:16 frame and overlay a zoomed-sharp picture at y."""
    pic_h = max(400, int(pic_h) // 2 * 2)
    return (
        f"[{src}]split=2[bg][fg];"
        f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"boxblur=22:8,eq=brightness=-0.07[b];"
        f"[fg]scale=1080:{pic_h}:force_original_aspect_ratio=increase,"
        f"crop=1080:{pic_h}[f];"
        f"[b][f]overlay=(W-w)/2:{int(y)}[ov];"
        f"[ov]format=yuv420p[{out}]"
    )


def parse_fill_token(vf: str) -> tuple[int, int, int] | None:
    if not (vf or "").startswith("FILL:"):
        return None
    _tag, top, y, pic_h = vf.split(":")
    return int(top), int(y), int(pic_h)


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
    music_volume: float = 0.16,
    sfx: bool = True,
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
    raw_vf = layout.vf
    fill = parse_fill_token(raw_vf)
    log(f"Layout: {layout.mode}")

    grade = grade_filter(spec.grade if spec else "none")
    if grade:
        log(f"Grade: {spec.grade}")
    post_vf = grade or ""

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
        punch_vf = punch_in_filter(peak_rel)
        post_vf = f"{post_vf},{punch_vf}" if post_vf else punch_vf
        log(f"Punch-in at {peak_rel:.2f}s")

    banner_text = hook_banner.display if hook_banner else (hook or "")
    keywords = hook_banner.keywords if hook_banner else []
    bar = hook_bar_filter(layout)
    if bar and banner_text.strip():
        post_vf = f"{post_vf},{bar}" if post_vf else bar

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
            hook_font_size=96 if layout.mode in {"bars", "fill"} else 82,
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

    want_loop = bool(spec.loop) if spec is not None else True
    freeze = 0.35 if want_loop else 0.0
    encode_dur = out_dur + freeze

    sfx_hits: list[tuple[str, float, Path]] = []
    if sfx:
        try:
            from clipper.sfx import ensure_sfx, plan_hits

            bank = ensure_sfx()
            peak_out = time_map(peak_rel) if (time_map and peak_rel is not None) else peak_rel
            for name, when in plan_hits(out_dur, peak_out, hook=bool(banner_text.strip())):
                path = bank.get(name)
                if path and path.is_file() and 0 <= when < out_dur:
                    sfx_hits.append((name, when, path))
        except Exception as exc:  # noqa: BLE001
            log(f"SFX skipped: {exc}")

    use_complex = bool(fill or time_map or use_music or sfx_hits or freeze or post_vf)
    if not use_complex:
        vf = raw_vf
        if post_vf:
            vf = f"{vf},{post_vf}" if vf else post_vf
        if sub_vf:
            vf = f"{vf},{sub_vf}" if vf else sub_vf
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
            f"[0:v]trim=start=0:duration={duration:.4f},setpts=PTS-STARTPTS[vtrim]",
            f"[0:a]atrim=start=0:duration={duration:.4f},asetpts=PTS-STARTPTS[acore]",
        ]
        if fill:
            _top, y, pic_h = fill
            parts.append(fill_blur_graph(y, pic_h, src="vtrim", out="vlaid"))
        elif raw_vf:
            parts.append(f"[vtrim]{raw_vf}[vlaid]")
        else:
            parts.append("[vtrim]copy[vlaid]")
        v_lab = "vlaid"
        if post_vf:
            parts.append(f"[{v_lab}]{post_vf}[vpost]")
            v_lab = "vpost"
        a_lab = "acore"
        sp = speed_filter(segs, v_in=v_lab, a_in="acore", v_out="vr", a_out="ar") if time_map else None
        if sp:
            v_fc, a_fc = sp
            parts.append(v_fc)
            parts.append(a_fc)
            v_lab, a_lab = "vr", "ar"
        if sub_vf:
            parts.append(f"[{v_lab}]{sub_vf}[vsub]")
            v_lab = "vsub"
        if freeze > 0:
            parts.append(f"[{v_lab}]tpad=stop_mode=clone:stop_duration={freeze:.3f}[vloop]")
            v_lab = "vloop"
            fade_st = max(0.0, encode_dur - 0.22)
            parts.append(f"[{a_lab}]afade=t=out:st={fade_st:.3f}:d=0.2,apad=pad_dur={freeze:.3f}[aloop]")
            a_lab = "aloop"
            log(f"Loop: freeze last frame {freeze:.2f}s")
        maps = ["-map", f"[{v_lab}]"]
        extra_inputs: list[str] = []
        input_index = 1
        if use_music:
            from clipper.library import duck_filter

            extra_inputs += ["-stream_loop", "-1", "-i", str(music_path)]
            parts.append(
                f"[{input_index}:a]atrim=0:{encode_dur:.3f},asetpts=PTS-STARTPTS[bed]"
            )
            parts.append(duck_filter(speech=a_lab, bed="bed", out="amix", bed_volume=music_volume))
            a_lab = "amix"
            input_index += 1
            log(f"Mixing ducked music bed ({music_path.name})")
        for name, when, path in sfx_hits:
            extra_inputs += ["-i", str(path)]
            delay_ms = int(max(0, when) * 1000)
            lab = f"sfx{input_index}"
            parts.append(
                f"[{input_index}:a]adelay={delay_ms}|{delay_ms},aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[{lab}]"
            )
            log(f"SFX {name} at {when:.2f}s")
            input_index += 1
        if sfx_hits:
            first = 1 + (1 if use_music else 0)
            labels = [a_lab] + [f"sfx{first + i}" for i in range(len(sfx_hits))]
            n = len(labels)
            parts.append(
                "".join(f"[{lab}]" for lab in labels)
                + f"amix=inputs={n}:duration=first:dropout_transition=0:normalize=0[asfx]"
            )
            a_lab = "asfx"
        parts.append(f"[{a_lab}]{LOUDNORM}[anorm]")
        maps += ["-map", "[anorm]"]

        args = [
            ffmpeg, "-y",
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
            "-i", str(source),
            *extra_inputs,
            "-filter_complex", ";".join(parts),
            *maps,
            *_encode_tail(encode_dur, af=False),
            str(dest),
        ]
        log(f"Encoding {dest.name}…")
        run(args)

    if not dest.is_file() or dest.stat().st_size < 1000:
        raise RuntimeError(f"Encoder did not produce a valid file: {dest}")
    return dest


# YouTube-friendly loudness. TP=-1.5 avoids the 0 dBFS clipping common
# in source files; I=-14 matches YouTube's integrated target.
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.84:level=false"


def _encode_tail(duration: float, *, af: bool = True) -> list[str]:
    args = [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100",
        "-movflags", "+faststart", "-t", f"{duration:.3f}",
    ]
    if af:
        args = ["-af", LOUDNORM, *args]
    return args
