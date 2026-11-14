#!/usr/bin/env python3
"""Render a 9:16 sample through the Kotlin (Android) pipeline on the desktop JVM."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "samples" / "android"
WORK = Path("/tmp/clipper-android-sample")


def find_source() -> Path:
    candidates = [
        Path("/tmp/clipper-v2/aib.webm"),
        Path("/tmp/clipper-v2/aib.mp4"),
        Path("/tmp/aib.webm"),
    ]
    for c in candidates:
        if c.is_file() and c.stat().st_size > 1000:
            return c
    raise SystemExit("No AIB source video found under /tmp/clipper-v2. Download the CC BY 3.0 video first.")


def load_or_build_transcript(source: Path) -> Path:
    # Reuse a desktop sidecar if present; otherwise a short fixture is not enough
    # for a real hook. Prefer existing v3 transcript-like files.
    for p in [
        ROOT / "samples" / "v3" / "transcript.json",
        Path("/tmp/clipper-v2/transcript.json"),
        WORK / "transcript.json",
    ]:
        if p.is_file():
            return p
    # Build a minimal word-level transcript from a text sidecar if we have one
    return Path("/nonexistent")


def main() -> int:
    source = find_source()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fonts = ROOT / "src" / "clipper" / "data"
    env = os.environ.copy()
    env["JAVA_HOME"] = env.get("JAVA_HOME") or "/home/box/jdk17"
    env["PATH"] = env["JAVA_HOME"] + "/bin:" + env.get("PATH", "")
    cmd = [
        str(ROOT / "android" / "gradlew"),
        "--no-daemon",
        "-p", str(ROOT / "android"),
        ":pipeline:runSample",
        f"-PsampleSource={source}",
        f"-PsampleOut={OUT_DIR / '01-android-pipeline.mp4'}",
        f"-PsampleFonts={fonts}",
        f"-PsampleWork={WORK}",
    ]
    # Optional transcript
    for p in [
        ROOT / "samples" / "v3" / "transcript.json",
        Path("/tmp/clipper-v2/transcript.json"),
    ]:
        if p.is_file():
            cmd.append(f"-PsampleTranscript={p}")
            break
    print("Running", " ".join(cmd), flush=True)
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
