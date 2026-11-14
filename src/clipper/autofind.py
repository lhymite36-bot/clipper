"""Auto-find: Clipper pulls videos by itself from watched sources, search, and trailers.

Watched sources are saved YouTube channels, playlists, and campaign/brief source
links (Content Rewards, Vyro, Clipster, IndClip-style). Keyword/trending search
uses yt-dlp, with an optional Creative Commons-only filter. Movie trailers are
looked up by title for Recap mode.

New items are downloaded, auto-clipped or recapped, and land in the draft-only
review queue. Nothing posts unless Autopilot is on. Already-processed videos are
deduped and a daily cap is enforced.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Callable

from clipper.config import load_settings, save_settings
from clipper.paths import user_data_dir

BRIEF_HOSTS = ("contentrewards", "content-rewards", "vyro", "clipster", "indclip", "brief")


def _store_dir() -> Path:
    d = user_data_dir() / "autofind"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sources_path() -> Path:
    return _store_dir() / "sources.json"


def seen_path() -> Path:
    return _store_dir() / "seen.json"


def cap_path() -> Path:
    return _store_dir() / "daily-cap.json"


def load_sources() -> list[dict[str, Any]]:
    path = sources_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return list(raw) if isinstance(raw, list) else list(raw.get("sources") or [])
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def save_sources(sources: list[dict[str, Any]]) -> None:
    sources_path().write_text(json.dumps(sources, indent=2), encoding="utf-8")


def load_seen() -> set[str]:
    path = seen_path()
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return set(raw if isinstance(raw, list) else raw.get("ids") or [])
    except (OSError, json.JSONDecodeError, TypeError):
        return set()


def mark_seen(ids: list[str]) -> None:
    seen = load_seen()
    seen.update(i for i in ids if i)
    seen_path().write_text(json.dumps(sorted(seen)), encoding="utf-8")


def used_today() -> int:
    path = cap_path()
    if not path.is_file():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    today = date.today().isoformat()
    return int(raw.get("count") or 0) if raw.get("date") == today else 0


def record_used(n: int) -> None:
    today = date.today().isoformat()
    cap_path().write_text(json.dumps({"date": today, "count": used_today() + n}), encoding="utf-8")


def daily_cap() -> int:
    return max(1, int(load_settings().get("autofind_daily_cap") or 8))


def remaining_today() -> int:
    return max(0, daily_cap() - used_today())


def looks_like_brief(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in BRIEF_HOSTS)


def video_id_from_url(url: str) -> str:
    m = re.search(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else ""


def normalize_license(raw: str | None, url: str = "") -> str:
    s = (raw or "").strip()
    if not s or s.lower() == "null":
        return "Creative Commons" if "creative" in (url or "").lower() else "unknown"
    if "creative commons" in s.lower() or s.lower() == "cc":
        return "Creative Commons"
    return s


def add_source(
    kind: str,
    query: str,
    *,
    label: str | None = None,
    cc_only: bool = False,
    recap: bool = False,
    enabled: bool = True,
) -> dict[str, Any]:
    kind = (kind or "keyword").lower().strip()
    if kind not in {"channel", "playlist", "brief", "keyword", "trailer"}:
        raise ValueError(f"Unknown source kind: {kind}")
    item = {
        "id": uuid.uuid4().hex[:8],
        "kind": kind,
        "query": query.strip(),
        "label": (label or query).strip(),
        "cc_only": bool(cc_only),
        "recap": bool(recap) or kind == "trailer",
        "enabled": bool(enabled),
    }
    sources = load_sources()
    sources = [s for s in sources if not (s.get("kind") == item["kind"] and s.get("query") == item["query"])]
    sources.append(item)
    save_sources(sources)
    return item


def remove_source(source_id: str) -> bool:
    sources = load_sources()
    kept = [s for s in sources if s.get("id") != source_id]
    if len(kept) == len(sources):
        return False
    save_sources(kept)
    return True


def ytsearch_query(keyword: str, *, cc_only: bool = False, trending: bool = False) -> str:
    if trending and not (keyword or "").strip():
        return "ytsearch10:trending"
    q = keyword.strip()
    if cc_only:
        q = f"creativecommons {q}".strip()
    return f"ytsearch10:{q}"


def trailer_query(title: str) -> str:
    return f"ytsearch5:{title.strip()} official trailer"


def ytdlp_search_args(query: str, *, cc_only: bool = False, max_items: int = 10) -> list[str]:
    q = query if query.startswith(("ytsearch", "http", "ytsearchdate")) else ytsearch_query(query, cc_only=cc_only)
    args = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-download",
        "--playlist-end",
        str(max_items),
        "--no-warnings",
    ]
    if cc_only:
        args += ["--match-filter", "license *= *Creative Commons"]
    args.append(q)
    return args


def _extract(query: str, max_items: int, extra: list[str] | None = None, runner: Callable | None = None) -> list[dict]:
    import subprocess

    args = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-download",
        "--playlist-end",
        str(max_items),
        "--no-warnings",
        *(extra or []),
        query,
    ]
    if runner is not None:
        stdout = runner(args)
        text = stdout if isinstance(stdout, str) else ""
    else:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=180)
        text = proc.stdout or ""
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def poll_source(src: dict[str, Any], *, max_items: int = 5, runner: Callable | None = None) -> list[dict[str, Any]]:
    kind = (src.get("kind") or "keyword").lower()
    query = src.get("query") or ""
    cc_only = bool(src.get("cc_only"))
    if kind == "keyword":
        q = ytsearch_query(query, cc_only=cc_only, trending=query.strip().lower() in {"", "trending"})
    elif kind == "trailer":
        q = trailer_query(query)
    else:
        q = query
    extra: list[str] = []
    if cc_only:
        extra += ["--match-filter", "license *= *Creative Commons"]
    rows = _extract(q, max_items, extra, runner=runner)
    found: list[dict[str, Any]] = []
    for o in rows:
        vid = o.get("id") or video_id_from_url(o.get("webpage_url") or o.get("url") or "")
        if not vid:
            continue
        url = o.get("webpage_url") or o.get("url") or f"https://www.youtube.com/watch?v={vid}"
        recap = bool(src.get("recap")) or kind == "trailer"
        found.append({
            "url": url,
            "title": o.get("title") or "",
            "video_id": vid,
            "source_id": src.get("id"),
            "source_label": src.get("label") or query,
            "license": normalize_license(o.get("license"), url),
            "kind": "recap_short" if recap else "clip",
            "channel": o.get("channel") or o.get("uploader"),
            "duration_sec": o.get("duration"),
            "found_by": kind,
        })
    return found


def discover(max_per_source: int = 5, runner: Callable | None = None) -> list[dict[str, Any]]:
    remaining = remaining_today()
    if remaining <= 0:
        return []
    seen = load_seen()
    found: list[dict[str, Any]] = []
    for src in load_sources():
        if not src.get("enabled", True):
            continue
        if len(found) >= remaining:
            break
        try:
            batch = poll_source(src, max_items=max_per_source, runner=runner)
        except Exception:
            batch = []
        for v in batch:
            vid = v.get("video_id") or ""
            if vid and vid in seen:
                continue
            if any(x.get("video_id") == vid for x in found):
                continue
            found.append(v)
            if len(found) >= remaining:
                break
    return found


def run_once(
    *,
    process: bool = True,
    log: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Discover new videos and optionally clip/recap them into the draft review queue."""
    log = log or (lambda m: print(m, flush=True))
    settings = load_settings()
    found = discover()
    if not found:
        log("Auto-find: nothing new (or the daily cap is already used).")
        return []
    log(f"Auto-find: {len(found)} new video(s) (daily cap {daily_cap()}, already used {used_today()}).")
    processed: list[dict[str, Any]] = []
    if not process:
        return found
    out_dir = user_data_dir() / "autofind" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    autopilot = bool(settings.get("autopilot"))
    for video in found:
        log(f"Auto-find: {video.get('title') or video.get('url')} [{video.get('license')}] via {video.get('source_label')}")
        try:
            if (video.get("kind") or "").startswith("recap"):
                from clipper.recap import run_recap

                run_recap(
                    source=video["url"],
                    title=video.get("title") or "Recap",
                    fmt="short",
                    out_dir=str(out_dir),
                    enqueue=True,
                )
            else:
                from clipper.pipeline import run_pipeline

                run_pipeline(
                    video["url"],
                    str(out_dir),
                    count=1,
                    enqueue=True,
                )
            # Tag the latest queue item with source + licence
            from clipper.publish import load_queue, save_queue

            items = load_queue()
            if items:
                items[-1]["source_url"] = video.get("url")
                items[-1]["source_label"] = video.get("source_label")
                items[-1]["license"] = video.get("license")
                items[-1]["found_by"] = video.get("found_by")
                if not autopilot:
                    items[-1]["status"] = "pending_review"
                save_queue(items)
            mark_seen([video.get("video_id") or ""])
            record_used(1)
            processed.append(video)
        except Exception as exc:
            log(f"Auto-find: skipped ({type(exc).__name__})")
            # Still mark seen so a broken source cannot stall the cap forever? No — leave unseen to retry.
    if not autopilot:
        log("Queued for review only. Nothing posts unless Autopilot is on.")
    return processed


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipper find",
        description="Pull new videos from watched sources, keyword search, or trailers and queue draft clips.",
    )
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("list", help="List watched sources")
    add = sub.add_parser("add", help="Add a watched source")
    add.add_argument("kind", choices=["channel", "playlist", "brief", "keyword", "trailer"])
    add.add_argument("query", help="URL, keyword, brief link, or movie title")
    add.add_argument("--label", default=None)
    add.add_argument("--cc", action="store_true", help="Creative Commons only")
    add.add_argument("--recap", action="store_true", help="Treat new items as Recap jobs")
    rm = sub.add_parser("remove", help="Remove a source by id")
    rm.add_argument("id")
    run = sub.add_parser("run", help="Check sources now and queue new drafts")
    run.add_argument("--discover-only", action="store_true", help="Print new videos but do not process")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    if args.cmd == "list":
        srcs = load_sources()
        if not srcs:
            print("No watched sources yet. Add one with: clipper find add channel URL")
            return 0
        for s in srcs:
            flag = "" if s.get("enabled", True) else " (disabled)"
            cc = " CC-only" if s.get("cc_only") else ""
            recap = " recap" if s.get("recap") else ""
            print(f"{s.get('id')}\t{s.get('kind')}\t{s.get('label')}{cc}{recap}{flag}\t{s.get('query')}")
        print(f"Daily cap: {used_today()}/{daily_cap()} used today (Asia/Calcutta).")
        return 0
    if args.cmd == "add":
        item = add_source(args.kind, args.query, label=args.label, cc_only=args.cc, recap=args.recap)
        print(f"Added {item['id']} ({item['kind']}) {item['label']}")
        return 0
    if args.cmd == "remove":
        ok = remove_source(args.id)
        print("Removed" if ok else "No source with that id")
        return 0 if ok else 1
    if args.cmd == "run":
        found = run_once(process=not args.discover_only)
        if args.discover_only:
            for v in found:
                print(f"{v.get('video_id')}\t{v.get('license')}\t{v.get('source_label')}\t{v.get('title')}\t{v.get('url')}")
        return 0
    parser.print_help()
    return 0
