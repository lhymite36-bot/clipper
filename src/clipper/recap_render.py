"""Assemble a transformative recap edit: short shots, grade, zoom, ducked audio, captions."""

from __future__ import annotations

from pathlib import Path

from clipper.captions import build_ass, fonts_dir
from clipper.ffmpeg_utils import find_ffmpeg, run
from clipper.recap_fallback import make_still
from clipper.recap_scenes import Shot
from clipper.recap_script import RecapLine, RecapScript
from clipper.style import YT_TOP_SAFE, grade_filter, hook_bar_filter, LayoutPlan, pick_keywords
from clipper.transcribe import Transcript

SHORT_W, SHORT_H = 1080, 1920
LONG_W, LONG_H = 1920, 1080


def _escape_filter_path(path: Path) -> str:
    text = path.resolve().as_posix()
    text = text.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    return text


def render_recap(
    source: Path | None,
    dest: Path,
    script: RecapScript,
    shots: list[Shot],
    voice: Path,
    voice_transcript: Transcript,
    *,
    fmt: str = "short",
    grade: str = "moody",
    music: Path | str | None = None,
    music_volume: float = 0.12,
    duck: float = 0.10,
    progress=None,
) -> Path:
    log = progress or (lambda *_a, **_k: None)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = dest.parent / "_shots"
    work.mkdir(parents=True, exist_ok=True)
    width, height = (SHORT_W, SHORT_H) if fmt == "short" else (LONG_W, LONG_H)
    ffmpeg = find_ffmpeg()
    grade_vf = grade_filter(grade if grade not in {"auto", "", None} else "moody") or grade_filter("moody")

    clip_paths: list[Path] = []
    for i, shot in enumerate(shots):
        out = work / f"shot-{i:04d}.mp4"
        ok = False
        if source and Path(source).is_file():
            try:
                _render_shot(ffmpeg, Path(source), out, shot, width, height, grade_vf, fmt)
                ok = out.is_file() and out.stat().st_size > 1000
            except Exception as exc:  # noqa: BLE001
                log(f"Shot {i} failed ({exc}); using a still")
                ok = False
        if not ok:
            line = script.lines[shot.line_index] if 0 <= shot.line_index < len(script.lines) else RecapLine("Recap")
            make_still(
                out,
                line,
                width=width,
                height=height,
                duration=max(2.0, shot.out_duration or 2.8),
                index=i,
                hook=script.hook,
                title=script.title,
            )
        clip_paths.append(out)
        if i % 8 == 0:
            log(f"Rendered shot {i + 1}/{len(shots)}")

    # Concat video
    concat_list = work / "concat.txt"
    lines = []
    for p in clip_paths:
        # concat demuxer needs escaped single quotes
        ap = p.resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{ap}'")
    concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")
    silent = work / "video.mp4"
    log("Concatenating shots…")
    run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-an",
            str(silent),
        ]
    )

    # Hook bar + captions (word-by-word from the voiceover timings).
    vf_parts = []
    if fmt == "short":
        layout = LayoutPlan("tight", "", int(SHORT_H * 0.20), 0, max(YT_TOP_SAFE, 150), 260)
        bar = hook_bar_filter(layout)
        if bar:
            vf_parts.append(bar)
    hook_margin = max(YT_TOP_SAFE, 150) if fmt == "short" else 48
    cap_margin = 260 if fmt == "short" else 80
    ass_path = dest.with_suffix(".ass")
    keywords = pick_keywords(script.hook, 2) if script.hook else []
    from clipper.ffmpeg_utils import probe_duration

    vo_dur = probe_duration(voice)
    vid_dur = probe_duration(silent)
    out_dur = max(vo_dur, 1.0)
    # If the picture ran short or long, we'll trim/pad to the VO.
    build_ass(
        voice_transcript,
        ass_path,
        hook=script.hook if fmt == "short" else None,
        hook_keywords=keywords,
        hook_margin_v=hook_margin,
        caption_margin_v=cap_margin,
        hook_font_size=68 if fmt == "short" else 56,
        word_captions=True,
        duration=out_dur,
    )
    fonts = fonts_dir()
    fonts_arg = f":fontsdir='{_escape_filter_path(fonts)}'" if fonts else ""
    vf_parts.append(f"subtitles='{_escape_filter_path(ass_path)}'{fonts_arg}")
    vf = ",".join(vf_parts)

    # Audio: VO + ducked original (cut to the same shot windows) + optional music.
    orig_audio = None
    if source and Path(source).is_file():
        try:
            orig_audio = _cut_original_audio(ffmpeg, Path(source), shots, work)
        except Exception as exc:  # noqa: BLE001
            log(f"Original audio cut failed ({exc}); narration only")
            orig_audio = None

    music_path = Path(music) if music else None
    use_music = bool(music_path and music_path.is_file())

    inputs = ["-i", str(silent), "-i", str(voice)]
    # 0 = picture, 1 = voice
    n = 2
    orig_idx = music_idx = None
    if orig_audio and orig_audio.is_file():
        orig_idx = n
        inputs += ["-i", str(orig_audio)]
        n += 1
    if use_music:
        music_idx = n
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]
        n += 1

    fc = [f"[0:v]{vf},format=yuv420p[vout]" if vf else "[0:v]format=yuv420p[vout]"]
    # Voice
    fc.append(f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.0,atrim=0:{out_dur:.3f},asetpts=PTS-STARTPTS[vo]")
    mix_pads = ["[vo]"]
    if orig_idx is not None:
        fc.append(
            f"[{orig_idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"volume={max(0.0, min(0.4, duck)):.3f},atrim=0:{out_dur:.3f},asetpts=PTS-STARTPTS[orig]"
        )
        mix_pads.append("[orig]")
    if music_idx is not None:
        fc.append(
            f"[{music_idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"volume={max(0.0, min(0.3, music_volume)):.3f},atrim=0:{out_dur:.3f},asetpts=PTS-STARTPTS[bed]"
        )
        mix_pads.append("[bed]")
    if len(mix_pads) == 1:
        fc.append("[vo]anull[aout]")
    else:
        fc.append(
            "".join(mix_pads)
            + f"amix=inputs={len(mix_pads)}:duration=first:dropout_transition=0:normalize=0[aout]"
        )

    log(f"Mixing narration, picture and audio → {dest.name}")
    run(
        [
            ffmpeg, "-y", *inputs,
            "-filter_complex", ";".join(fc),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "44100",
            "-movflags", "+faststart",
            "-t", f"{out_dur:.3f}",
            str(dest),
        ]
    )
    if not dest.is_file() or dest.stat().st_size < 2000:
        raise RuntimeError(f"Recap encoder did not produce a valid file: {dest}")
    _ = vid_dur
    return dest


def _render_shot(ffmpeg, source, dest, shot: Shot, width, height, grade_vf, fmt: str) -> None:
    dur = max(0.8, shot.src_end - shot.src_start)
    # Zoom/reframe + grade + layout (no flip, no playback-speed tricks).
    z = max(1.02, min(1.18, shot.zoom))
    # Ken-burns-ish slow punch over the take, then crop to target.
    # For Shorts, fill a 9:16 frame with a blurred copy behind a slightly
    # zoomed, letterboxed (or cropped) picture.
    if fmt == "short":
        # Scale source to cover 1080x1920 after zoom, blur bg + sharp overlay.
        sharp = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"scale=iw*{z}:ih*{z},crop={width}:{height}"
        )
        blur = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma=22,eq=brightness=-0.04:saturation=0.85"
        )
        # Easier single-graph approach: blur-fill like the existing blur reframe,
        # then a slight extra zoom.
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"split[fg][bg];"
            f"[bg]scale={width}:{height},gblur=sigma=20,eq=brightness=-0.05[bg2];"
            f"[fg]scale=iw*{z}:ih*{z},crop=iw/{z}:ih/{z}:(iw-iw/{z})/2:(ih-ih/{z})/2[fg2];"
            # Actually pad already made it full frame. Simpler:
        )
        # Reset to a reliable graph (split after pad is messy with commas vs filter_complex).
        # Use a single crop/zoom on a blurred-background compose via -filter_complex in the command.
        vf = _shorts_vf(width, height, z, grade_vf)
        args = [
            ffmpeg, "-y",
            "-ss", f"{shot.src_start:.3f}", "-t", f"{dur:.3f}",
            "-i", str(source),
            "-filter_complex", vf,
            "-map", "[v]",
            "-an",
            "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            str(dest),
        ]
        run(args)
        return

    parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        f"scale=iw*{z:.3f}:ih*{z:.3f}",
        f"crop={width}:{height}",
    ]
    if grade_vf:
        parts.append(grade_vf)
    parts.append("fps=30")
    parts.append("format=yuv420p")
    vf = ",".join(parts)
    run(
        [
            ffmpeg, "-y",
            "-ss", f"{shot.src_start:.3f}", "-t", f"{dur:.3f}",
            "-i", str(source),
            "-vf", vf,
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            str(dest),
        ]
    )


def _shorts_vf(width: int, height: int, zoom: float, grade_vf: str) -> str:
    grade = f",{grade_vf}" if grade_vf else ""
    # Background: scale-cover + blur. Foreground: fit width, slight zoom, overlay centered.
    return (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma=22,eq=brightness=-0.06:saturation=0.8{grade}[bg];"
        f"[0:v]scale={width}:-2:force_original_aspect_ratio=decrease,"
        f"scale=iw*{zoom:.3f}:ih*{zoom:.3f},"
        f"setsar=1{grade}[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v]"
    )


def _cut_original_audio(ffmpeg, source: Path, shots: list[Shot], work: Path) -> Path | None:
    # Extract each shot's audio, speed-match, concat. Silence if a pull fails.
    parts = []
    list_path = work / "audio_concat.txt"
    for i, shot in enumerate(shots):
        dest = work / f"audio-{i:04d}.wav"
        dur = max(0.2, shot.src_end - shot.src_start)
        try:
            run(
                [
                    ffmpeg, "-y",
                    "-ss", f"{shot.src_start:.3f}", "-t", f"{dur:.3f}",
                    "-i", str(source),
                    "-vn",
                    "-af", "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo",
                    "-c:a", "pcm_s16le",
                    str(dest),
                ]
            )
            if dest.is_file() and dest.stat().st_size > 100:
                parts.append(dest)
                continue
        except Exception:
            pass
        # Silent pad of the expected output duration.
        silence = max(0.2, dur)
        run(
            [
                ffmpeg, "-y",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
                "-t", f"{silence:.3f}",
                "-c:a", "pcm_s16le",
                str(dest),
            ]
        )
        parts.append(dest)
    if not parts:
        return None
    list_path.write_text(
        "\n".join(f"file '{p.resolve().as_posix().replace(chr(39), r"'\''")}'" for p in parts) + "\n",
        encoding="utf-8",
    )
    mixed = work / "original_cut.wav"
    run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c:a", "pcm_s16le", str(mixed),
        ]
    )
    return mixed if mixed.is_file() else None
