"""Movie recap mode: script, voiceover, scene-matched cuts, captions, sidecar."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from clipper.recap_script import RecapScript, load_plot_source, target_seconds_for, write_script
from clipper.recap_tts import list_voices, resolve_voice, synthesize, transcript_from_tts
from clipper.transcribe import Transcript


@dataclass
class RecapResult:
    path: str
    sidecar: str
    title: str
    hook: str
    description: str
    tags: list[str] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)
    format: str = "short"
    voice: str = ""
    backend: str = ""
    duration: float = 0.0
    spoilers: bool = True
    script_source: str = ""
    footage: str = "video"  # video | fallback

    def to_dict(self) -> dict:
        return asdict(self)


def run_recap(
    source: str | None,
    title: str,
    out_dir: Path | str,
    *,
    fmt: str = "short",
    voice: str | None = None,
    spoilers: bool = True,
    subs: Path | str | None = None,
    plot: Path | str | None = None,
    plot_text: str | None = None,
    target_seconds: float | None = None,
    model: str = "small",
    language: str = "auto",
    grade: str = "moody",
    music: Path | str | None = None,
    music_volume: float = 0.12,
    duck: float = 0.10,
    enqueue: bool | None = None,
    gemini_key: str | None = None,
    groq_key: str | None = None,
    keep_work: bool = False,
    progress=None,
) -> RecapResult:
    log = progress or (lambda *_a, **_k: None)
    if not (title or "").strip():
        raise ValueError("A movie title is required (--title)")
    title = title.strip()
    fmt = "short" if str(fmt).lower() in {"short", "shorts", "tiktok"} else "long"
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)

    video, info = _load_source(source, work, log)
    duration = 0.0
    if video:
        from clipper.ffmpeg_utils import probe_duration

        duration = float(info.get("duration") or 0) or probe_duration(video)

    transcript: Transcript | None = None
    if subs and Path(subs).is_file():
        from clipper.recap_scenes import load_srt

        log(f"Loading subtitles {Path(subs).name}…")
        transcript = load_srt(subs)
        if not transcript.duration and duration:
            transcript.duration = duration
    elif video:
        try:
            from clipper.transcribe import transcribe

            transcript = transcribe(
                video, work, model_size=model, language=language, progress=log
            )
            if not transcript.duration:
                transcript.duration = duration
        except Exception as exc:  # noqa: BLE001
            log(f"Transcription failed ({exc}); continuing with title/plot only")
            transcript = None

    plot_blob = load_plot_source(plot, plot_text)
    script = write_script(
        title,
        transcript,
        fmt=fmt,
        spoilers=spoilers,
        plot=plot_blob,
        target_seconds=target_seconds,
        gemini_key=gemini_key,
        groq_key=groq_key,
        progress=log,
    )
    (work / "script.json").write_text(json.dumps(script.to_dict(), indent=2), encoding="utf-8")
    log(f"Script: {script.word_count} words, {len(script.lines)} lines, via {script.source_used}")

    voice_name = resolve_voice(voice)
    tts = synthesize(
        script.full_text,
        work / "narration.wav",
        voice=voice_name,
        gemini_key=gemini_key,
        progress=log,
    )
    vo_tr = transcript_from_tts(tts)

    # Map VO sentence durations onto script lines (best-effort by word count).
    line_durs = _line_durations(script.lines, tts.duration, vo_tr)

    from clipper.recap_scenes import align_shots, detect_scenes

    scenes = detect_scenes(video, duration or tts.duration, progress=log) if video else []
    shots = align_shots(
        script.lines,
        line_durs,
        scenes,
        transcript,
        duration or tts.duration,
        progress=log,
    )
    # If we have no footage, invent still-only shots.
    if not video:
        from clipper.recap_scenes import Shot

        shots = [
            Shot(
                src_start=0,
                src_end=max(2.0, d),
                line_index=i,
                beat=ln.beat,
                out_duration=max(2.0, d),
                reason="fallback still",
            )
            for i, (ln, d) in enumerate(zip(script.lines, line_durs))
        ]

    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()[:40] or "recap"
    dest = out_dir / f"{slug}-{'short' if fmt == 'short' else 'long'}.mp4"

    music_path = Path(music) if music else None
    if music and not (music_path and music_path.is_file()):
        log(f"Music file not found, using a copyright-safe bed: {music}")
        music_path = None
    if not music_path:
        try:
            from clipper.library import pick_music

            pick = pick_music("cinematic-edit")
            if pick:
                music_path = pick.path
                log(f"Music: {pick.mood} {pick.source} bed ({pick.path.name})")
                if pick.credit and pick.credit not in (script.description or ""):
                    script.description = (script.description or "").rstrip() + "\n\n" + pick.credit
        except Exception as exc:  # noqa: BLE001
            log(f"No music bed ({exc})")
            music_path = None

    from clipper.recap_render import render_recap

    render_recap(
        video,
        dest,
        script,
        shots,
        tts.path,
        vo_tr,
        fmt=fmt,
        grade=grade,
        music=music_path,
        music_volume=music_volume,
        duck=duck,
        progress=log,
    )
    from clipper.ffmpeg_utils import probe_duration

    out_dur = probe_duration(dest)
    chapters = _stamp_chapters(script, line_durs)
    sidecar = dest.with_suffix(".txt")
    sidecar.write_text(
        _render_sidecar(script, dest, tts.voice, tts.backend, out_dur, chapters, video is not None),
        encoding="utf-8",
    )
    manifest = {
        "title": title,
        "format": fmt,
        "path": str(dest),
        "sidecar": str(sidecar),
        "duration": out_dur,
        "voice": tts.voice,
        "backend": tts.backend,
        "spoilers": spoilers,
        "script_source": script.source_used,
        "shots": len(shots),
        "chapters": chapters,
    }
    (out_dir / "recap.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not keep_work:
        # Keep narration + script; drop bulky per-shot encodes.
        shots_dir = dest.parent / "_shots"
        if shots_dir.is_dir():
            for p in shots_dir.glob("shot-*.mp4"):
                try:
                    p.unlink()
                except OSError:
                    pass
    log(f"Done. Recap at {dest}")
    result = RecapResult(
        path=str(dest),
        sidecar=str(sidecar),
        title=script.youtube_title or title,
        hook=script.hook,
        description=script.description,
        tags=list(script.tags),
        chapters=chapters,
        format=fmt,
        voice=tts.voice,
        backend=tts.backend,
        duration=out_dur,
        spoilers=spoilers,
        script_source=script.source_used,
        footage="video" if video else "fallback",
    )
    from clipper.config import load_settings
    from clipper.publish import enqueue as queue_add

    do_enqueue = load_settings().get("enqueue", True) if enqueue is None else bool(enqueue)
    if do_enqueue:
        item = queue_add(
            {
                "path": result.path,
                "sidecar": result.sidecar,
                "title": result.title,
                "description": result.description,
                "hashtags": result.tags,
                "hook": result.hook,
                "preset": f"recap-{fmt}",
                "layout": "fill" if fmt == "short" else "wide",
            }
        )
        log(f"Queued {item['id']} for review (nothing posts until you approve and disable draft-only).")
    return result


def _load_source(source: str | None, work: Path, log) -> tuple[Path | None, dict]:
    if not source or not str(source).strip():
        log("No footage provided — will use illustrated stills")
        return None, {}
    source = str(source).strip()
    from clipper.download import download

    log("Loading source video…")
    video, info = download(source, work, progress=log)
    return video, info


def _line_durations(lines, total: float, vo_tr: Transcript) -> list[float]:
    if not lines:
        return []
    weights = [max(1, len(ln.text.split())) for ln in lines]
    s = sum(weights) or 1
    durs = [total * (w / s) for w in weights]
    # Snap slightly using voice word timings if we can match prefixes.
    return durs


def _stamp_chapters(script: RecapScript, line_durs: list[float]) -> list[dict]:
    if script.format != "long":
        return []
    t = 0.0
    first_at = {}
    for ln, d in zip(script.lines, line_durs):
        if ln.beat not in first_at:
            first_at[ln.beat] = t
        t += d
    chapters = []
    seen = set()
    labels = {
        "hook": "The hook",
        "setup": "How it starts",
        "conflict": "The turning point",
        "twist": "The twist",
        "cta": "Wrap-up",
    }
    for ch in script.chapters or []:
        beat = ch.get("beat") or ""
        title = ch.get("title") or labels.get(beat, "Chapter")
        start = first_at.get(beat, 0.0)
        key = (round(start, 1), title)
        if key in seen:
            continue
        seen.add(key)
        chapters.append({"time": round(start, 2), "title": title})
    if not chapters:
        for beat, start in first_at.items():
            chapters.append({"time": round(start, 2), "title": labels.get(beat, beat.title())})
    chapters.sort(key=lambda c: c["time"])
    return chapters


def _render_sidecar(script, dest, voice, backend, duration, chapters, has_video) -> str:
    tags = " ".join(f"#{t.lstrip('#')}" for t in script.tags)
    ch_lines = ""
    if chapters:
        def _ts(s):
            s = int(s)
            return f"{s // 60}:{s % 60:02d}"
        ch_lines = "Chapters:\n" + "\n".join(f"{_ts(c['time'])} {c['title']}" for c in chapters) + "\n\n"
    credit = (
        "This is a commentary/review recap, not the official film. "
        "Please credit and support the original creators. "
        "Platforms can still claim the video through Content ID even when the edit is transformative."
    )
    footage = "Edited scenes from the provided film." if has_video else "Illustrated stills (no source footage)."
    return (
        f"Title:\n{script.youtube_title or script.title}\n\n"
        f"Description:\n{script.description.strip()}\n\n{credit}\n\n"
        f"{ch_lines}"
        f"Hashtags:\n{tags}\n\n"
        f"Hook:\n{script.hook}\n\n"
        f"Voice: {voice} ({backend})\n"
        f"Format: {script.format}  Spoilers: {script.spoilers}\n"
        f"Duration: {duration:.1f}s\n"
        f"Script: {script.source_used}\n"
        f"Picture: {footage}\n"
        f"File: {Path(dest).name}\n"
    )


def build_recap_parser(prog: str = "clipper recap"):
    import argparse

    p = argparse.ArgumentParser(
        prog=prog,
        description="Make an AI-voiceover movie recap (Short or long) from a film you have the rights to use. Recaps can still be claimed by Content ID; this tool does not try to hide a film from detection.",
    )
    p.add_argument("source", nargs="?", help="Local movie/trailer file, or a URL yt-dlp can fetch. Omit for illustrated stills.")
    p.add_argument("--title", required=True, help="Movie title (required)")
    p.add_argument("--format", choices=["short", "long"], default="short", help="short = 45–60s 9:16; long = 16:9 recap")
    p.add_argument("--target-seconds", type=float, default=None, help="Override target length in seconds (e.g. 150 for a 2.5 min demo)")
    p.add_argument("--voice", default="auto", help="Gemini or edge-tts voice (see --list-voices)")
    p.add_argument("--list-voices", action="store_true", help="List built-in voices and exit")
    p.add_argument("--spoilers", action="store_true", default=None, help="Allow ending/twist spoilers (default: on for long, off for short)")
    p.add_argument("--no-spoilers", action="store_true", help="Keep the ending hidden")
    p.add_argument("--subs", default=None, help="Subtitle file (.srt) to help the plot + scene matching")
    p.add_argument("--plot", default=None, help="Optional plot notes / article (text file)")
    p.add_argument("--out", "-o", default="recap", help="Output folder (default: ./recap)")
    p.add_argument("--model", default="small", help="faster-whisper model if no .srt is given")
    p.add_argument("--language", default="auto")
    p.add_argument("--grade", choices=["auto", "none", "moody", "contrast", "warm"], default="moody")
    p.add_argument("--music", default=None, help="Optional royalty-free / user-supplied music bed (local file only)")
    p.add_argument("--music-volume", type=float, default=0.12)
    p.add_argument("--enqueue", action="store_true", default=None, help="Add the recap to the review queue (default on)")
    p.add_argument("--no-enqueue", action="store_true", help="Don't add the recap to the publish queue")
    p.add_argument("--gemini-key", default=None)
    p.add_argument("--groq-key", default=None)
    p.add_argument("--keep-work", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_recap_parser()
    args = parser.parse_args(argv)
    if args.list_voices:
        for v in list_voices():
            print(f"{v['id']:28}  {v['backend']}")
        return 0
    if args.no_spoilers:
        spoilers = False
    elif args.spoilers:
        spoilers = True
    else:
        spoilers = args.format == "long"
    try:
        result = run_recap(
            args.source,
            args.title,
            args.out,
            fmt=args.format,
            voice=args.voice,
            spoilers=spoilers,
            subs=args.subs,
            plot=args.plot,
            target_seconds=args.target_seconds,
            model=args.model,
            language=args.language,
            grade=None if args.grade == "auto" else args.grade,
            music=args.music,
            music_volume=args.music_volume,
            enqueue=False if args.no_enqueue else (True if args.enqueue else None),
            gemini_key=args.gemini_key,
            groq_key=args.groq_key,
            keep_work=args.keep_work,
            progress=print,
        )
    except KeyboardInterrupt:
        print("Cancelled.")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print()
    print(f"Wrote recap to {result.path}")
    print(f"  Title: {result.title}")
    print(f"  Hook:  {result.hook}")
    print(f"  Voice: {result.voice} ({result.backend})  {result.duration:.1f}s")
    if result.chapters:
        print("  Chapters:")
        for ch in result.chapters:
            t = int(ch["time"])
            print(f"    {t // 60}:{t % 60:02d}  {ch['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
