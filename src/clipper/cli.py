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
            "with captions, a hook, and suggested titles."
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
        default="tiny",
        help="faster-whisper model: tiny (default, free & fast), base, small, medium, large-v3",
    )
    parser.add_argument("--hook", default=None, help="Optional hook text shown at the top of every clip")
    parser.add_argument(
        "--style",
        choices=["auto", "face", "center", "blur"],
        default="auto",
        help="Vertical reframing: auto (default), face, center crop, or blurred background",
    )
    parser.add_argument("--min-duration", type=float, default=15.0, help="Minimum clip length in seconds")
    parser.add_argument("--max-duration", type=float, default=60.0, help="Maximum clip length in seconds")
    parser.add_argument("--no-captions", action="store_true", help="Skip burned-in captions")
    parser.add_argument("--gemini-key", default=None, help="Optional Gemini API key (free tier)")
    parser.add_argument("--groq-key", default=None, help="Optional Groq API key (free tier)")
    parser.add_argument("--keep-work", action="store_true", help="Keep intermediate audio/source files")
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
    print(f"heuristic: {len(moments)} moment(s) ok")
    print("OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
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
        results = run_pipeline(
            args.source,
            args.out,
            count=args.count,
            model=args.model,
            hook=args.hook,
            style=args.style,
            min_dur=args.min_duration,
            max_dur=args.max_duration,
            captions=not args.no_captions,
            gemini_key=args.gemini_key,
            groq_key=args.groq_key,
            keep_work=args.keep_work,
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
        if tags:
            print(f"     {tags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
