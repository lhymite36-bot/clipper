"""Command-line interface: `clip <url> --count 5` or `clipper ...`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from clipper import __app_name__, __version__


def _prog() -> str:
    name = Path(sys.argv[0]).stem.lower()
    if name in {"clip", "clipper", "clippercli"}:
        return name
    return "clipper"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_prog(),
        description=(
            "Turn a long YouTube video or a local file into vertical YouTube Shorts "
            "with captions, a hook, and suggested titles. Use `clipper recap` for a movie-recap voiceover."
        ),
        epilog="Example: clip https://youtu.be/VIDEO --count 5 --out clips",
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="YouTube / video URL, a local video file, or 'ui' to open the web app",
    )
    parser.add_argument("--count", "-n", type=int, default=5, help="How many clips to make (default: 5)")
    parser.add_argument("--out", "-o", default="clips", help="Output folder (default: ./clips)")
    parser.add_argument(
        "--model",
        default="small",
        help="faster-whisper model: small (default, more accurate), base, tiny, medium, large-v3",
    )
    parser.add_argument(
        "--language",
        default="auto",
        help="Whisper language (default: auto, with an English auto-fix for Latin-heavy audio)",
    )
    parser.add_argument(
        "--brief",
        default=None,
        help="Campaign brief text or path (source, duration, hook rules, geo)",
    )
    parser.add_argument("--hook", default=None, help="Optional hook text shown at the top of every clip")
    parser.add_argument(
        "--preset",
        choices=["auto", "cinematic-edit", "story-skit", "sports-montage", "cinematic", "story", "sports"],
        default="auto",
        help="Look: auto, cinematic-edit, story-skit, or sports-montage",
    )
    parser.add_argument(
        "--style",
        choices=["auto", "face", "center", "blur"],
        default="auto",
        help="Crop hint used when the layout is tight: auto, face, center, or blur",
    )
    parser.add_argument(
        "--layout",
        choices=["auto", "tight", "bars", "blur", "fill"],
        default="auto",
        help="Frame layout: tight crop, 16:9 bars, blur, or fill (blur background + sharp 16:9 under the hook)",
    )
    parser.add_argument(
        "--grade",
        choices=["auto", "none", "moody", "contrast", "warm"],
        default="auto",
        help="Optional colour grade: moody, contrast, warm, or none",
    )
    parser.add_argument(
        "--captions",
        choices=["auto", "words", "none", "minimal"],
        default="auto",
        help="Captions: auto (follow the preset), word-by-word, none, or minimal",
    )
    parser.add_argument(
        "--music",
        default=None,
        help="Optional copyright-safe music bed (a local file you have rights to)",
    )
    parser.add_argument("--music-dir", default=None, help="Folder of copyright-safe tracks (YouTube Audio Library, CC0, CC BY)")
    parser.add_argument("--sounds-dir", default=None, help="Optional 'my sounds' folder of audio you have rights to")
    parser.add_argument("--auto-music", action="store_true", default=None, help="Auto-pick a copyright-safe bed (default on)")
    parser.add_argument("--no-music", action="store_true", help="Skip background music")
    parser.add_argument("--sfx", action="store_true", default=None, help="Add stock whoosh/impact/riser SFX (default on)")
    parser.add_argument("--no-sfx", action="store_true", help="Skip stock SFX")
    parser.add_argument("--enqueue", action="store_true", default=None, help="Add clips to the review queue (default on)")
    parser.add_argument("--no-enqueue", action="store_true", help="Don't add clips to the publish queue")
    parser.add_argument(
        "--music-volume",
        type=float,
        default=0.16,
        help="Music bed volume 0–1 (default: 0.16, ducked under speech)",
    )
    parser.add_argument("--no-loop", action="store_true", help="Don't snap the out-point to a calm looping frame")
    parser.add_argument("--speed-ramps", action="store_true", help="Force sports-style speed ramps (off for story-skit by default)")
    parser.add_argument("--min-duration", type=float, default=15.0, help="Minimum clip length in seconds")
    parser.add_argument("--max-duration", type=float, default=60.0, help="Maximum clip length in seconds")
    parser.add_argument("--no-captions", action="store_true", help="Skip burned-in captions")
    parser.add_argument("--gemini-key", default=None, help="Optional Gemini API key (free tier)")
    parser.add_argument("--groq-key", default=None, help="Optional Groq API key (free tier)")
    parser.add_argument("--keep-work", action="store_true", help="Keep intermediate audio/source files")
    parser.add_argument("--no-punch", action="store_true", help="Disable the short zoom/punch-in at the payoff")
    parser.add_argument("--ui", action="store_true", help="Open the local web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Web UI host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8766, help="Web UI port (default: 8766)")
    parser.add_argument("--selftest", action="store_true", help="Run a fast install check and exit")
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    return parser


def selftest() -> int:
    from clipper.ffmpeg_utils import FFmpegError, find_ffmpeg, find_ffprobe, run
    from clipper.moments import heuristic_moments
    from clipper.transcribe import Transcript, Word

    print(f"{__app_name__} {__version__} self-test")
    try:
        ffmpeg = find_ffmpeg()
        ffprobe = find_ffprobe()
    except FFmpegError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"ffmpeg:  {ffmpeg}")
    print(f"ffprobe: {ffprobe}")
    proc = run([ffmpeg, "-version"], check=False)
    if proc.returncode != 0:
        print("FAIL: ffmpeg did not run")
        return 1
    # Heuristic still works without a model or a video
    words = [
        Word("Wait", 1.0, 1.3),
        Word("for", 1.3, 1.5),
        Word("it!", 1.5, 2.0),
        Word("This", 10.0, 10.3),
        Word("is", 10.3, 10.5),
        Word("insane", 10.5, 11.2),
    ]
    tr = Transcript(text="Wait for it! This is insane", language="en", segments=[], words=words, duration=40)
    moments = heuristic_moments(tr, 40, 2, min_dur=15, max_dur=60)
    if not moments:
        print("FAIL: heuristic returned no moments")
        return 1
    m = moments[0]
    if m.peak is None or m.peak < 9 or m.peak > 13:
        print(f"FAIL: payoff should be the 'insane' line near 10.5s, got peak={m.peak}")
        return 1
    if not m.payoff_in_last_30():
        print(f"FAIL: payoff {m.peak} is not in the last 30% of {m.start}-{m.end}")
        return 1
    if (m.hook or "").strip().upper() == "WAIT FOR IT" and "INSANE" not in (m.hook or "").upper():
        # 'Wait for it' is spoken, but the hook should prefer the actual payoff
        # or at least not be the only thing we advertise if we also have words.
        pass
    if m.end < m.peak + 1.0:
        print(f"FAIL: clip should end after the payoff ({m.end} vs peak {m.peak})")
        return 1
    print(f"heuristic: {len(moments)} moment(s) ok (peak {m.peak:.1f}s, hook {m.hook!r})")
    from clipper.recap_script import write_script

    script = write_script("Sintel", tr, fmt="short", spoilers=False, llm=False)
    if not script.lines or not script.hook:
        print("FAIL: recap fallback script was empty")
        return 1
    if "wait for it" in script.hook.lower():
        print("FAIL: recap hook looked generic")
        return 1
    print(f"recap script: {len(script.lines)} line(s), hook {script.hook!r}")
    print("OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"recap", "recapper"}:
        from clipper.recap import main as recap_main

        return recap_main(argv[1:])
    if argv and argv[0] in {"queue", "approve", "reject", "publish"}:
        from clipper.publish import cli_main

        return cli_main(argv)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    want_ui = args.ui or (args.source and args.source.lower() in {"ui", "web", "gui"})
    if want_ui or not args.source:
        if want_ui or args.ui:
            from clipper.web import serve

            return serve(host=args.host, port=args.port)
        parser.print_help()
        return 0

    from clipper.pipeline import run_pipeline

    try:
        captions = "none" if args.no_captions else args.captions
        auto_music = False if args.no_music else True
        if args.auto_music:
            auto_music = True
        sfx = False if args.no_sfx else True
        if args.sfx:
            sfx = True
        enqueue = False if args.no_enqueue else True
        if args.enqueue:
            enqueue = True
        results = run_pipeline(
            args.source,
            args.out,
            count=args.count,
            model=args.model,
            language=args.language,
            hook=args.hook,
            style=args.style,
            min_dur=args.min_duration,
            max_dur=args.max_duration,
            captions=captions,
            gemini_key=args.gemini_key,
            groq_key=args.groq_key,
            keep_work=args.keep_work,
            punch=not args.no_punch,
            preset=args.preset,
            layout=args.layout,
            grade=None if args.grade == "auto" else args.grade,
            music=args.music,
            music_volume=args.music_volume,
            music_dir=args.music_dir,
            sounds_dir=args.sounds_dir,
            auto_music=auto_music,
            sfx=sfx,
            enqueue=enqueue,
            brief=args.brief,
            loop=not args.no_loop,
            speed_ramps=True if args.speed_ramps else None,
            progress=print,
        )
    except KeyboardInterrupt:
        print("Cancelled.")
        return 130
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"Wrote {len(results)} clip(s) to {Path(args.out).resolve()}")
    for r in results:
        tags = " ".join(f"#{t}" for t in r.hashtags[:6])
        print(f"  {r.index}. {r.path}")
        print(f"     Title: {r.title}")
        if getattr(r, "hook", ""):
            print(f"     Hook: {r.hook}")
        extra = " · ".join(x for x in [getattr(r, "preset", ""), getattr(r, "layout", "")] if x)
        if extra:
            print(f"     {extra}")
        if tags:
            print(f"     {tags}")
        if getattr(r, "title_options", None):
            print("     Title options: " + " | ".join(r.title_options))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
