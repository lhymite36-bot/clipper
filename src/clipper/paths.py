"""User-data locations for config, queue, music and model caches."""

from __future__ import annotations

import os
from pathlib import Path


def user_data_dir() -> Path:
    override = os.environ.get("CLIPPER_HOME") or os.environ.get("CLIPPER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "Clipper"
    return Path.home() / ".config" / "clipper"


def env_paths() -> list[Path]:
    """Places we may load a .env from. First existing file wins for override=False."""
    paths = [Path.cwd() / ".env", user_data_dir() / ".env"]
    return paths


def default_music_dir() -> Path:
    return user_data_dir() / "music"


def default_sounds_dir() -> Path:
    return user_data_dir() / "sounds"


def queue_path() -> Path:
    return user_data_dir() / "queue.json"


def settings_path() -> Path:
    return user_data_dir() / "settings.json"
