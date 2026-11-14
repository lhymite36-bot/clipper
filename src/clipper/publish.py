"""Local review queue plus Buffer (default) or YouTube Data API posting.

Nothing is published unless the user turns autopilot on *and* turns draft-only
off, or explicitly approves and posts an item. Secrets come from the environment.
Buffer needs a public HTTPS URL, so clips can be uploaded to a public GitHub
release (same approach as Voice to Short / qb-media). Clipper never rips
YouTube audio to use as music.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
try:
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Calcutta")
except Exception:  # tzdata missing on some Python installs
    IST = timezone(timedelta(hours=5, minutes=30))

import httpx

from clipper.config import load_settings, secret
from clipper.paths import queue_path, user_data_dir
BUFFER_URL = "https://api.buffer.com"
BUFFER_FREE_QUEUE = 10
Q_ORGS = "query { account { organizations { id name } } }"
Q_CHANNELS = "query Ch($org: OrganizationId!) { channels(input: { organizationId: $org }) { id name displayName service isQueuePaused isDisconnected } }"
Q_QUEUE = "query Q($org: OrganizationId!, $ch: [ChannelId!]) { posts(first: 100, input: { organizationId: $org, filter: { channelIds: $ch, status: [scheduled] } }) { edges { node { id dueAt } } } }"
M_CREATE = "mutation P($input: CreatePostInput!) { createPost(input: $input) { ... on PostActionSuccess { post { id dueAt status } } ... on MutationError { message } } }"
YT_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
YT_TOKEN = "https://oauth2.googleapis.com/token"


def _now() -> datetime:
    return datetime.now(tz=IST)


def load_queue() -> list[dict[str, Any]]:
    path = queue_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return list(raw.get("items") or raw) if isinstance(raw, dict) else list(raw)
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def save_queue(items: list[dict[str, Any]]) -> None:
    path = queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")


def enqueue(
    clip: dict[str, Any],
    *,
    status: str = "pending_review",
) -> dict[str, Any]:
    items = load_queue()
    item = {
        "id": uuid.uuid4().hex[:10],
        "status": status,  # pending_review | approved | scheduled | posted | rejected | draft
        "created_at": _now().isoformat(),
        "due_at": None,
        "public_url": None,
        "remote_id": None,
        "error": None,
        **{k: clip.get(k) for k in (
            "path", "sidecar", "title", "description", "hashtags", "hook",
            "preset", "layout", "index",
        )},
    }
    items.append(item)
    save_queue(items)
    return item


def set_status(item_id: str, status: str, **extra: Any) -> dict[str, Any] | None:
    items = load_queue()
    found = None
    for item in items:
        if item.get("id") == item_id:
            item["status"] = status
            item.update({k: v for k, v in extra.items() if v is not None or k in extra})
            found = item
            break
    if found is not None:
        save_queue(items)
    return found


def next_slots(count: int = 3, *, now: datetime | None = None) -> list[datetime]:
    settings = load_settings()
    times = settings.get("schedule_times") or ["18:00"]
    parsed: list[tuple[int, int]] = []
    for raw in times:
        try:
            hh, mm = str(raw).strip().split(":")
            parsed.append((int(hh), int(mm)))
        except ValueError:
            continue
    if not parsed:
        parsed = [(18, 0)]
    per_day = max(1, int(settings.get("per_day") or len(parsed)))
    parsed = parsed[:per_day]
    cursor = (now or _now()) + timedelta(minutes=5)
    slots: list[datetime] = []
    day = cursor.date()
    while len(slots) < count:
        for hh, mm in parsed:
            cand = datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST)
            if cand >= cursor:
                slots.append(cand)
                if len(slots) >= count:
                    break
        day = day + timedelta(days=1)
    return slots


# ---------- Buffer + GitHub public host ----------

def buffer_call(api_key: str, query: str, variables: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    res = httpx.post(BUFFER_URL, headers=headers, json={"query": query, "variables": variables or {}}, timeout=30)
    data = None
    try:
        data = res.json()
    except Exception:
        data = {}
    if res.status_code in {401, 403}:
        raise RuntimeError("Buffer rejected the API key. Check BUFFER_API_KEY in your .env.")
    if not res.is_success and not (data and data.get("data")):
        raise RuntimeError(f"Buffer HTTP {res.status_code}")
    if data.get("errors") and not data.get("data"):
        msg = data["errors"][0].get("message") or "Buffer error"
        raise RuntimeError(f"Buffer: {msg}")
    return data.get("data") or {}


def buffer_channels(api_key: str) -> list[dict]:
    d = buffer_call(api_key, Q_ORGS)
    orgs = ((d.get("account") or {}).get("organizations")) or []
    out: list[dict] = []
    for org in orgs:
        c = buffer_call(api_key, Q_CHANNELS, {"org": org["id"]})
        for ch in c.get("channels") or []:
            row = dict(ch)
            row["organizationId"] = org["id"]
            row["organizationName"] = org.get("name") or ""
            out.append(row)
    return out


def buffer_post_input(
    *,
    channel_id: str,
    video_url: str,
    title: str,
    description: str,
    due_at: datetime,
    needs_approval: bool,
) -> dict:
    return {
        "channelId": channel_id,
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due_at.astimezone(timezone.utc).isoformat(),
        "needsApproval": bool(needs_approval),
        "text": description,
        "assets": [{"video": {"url": video_url, "metadata": {"title": title}}}],
        "metadata": {
            "youtube": {
                "title": title[:100],
                "categoryId": "24",
                "privacy": "public",
                "madeForKids": False,
                "isAiGenerated": False,
                "notifySubscribers": True,
                "embeddable": True,
                "license": "youtube",
            }
        },
        "source": "clipper-autopost",
    }


def github_upload_asset(path: Path, *, name: str | None = None, repo: str, token: str) -> str:
    """Upload an mp4 to a prerelease on a public repo; return the download URL."""
    tag = "clipper-autopost-media"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    api = f"https://api.github.com/repos/{repo}/releases"
    with httpx.Client(timeout=60) as client:
        rel = client.get(f"{api}/tags/{tag}", headers=headers)
        if rel.status_code == 404:
            created = client.post(
                api,
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "tag_name": tag,
                    "name": "Clipper autopost media",
                    "body": "Public MP4s so Buffer can fetch them. Safe to delete after a Short is posted. This release is a prerelease and must not be marked Latest.",
                    "prerelease": True,
                    "make_latest": "false",
                },
            )
            if created.status_code >= 300:
                raise RuntimeError(
                    f"Could not create a media release on {repo} (HTTP {created.status_code}). "
                    "The repo must be public and the token needs Contents: Read and write."
                )
            rel_id = created.json()["id"]
        else:
            rel.raise_for_status()
            rel_id = rel.json()["id"]
        asset_name = name or path.name
        upload_url = (
            f"https://uploads.github.com/repos/{repo}/releases/{rel_id}/assets?name={quote(asset_name)}"
        )
        data = path.read_bytes()
        up = client.post(
            upload_url,
            headers={**headers, "Content-Type": "video/mp4"},
            content=data,
            timeout=120,
        )
        if up.status_code == 422:
            return f"https://github.com/{repo}/releases/download/{tag}/{quote(asset_name)}"
        if up.status_code >= 300:
            raise RuntimeError(f"GitHub upload failed (HTTP {up.status_code}).")
        body = up.json()
        return body.get("browser_download_url") or f"https://github.com/{repo}/releases/download/{tag}/{quote(asset_name)}"


# ---------- YouTube Data API (optional) ----------

def youtube_access_token() -> str:
    refresh = secret("YOUTUBE_REFRESH_TOKEN")
    client_id = secret("YOUTUBE_CLIENT_ID")
    client_secret = secret("YOUTUBE_CLIENT_SECRET")
    if not (refresh and client_id and client_secret):
        raise RuntimeError("YouTube upload needs YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN in .env.")
    res = httpx.post(
        YT_TOKEN,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if res.status_code >= 300:
        raise RuntimeError("YouTube OAuth refresh failed. Re-connect the Google account.")
    token = (res.json() or {}).get("access_token") or ""
    if not token:
        raise RuntimeError("YouTube OAuth refresh returned no access token.")
    return token


def youtube_upload(path: Path, *, title: str, description: str, privacy: str = "private") -> str:
    token = youtube_access_token()
    snippet = {
        "snippet": {"title": title[:100], "description": description[:4900], "categoryId": "24"},
        "status": {
            "privacyStatus": privacy if privacy in {"private", "unlisted", "public"} else "private",
            "selfDeclaredMadeForKids": False,
        },
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    size = path.stat().st_size
    init = httpx.post(
        YT_UPLOAD,
        headers={**headers, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
        json=snippet,
        timeout=30,
    )
    loc = init.headers.get("Location") or init.headers.get("location")
    if init.status_code >= 300 or not loc:
        raise RuntimeError(f"YouTube did not accept the upload (HTTP {init.status_code}).")
    data = path.read_bytes()
    done = httpx.put(
        loc,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4", "Content-Length": str(size)},
        content=data,
        timeout=300,
    )
    if done.status_code >= 300:
        raise RuntimeError(f"YouTube upload failed (HTTP {done.status_code}).")
    body = done.json() if done.content else {}
    return body.get("id") or ""


def can_publish() -> tuple[bool, str]:
    """Whether autopilot is allowed to send anything off the machine."""
    settings = load_settings()
    if not settings.get("autopilot"):
        return False, "Autopilot is off. Approve clips and post them yourself, or turn autopilot on in settings."
    if settings.get("draft_only", True):
        return False, "Draft-only is on (the default). Turn it off in settings when you want Clipper to publish."
    return True, "ok"


def post_item(item_id: str, *, force: bool = False, draft: bool | None = None) -> dict[str, Any]:
    """Upload / schedule one approved (or forced) queue item."""
    settings = load_settings()
    items = {i["id"]: i for i in load_queue()}
    item = items.get(item_id)
    if not item:
        raise RuntimeError("Unknown queue item.")
    if item["status"] not in {"approved", "pending_review", "draft"} and not force:
        raise RuntimeError(f"Item is {item['status']}, not approved.")
    if item["status"] == "pending_review" and not force:
        raise RuntimeError("This clip is waiting for review. Approve it first.")
    path = Path(item.get("path") or "")
    if not path.is_file():
        raise RuntimeError("The clip file is missing.")

    draft_only = settings.get("draft_only", True) if draft is None else draft
    if not force:
        ok, reason = can_publish()
        if not ok and not draft_only:
            raise RuntimeError(reason)

    title = item.get("title") or "Short"
    description = item.get("description") or title
    method = (settings.get("publish_method") or "buffer").lower()

    if method == "youtube":
        privacy = "private" if draft_only else (settings.get("youtube_privacy") or "private")
        yt_id = youtube_upload(path, title=title, description=description, privacy=privacy)
        return set_status(item_id, "draft" if draft_only else "posted", remote_id=yt_id, public_url=f"https://youtube.com/shorts/{yt_id}") or item

    # Buffer path: need a public URL, then schedule (or submit for Buffer approval).
    repo = (settings.get("github_repo") or "").strip()
    token = secret("CLIPPER_GITHUB_TOKEN") or secret("GITHUB_TOKEN")
    if not repo or not token:
        raise RuntimeError("Buffer posting needs a public GitHub repo (settings.github_repo) and CLIPPER_GITHUB_TOKEN in .env.")
    url = github_upload_asset(path, name=f"{item_id}-{path.name}", repo=repo, token=token)
    api_key = secret("BUFFER_API_KEY")
    if not api_key:
        raise RuntimeError("Set BUFFER_API_KEY in your .env (Buffer → Settings → API).")
    channel = (settings.get("buffer_channel_id") or "").strip()
    if not channel:
        raise RuntimeError("Pick a Buffer YouTube channel in settings (buffer_channel_id).")
    due = next_slots(1)[0]
    payload = buffer_post_input(
        channel_id=channel,
        video_url=url,
        title=title,
        description=description,
        due_at=due,
        needs_approval=bool(draft_only),
    )
    data = buffer_call(api_key, M_CREATE, {"input": payload})
    created = (data.get("createPost") or {})
    if not created.get("post"):
        raise RuntimeError("Buffer: " + (created.get("message") or "could not create the post"))
    post = created["post"]
    status = "draft" if draft_only else "scheduled"
    return set_status(
        item_id,
        status,
        public_url=url,
        remote_id=post.get("id"),
        due_at=post.get("dueAt") or due.isoformat(),
    ) or item


def cli_main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "queue"
    args = argv[1:]
    if cmd == "queue" and (not args or args[0] in {"list", "ls"}):
        items = load_queue()
        if not items:
            print("Queue is empty.")
            return 0
        for item in items:
            print(f"{item['id']}  {item['status']:16}  {item.get('title') or item.get('path')}")
        return 0
    if cmd in {"approve", "queue"} and args and (cmd == "approve" or args[0] == "approve"):
        item_id = args[-1]
        item = set_status(item_id, "approved")
        if not item:
            print("Unknown id.")
            return 1
        print(f"Approved {item_id}: {item.get('title')}")
        return 0
    if cmd in {"reject", "queue"} and args and (cmd == "reject" or args[0] == "reject"):
        item_id = args[-1]
        item = set_status(item_id, "rejected")
        if not item:
            print("Unknown id.")
            return 1
        print(f"Rejected {item_id}")
        return 0
    if cmd == "publish":
        draft = "--draft" in args or load_settings().get("draft_only", True)
        ids = [a for a in args if not a.startswith("-")]
        items = load_queue()
        targets = [i for i in items if (not ids or i["id"] in ids) and i["status"] == "approved"]
        if not targets:
            print("No approved clips to publish. Use: clipper approve <id>")
            return 1
        ok, reason = can_publish()
        if not ok and not draft:
            print(reason)
            return 1
        for item in targets:
            try:
                got = post_item(item["id"], draft=draft)
                print(f"{got['id']} -> {got['status']}")
            except Exception as exc:  # noqa: BLE001
                print(f"{item['id']} failed: {exc}")
                set_status(item["id"], "approved", error=str(exc))
        return 0
    print("Usage: clipper queue | clipper approve ID | clipper reject ID | clipper publish [--draft]")
    return 1
