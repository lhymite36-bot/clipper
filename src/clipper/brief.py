"""Campaign-brief mode: paste a clipping-program brief and apply its rules."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


GEO_ALIASES = {
    "us": "US", "usa": "US", "united states": "US", "america": "US",
    "uk": "UK", "united kingdom": "UK", "britain": "UK", "gb": "UK",
    "ca": "CA", "canada": "CA",
    "au": "AU", "australia": "AU",
    "in": "IN", "india": "IN",
    "eu": "EU", "europe": "EU",
    "worldwide": "worldwide", "global": "worldwide", "all": "worldwide",
}


@dataclass
class CampaignBrief:
    source: str = ""
    count: int | None = None
    min_duration: float | None = None
    max_duration: float | None = None
    hook_rules: str = ""
    geo: list[str] = field(default_factory=list)
    language: str = ""
    preset: str = ""
    captions: str = ""
    music: bool | None = None
    title: str = ""
    raw: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _kv_lines(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
        val = val.strip().strip("\"'")
        if key and val:
            out[key] = val
    return out


def _parse_geo(text: str) -> list[str]:
    found: list[str] = []
    blob = (text or "").lower()
    # Comma/slash lists of country codes
    for tok in re.split(r"[,/|&]| and ", blob):
        tok = tok.strip()
        if tok in GEO_ALIASES:
            code = GEO_ALIASES[tok]
            if code not in found:
                found.append(code)
    # "geo: US, UK, CA" already handled via tokens
    if re.search(r"\b(united states|u\.s\.a?|usa)\b", blob) and "US" not in found:
        found.append("US")
    return found


def _parse_duration_pair(text: str) -> tuple[float | None, float | None]:
    mins = maxs = None
    # 15-30s, 15–30 seconds, 15 to 30 sec
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–to]+\s*(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)?", text, re.I)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return (min(a, b), max(a, b))
    m = re.search(r"(?:min(?:imum)?|at least)\s*(?:duration\s*)?(?:of\s*)?(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?", text, re.I)
    if m:
        mins = float(m.group(1))
    m = re.search(r"(?:max(?:imum)?|no longer than|up to)\s*(?:duration\s*)?(?:of\s*)?(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?", text, re.I)
    if m:
        maxs = float(m.group(1))
    return mins, maxs


def parse_brief(text: str) -> CampaignBrief:
    """Parse a free-text or simple key: value campaign brief."""
    raw = (text or "").strip()
    brief = CampaignBrief(raw=raw)
    if not raw:
        return brief

    # JSON object
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                brief.source = str(data.get("source") or data.get("url") or "")
                if data.get("count") is not None:
                    brief.count = int(data["count"])
                if data.get("min_duration") is not None:
                    brief.min_duration = float(data["min_duration"])
                if data.get("max_duration") is not None:
                    brief.max_duration = float(data["max_duration"])
                brief.hook_rules = str(data.get("hook_rules") or data.get("hook") or "")
                geo = data.get("geo") or data.get("regions") or []
                if isinstance(geo, str):
                    brief.geo = _parse_geo(geo)
                elif isinstance(geo, list):
                    brief.geo = _parse_geo(", ".join(str(x) for x in geo))
                brief.language = str(data.get("language") or "")
                brief.preset = str(data.get("preset") or "")
                brief.captions = str(data.get("captions") or "")
                if "music" in data:
                    brief.music = bool(data["music"])
                brief.title = str(data.get("title") or "")
                return brief
        except json.JSONDecodeError:
            pass

    kv = _kv_lines(raw)
    url = re.search(r"https?://[^\s\]\)\"']+", raw)
    brief.source = kv.get("source") or kv.get("url") or kv.get("video") or (url.group(0) if url else "")
    if kv.get("count") or kv.get("clips"):
        try:
            brief.count = int(re.search(r"\d+", kv.get("count") or kv.get("clips") or "").group(0))
        except (AttributeError, ValueError):
            pass
    dmin, dmax = _parse_duration_pair(raw)
    if kv.get("min_duration") or kv.get("min"):
        try:
            brief.min_duration = float(re.search(r"[\d.]+", kv.get("min_duration") or kv.get("min") or "").group(0))
        except (AttributeError, ValueError):
            brief.min_duration = dmin
    else:
        brief.min_duration = dmin
    if kv.get("max_duration") or kv.get("max"):
        try:
            brief.max_duration = float(re.search(r"[\d.]+", kv.get("max_duration") or kv.get("max") or "").group(0))
        except (AttributeError, ValueError):
            brief.max_duration = dmax
    else:
        brief.max_duration = dmax
    brief.hook_rules = kv.get("hook_rules") or kv.get("hook") or kv.get("hooks") or ""
    if not brief.hook_rules:
        # Pull a "hook:" paragraph or a sentence mentioning hooks.
        m = re.search(r"hook[s]?\s*(?:rules?|must|should)?[:\-]\s*(.+)", raw, re.I)
        if m:
            brief.hook_rules = m.group(1).strip().split("\n")[0][:240]
    brief.geo = _parse_geo(kv.get("geo") or kv.get("regions") or kv.get("territory") or raw)
    brief.language = (kv.get("language") or kv.get("lang") or "").lower()
    brief.preset = kv.get("preset") or kv.get("style") or ""
    brief.captions = kv.get("captions") or ""
    if "music" in kv:
        brief.music = kv["music"].lower() not in {"no", "false", "0", "off", "none"}
    brief.title = kv.get("title") or kv.get("campaign") or ""
    return brief


def load_brief(path_or_text: str | Path) -> CampaignBrief:
    p = Path(str(path_or_text))
    if p.is_file():
        return parse_brief(p.read_text(encoding="utf-8"))
    return parse_brief(str(path_or_text))
