"""Load and save Clipper settings. Secrets live in the environment / .env, never in settings.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from clipper.paths import env_paths, settings_path, user_data_dir

# Keys that must never be written to settings.json or printed in logs.
SECRET_ENV = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "BUFFER_API_KEY",
    "CLIPPER_GITHUB_TOKEN",
    "GITHUB_TOKEN",
    "PIXABAY_API_KEY",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
    "YOUTUBE_ACCESS_TOKEN",
)

DEFAULTS: dict[str, Any] = {
    "model": "small",
    "language": "auto",
    "draft_only": True,
    "autopilot": False,
    "publish_method": "buffer",  # buffer | youtube
    "schedule_times": ["18:00", "19:30", "21:00"],
    "per_day": 3,
    "github_repo": "",
    "buffer_channel_id": "",
    "buffer_organization_id": "",
    "youtube_privacy": "private",
    "auto_music": True,
    "sfx": True,
    "enqueue": True,
}


def load_dotenv_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)
    for path in env_paths():
        if path.is_file():
            load_dotenv(path, override=False)


def secret(name: str) -> str:
    """Read a secret from the environment. Never logs the value."""
    load_dotenv_files()
    return (os.environ.get(name) or "").strip()


def redact(text: str) -> str:
    """Strip any known secret values from a string before logging."""
    out = text or ""
    for name in SECRET_ENV:
        val = (os.environ.get(name) or "").strip()
        if val and len(val) >= 4:
            out = out.replace(val, f"[{name}_REDACTED]")
    return out


def load_settings() -> dict[str, Any]:
    load_dotenv_files()
    data = dict(DEFAULTS)
    path = settings_path()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in SECRET_ENV or str(k).lower().endswith(("_key", "_token", "_secret")):
                        continue
                    data[k] = v
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    for k, v in updates.items():
        if k in SECRET_ENV or str(k).lower().endswith(("_key", "_token", "_secret")):
            continue
        current[k] = v
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def public_settings() -> dict[str, Any]:
    """Settings safe to send to the UI (no secrets)."""
    data = load_settings()
    data["has_buffer_key"] = bool(secret("BUFFER_API_KEY"))
    data["has_gemini_key"] = bool(secret("GEMINI_API_KEY") or secret("GOOGLE_API_KEY"))
    data["has_groq_key"] = bool(secret("GROQ_API_KEY"))
    data["has_github_token"] = bool(secret("CLIPPER_GITHUB_TOKEN") or secret("GITHUB_TOKEN"))
    data["has_youtube_oauth"] = bool(secret("YOUTUBE_REFRESH_TOKEN") and secret("YOUTUBE_CLIENT_ID"))
    data["config_dir"] = str(user_data_dir())
    return data
