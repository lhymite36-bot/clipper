"""Keep the YouTube downloader (yt-dlp) fresh and explain its errors in plain English.

YouTube changes often, and a yt-dlp frozen into the installer goes stale within
weeks. On launch Clipper checks GitHub (at most every 12 hours) for the official
yt-dlp zip build, verifies its SHA-256 against yt-dlp's published checksums,
and keeps it under %LOCALAPPDATA%\\Clipper\\tools. It is put first on sys.path
before yt-dlp is imported, so downloads always use the newest copy. If the
update fails, the bundled copy is used.

yt-dlp also needs a JavaScript runtime for YouTube. The installer bundles
QuickJS (qjs.exe, ~2 MB); Deno or Node on PATH are used too if present.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from clipper.paths import user_data_dir

RELEASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download"
CHECK_EVERY_S = 12 * 3600
UA = "Clipper-updater"

_state_lock = threading.Lock()
_update_thread: threading.Thread | None = None
_status: dict = {"state": "idle", "message": "", "version": None, "source": None}


def tools_dir() -> Path:
    return user_data_dir() / "tools"


def zip_path() -> Path:
    return tools_dir() / "yt-dlp.zip"


def _meta_path() -> Path:
    return tools_dir() / "yt-dlp.json"


def _set(**kw) -> None:
    with _state_lock:
        _status.update(kw)


def status() -> dict:
    with _state_lock:
        out = dict(_status)
    if out.get("version") is None and "yt_dlp" in sys.modules:
        try:
            out["version"] = sys.modules["yt_dlp"].version.__version__
        except Exception:  # noqa: BLE001
            pass
    return out


def _get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https host
        return r.read()


def _valid_zip(p: Path) -> bool:
    try:
        with zipfile.ZipFile(p) as z:
            return "yt_dlp/__init__.py" in z.namelist()
    except Exception:  # noqa: BLE001
        return False


def _zip_version(p: Path) -> str | None:
    try:
        with zipfile.ZipFile(p) as z:
            text = z.read("yt_dlp/version.py").decode("utf-8", "replace")
        m = re.search(r"__version__\s*=\s*'([^']+)'", text) or re.search(r'__version__\s*=\s*"([^"]+)"', text)
        return m.group(1) if m else None
    except Exception:  # noqa: BLE001
        return None


def update_now(log=None, force: bool = False) -> bool:
    """Download the latest official yt-dlp zip if it changed. Returns True if a fresh copy is ready."""
    log = log or (lambda *_a: None)
    tools_dir().mkdir(parents=True, exist_ok=True)
    meta = {}
    if _meta_path().is_file():
        try:
            meta = json.loads(_meta_path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = {}
    if not force and zip_path().is_file() and time.time() - meta.get("checked_at", 0) < CHECK_EVERY_S:
        _set(state="ready", message="Downloader is up to date.", version=_zip_version(zip_path()), source="updated")
        return True
    _set(state="checking", message="Checking for a newer YouTube downloader…")
    try:
        sums = _get(f"{RELEASE}/SHA2-256SUMS", timeout=20).decode("utf-8", "replace")
        want = None
        for line in sums.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == "yt-dlp":
                want = parts[0].lower()
        if not want:
            raise RuntimeError("checksum list has no entry for yt-dlp")
        if zip_path().is_file() and meta.get("sha256") == want and _valid_zip(zip_path()):
            meta["checked_at"] = time.time()
            _meta_path().write_text(json.dumps(meta), encoding="utf-8")
            _set(state="ready", message="Downloader is up to date.", version=_zip_version(zip_path()), source="updated")
            return True
        log("Updating the YouTube downloader (yt-dlp)…")
        data = _get(f"{RELEASE}/yt-dlp", timeout=120)
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            raise RuntimeError("downloaded yt-dlp failed its checksum")
        tmp = zip_path().with_suffix(".tmp")
        tmp.write_bytes(data)
        if not _valid_zip(tmp):
            tmp.unlink(missing_ok=True)
            raise RuntimeError("downloaded yt-dlp is not a valid build")
        os.replace(tmp, zip_path())
        version = _zip_version(zip_path())
        _meta_path().write_text(json.dumps({"sha256": want, "checked_at": time.time(), "version": version}), encoding="utf-8")
        _set(state="ready", message=f"Downloader updated to yt-dlp {version}.", version=version, source="updated")
        log(f"YouTube downloader updated to yt-dlp {version}.")
        return True
    except Exception as exc:  # noqa: BLE001
        ok = zip_path().is_file() and _valid_zip(zip_path())
        _set(
            state="ready" if ok else "bundled",
            message=f"Couldn't check for a downloader update ({exc}). Using the {'last downloaded' if ok else 'built-in'} copy.",
            version=_zip_version(zip_path()) if ok else None,
            source="updated" if ok else "bundled",
        )
        return ok


def start_background_update() -> None:
    """Called on launch; never blocks the UI."""
    global _update_thread
    if os.environ.get("CLIPPER_NO_YTDLP_UPDATE") == "1":
        return
    with _state_lock:
        if _update_thread and _update_thread.is_alive():
            return
        _update_thread = threading.Thread(target=update_now, name="ytdlp-update", daemon=True)
        _update_thread.start()


_PKGS = ("yt_dlp", "yt_dlp_ejs")


class _ZipFirstFinder:
    """Meta-path finder that serves yt_dlp / yt_dlp_ejs from the updated zip.

    PyInstaller's own importer would otherwise keep returning the copy frozen
    into the exe, so a plain sys.path insert is not enough.
    """

    def __init__(self, archive: str):
        import zipimport

        self.archive = archive
        self._zipimport = zipimport
        self.root = zipimport.zipimporter(archive)

    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".", 1)[0]
        if top not in _PKGS:
            return None
        try:
            if "." not in fullname:
                return self.root.find_spec(fullname)
            for entry in path or []:
                if str(entry).startswith(self.archive):
                    spec = self._zipimport.zipimporter(str(entry)).find_spec(fullname)
                    if spec is not None:
                        return spec
        except Exception:  # noqa: BLE001
            return None
        return None


def activate(log=None, wait_s: float = 45) -> None:
    """Make the newest yt-dlp importable. Must run before the first `import yt_dlp`."""
    log = log or (lambda *_a: None)
    t = _update_thread
    if t is not None and t.is_alive():
        log("Waiting for the downloader update to finish…")
        t.join(wait_s)
    if "yt_dlp" in sys.modules:
        return
    p = zip_path()
    if os.environ.get("CLIPPER_NO_YTDLP_UPDATE") != "1" and p.is_file() and _valid_zip(p):
        if not any(isinstance(f, _ZipFirstFinder) for f in sys.meta_path):
            sys.meta_path.insert(0, _ZipFirstFinder(str(p)))


def _bundled_qjs() -> str | None:
    names = ["qjs.exe", "qjs"] if os.name == "nt" else ["qjs"]
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
    roots.append(Path(__file__).resolve().parent / "data" / "bin")
    roots.append(tools_dir())
    for r in roots:
        for n in names:
            c = r / n
            if c.is_file():
                return str(c)
    return shutil.which("qjs")


def js_runtime_opts() -> dict:
    """yt-dlp `js_runtimes` option: Deno if installed, otherwise bundled QuickJS, Node 22+ as a last resort."""
    runtimes: dict = {}
    if shutil.which("deno"):
        runtimes["deno"] = {}
    q = _bundled_qjs()
    if q:
        runtimes["quickjs"] = {"path": q}
    if shutil.which("node"):
        runtimes["node"] = {}
    return runtimes or {"deno": {}}


# ---------------- URL handling ----------------

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_IN_TEXT = re.compile(r"((?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>\"']*)?)", re.I)


def normalize_source(text: str) -> str:
    """Pull the link out of pasted share text; accept a bare YouTube ID; add https:// if missing."""
    s = (text or "").strip()
    if not s:
        return s
    if _ID.match(s):
        return f"https://www.youtube.com/watch?v={s}"
    if os.path.exists(s):
        return s
    if re.match(r"^[a-zA-Z]:[\\/]", s) or s.startswith(("\\\\", "/")):
        return s  # local path (missing files are reported later)
    found = [m.group(1).rstrip(".,)]!?") for m in _URL_IN_TEXT.finditer(s)]
    if not found:
        raise ValueError(
            "That doesn't look like a link. Copy the video's Share link (for example https://youtu.be/…) and paste it here.",
        )
    yt = [u for u in found if re.search(r"(youtube\.com|youtu\.be|youtube-nocookie\.com)", u, re.I)]
    url = (yt or found)[0]
    if not url.lower().startswith("http"):
        url = "https://" + url
    return url


def friendly_error(exc: BaseException) -> str:
    """Turn yt-dlp / network errors into something Pedro can act on."""
    raw = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).strip()
    low = raw.lower()
    if "sign in to confirm" in low and "bot" in low:
        msg = ("YouTube is asking this network to prove it isn't a bot. Wait a few minutes and try again, "
               "switch network (e.g. phone hotspot), or download the video yourself and use Upload file.")
    elif "private video" in low:
        msg = "This video is private, so it can't be downloaded."
    elif "video unavailable" in low or "video is unavailable" in low or "this video has been removed" in low or "not available" in low:
        msg = "YouTube says this video is unavailable (removed, blocked in your country, or the link is wrong)."
    elif "sign in to confirm your age" in low or "age-restricted" in low or "inappropriate for some users" in low:
        msg = "This video is age-restricted, so it can't be downloaded without signing in. Download it yourself and use Upload file."
    elif "members-only" in low or "join this channel" in low:
        msg = "This is a members-only video, so it can't be downloaded."
    elif "is not a valid url" in low or "unsupported url" in low:
        msg = "Clipper can't download from that link. Paste a YouTube video link, or upload the video file."
    elif "live event will begin" in low or "is live" in low or "premieres in" in low:
        msg = "This is a live stream or premiere. Wait until it has finished, then try again."
    elif "requested format is not available" in low or "n challenge" in low or "signature" in low or "js runtime" in low or "javascript runtime" in low:
        msg = ("The YouTube downloader couldn't unlock this video's streams. Clipper updates it automatically on launch; "
               "close and reopen Clipper (while online), then try again.")
    elif "getaddrinfo" in low or "name or service not known" in low or "nodename nor servname" in low or "urlopen error" in low or "timed out" in low or "connection" in low:
        msg = "Couldn't reach YouTube. Check your internet connection and try again."
    elif "http error 403" in low:
        msg = "YouTube refused the download (HTTP 403). Close and reopen Clipper so the downloader updates, then try again."
    elif "http error 429" in low or "too many requests" in low:
        msg = "YouTube is rate-limiting this network. Wait 10–15 minutes and try again."
    else:
        return f"Download failed: {raw[:400]}"
    return f"{msg}\n(Details: {raw[:300]})"
