"""Tiny local web UI (FastAPI) for the clipping pipeline."""

from __future__ import annotations

import threading
import time
import uuid
import webbrowser
from pathlib import Path

from clipper import __app_name__, __version__

STATIC = Path(__file__).resolve().parent / "static"
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def _job(job_id: str) -> dict | None:
    with JOBS_LOCK:
        return JOBS.get(job_id)


def _update(job_id: str, **kwargs) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(kwargs)
            if kwargs.get("log_line"):
                JOBS[job_id].setdefault("log", []).append(kwargs["log_line"])
                JOBS[job_id]["log"] = JOBS[job_id]["log"][-400:]


def _run_job(job_id: str, source: str, opts: dict) -> None:
    from clipper.pipeline import run_pipeline

    def progress(msg: str) -> None:
        from clipper.config import redact

        text = redact(str(msg))
        _update(job_id, log_line=text, message=text)

    _update(job_id, status="running", message="Starting…")
    try:
        results = run_pipeline(source, opts["out_dir"], progress=progress, **opts["pipeline"])
        _update(
            job_id,
            status="done",
            message=f"Finished {len(results)} clip(s)",
            clips=[r.to_dict() for r in results],
        )
    except Exception as exc:  # noqa: BLE001
        _update(job_id, status="error", message=str(exc), log_line=f"Error: {exc}")



def _run_recap_job(job_id: str, source: str | None, opts: dict) -> None:
    from clipper.recap import run_recap

    def progress(msg: str) -> None:
        _update(job_id, log_line=str(msg), message=str(msg))

    _update(job_id, status="running", message="Starting recap…")
    try:
        result = run_recap(source, opts["title"], opts["out_dir"], progress=progress, **opts["pipeline"])
        _update(
            job_id,
            status="done",
            message=f"Finished recap ({result.duration:.0f}s)",
            recap=result.to_dict(),
            clips=[
                {
                    "index": 1,
                    "path": result.path,
                    "sidecar": result.sidecar,
                    "title": result.title,
                    "description": result.description,
                    "hashtags": result.tags,
                    "hook": result.hook,
                    "start": 0,
                    "end": result.duration,
                    "duration": result.duration,
                    "preset": "recap-" + result.format,
                    "layout": "blur" if result.format == "short" else "wide",
                    "title_options": [],
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001
        _update(job_id, status="error", message=str(exc), log_line=f"Error: {exc}")


def create_app():
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title=__app_name__, version=__version__)
    if STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        html = STATIC / "index.html"
        if not html.is_file():
            return HTMLResponse("<h1>Clipper</h1><p>UI files missing.</p>", 500)
        return HTMLResponse(html.read_text(encoding="utf-8"))

    @app.get("/api/health")
    def health():
        from clipper.ffmpeg_utils import FFmpegError, find_ffmpeg

        ffmpeg = True
        try:
            find_ffmpeg()
        except FFmpegError:
            ffmpeg = False
        from clipper.config import public_settings

        return {"ok": True, "version": __version__, "ffmpeg": ffmpeg, "settings": public_settings()}

    @app.post("/api/jobs")
    async def start_job(
        url: str = Form(""),
        count: int = Form(5),
        hook: str = Form(""),
        style: str = Form("auto"),
        preset: str = Form("auto"),
        layout: str = Form("auto"),
        grade: str = Form("auto"),
        model: str = Form("small"),
        language: str = Form("auto"),
        brief: str = Form(""),
        gemini_key: str = Form(""),
        groq_key: str = Form(""),
        captions: str = Form("auto"),
        punch: str = Form("1"),
        loop: str = Form("1"),
        auto_music: str = Form("1"),
        sfx: str = Form("1"),
        enqueue: str = Form("1"),
        file: UploadFile | None = File(None),
        music: UploadFile | None = File(None),
    ):
        job_id = uuid.uuid4().hex[:12]
        out_dir = Path.home() / "Clipper" / "jobs" / job_id
        out_dir.mkdir(parents=True, exist_ok=True)

        source = (url or "").strip()
        if file and file.filename:
            dest = out_dir / "_work"
            dest.mkdir(parents=True, exist_ok=True)
            suffix = Path(file.filename).suffix or ".mp4"
            saved = dest / f"upload{suffix}"
            data = await file.read()
            if not data:
                raise HTTPException(400, "Uploaded file is empty")
            saved.write_bytes(data)
            source = str(saved)
        if not source:
            raise HTTPException(400, "Provide a video URL or upload a file")

        music_path = None
        if music and music.filename:
            dest_m = out_dir / "_work"
            dest_m.mkdir(parents=True, exist_ok=True)
            suffix = Path(music.filename).suffix or ".mp3"
            saved_m = dest_m / f"music{suffix}"
            data_m = await music.read()
            if data_m:
                saved_m.write_bytes(data_m)
                music_path = str(saved_m)

        cap = (captions or "auto").strip().lower()
        if cap in {"0", "false", "off"}:
            cap = "none"
        elif cap in {"1", "true", "on"}:
            cap = "auto"

        opts = {
            "out_dir": out_dir,
            "pipeline": {
                "count": max(1, min(int(count or 5), 20)),
                "model": model or "small",
                "language": language or "auto",
                "hook": hook.strip() or None,
                "style": style or "auto",
                "preset": preset or "auto",
                "layout": layout or "auto",
                "grade": None if (grade or "auto") == "auto" else grade,
                "gemini_key": gemini_key.strip() or None,
                "groq_key": groq_key.strip() or None,
                "captions": cap,
                "punch": punch not in {"0", "false", "off"},
                "loop": loop not in {"0", "false", "off"},
                "auto_music": auto_music not in {"0", "false", "off"},
                "sfx": sfx not in {"0", "false", "off"},
                "enqueue": enqueue not in {"0", "false", "off"},
                "brief": brief.strip() or None,
                "music": music_path,
            },
        }
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "message": "Queued",
                "log": [],
                "clips": [],
                "out_dir": str(out_dir),
                "created": time.time(),
            }
        thread = threading.Thread(target=_run_job, args=(job_id, source, opts), daemon=True)
        thread.start()
        return {"id": job_id}


    @app.get("/api/voices")
    def voices():
        from clipper.recap_tts import list_voices

        return {"voices": list_voices()}

    @app.post("/api/recap")
    async def start_recap(
        url: str = Form(""),
        title: str = Form(""),
        format: str = Form("short"),
        voice: str = Form("auto"),
        spoilers: str = Form("0"),
        target_seconds: str = Form(""),
        model: str = Form("small"),
        language: str = Form("auto"),
        grade: str = Form("moody"),
        plot_text: str = Form(""),
        gemini_key: str = Form(""),
        groq_key: str = Form(""),
        file: UploadFile | None = File(None),
        subs: UploadFile | None = File(None),
        plot: UploadFile | None = File(None),
        music: UploadFile | None = File(None),
        enqueue: str = Form("1"),
    ):
        if not (title or "").strip():
            raise HTTPException(400, "A movie title is required")
        job_id = uuid.uuid4().hex[:12]
        out_dir = Path.home() / "Clipper" / "jobs" / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        work = out_dir / "_work"
        work.mkdir(parents=True, exist_ok=True)

        source = (url or "").strip() or None
        if file and file.filename:
            suffix = Path(file.filename).suffix or ".mp4"
            saved = work / f"upload{suffix}"
            data = await file.read()
            if data:
                saved.write_bytes(data)
                source = str(saved)

        async def _save(up, name):
            if not up or not up.filename:
                return None
            suffix = Path(up.filename).suffix or ""
            dest = work / f"{name}{suffix}"
            data = await up.read()
            if not data:
                return None
            dest.write_bytes(data)
            return str(dest)

        subs_path = await _save(subs, "subs")
        plot_path = await _save(plot, "plot")
        music_path = await _save(music, "music")
        target = None
        if (target_seconds or "").strip():
            try:
                target = float(target_seconds)
            except ValueError:
                target = None

        opts = {
            "out_dir": out_dir,
            "title": title.strip(),
            "pipeline": {
                "fmt": format or "short",
                "voice": voice or "auto",
                "spoilers": spoilers not in {"0", "false", "off"},
                "subs": subs_path,
                "plot": plot_path,
                "plot_text": plot_text.strip() or None,
                "target_seconds": target,
                "model": model or "small",
                "language": language or "auto",
                "grade": grade or "moody",
                "music": music_path,
                "enqueue": enqueue not in {"0", "false", "off"},
                "gemini_key": gemini_key.strip() or None,
                "groq_key": groq_key.strip() or None,
            },
        }
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "message": "Queued recap",
                "log": [],
                "clips": [],
                "recap": None,
                "out_dir": str(out_dir),
                "created": time.time(),
            }
        thread = threading.Thread(target=_run_recap_job, args=(job_id, source, opts), daemon=True)
        thread.start()
        return {"id": job_id}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = _job(job_id)
        if not job:
            raise HTTPException(404, "Unknown job")
        # Don't send giant logs only — they're already capped
        return {
            "id": job["id"],
            "status": job["status"],
            "message": job.get("message") or "",
            "log": job.get("log") or [],
            "clips": job.get("clips") or [],
            "recap": job.get("recap"),
        }

    @app.get("/api/jobs/{job_id}/file")
    def get_file(job_id: str, path: str):
        job = _job(job_id)
        if not job:
            raise HTTPException(404, "Unknown job")
        out_dir = Path(job["out_dir"]).resolve()
        target = Path(path).resolve()
        try:
            target.relative_to(out_dir)
        except ValueError:
            raise HTTPException(403, "Invalid path") from None
        if not target.is_file():
            raise HTTPException(404, "File not found")
        media = "video/mp4" if target.suffix.lower() == ".mp4" else "text/plain"
        return FileResponse(target, media_type=media, filename=target.name)

    @app.get("/api/settings")
    def get_settings():
        from clipper.config import public_settings

        return public_settings()

    @app.post("/api/settings")
    async def post_settings(payload: dict):
        from clipper.config import public_settings, save_settings

        allowed = {
            "model", "language", "draft_only", "autopilot", "publish_method",
            "schedule_times", "per_day", "github_repo", "buffer_channel_id",
            "buffer_organization_id", "youtube_privacy", "auto_music", "sfx", "enqueue",
        }
        updates = {k: v for k, v in (payload or {}).items() if k in allowed}
        save_settings(updates)
        return public_settings()

    @app.get("/api/queue")
    def get_queue():
        from clipper.publish import load_queue

        return {"items": load_queue()}

    @app.post("/api/queue/{item_id}/{action}")
    def queue_action(item_id: str, action: str, draft: str = "1"):
        from clipper.publish import post_item, set_status

        action = (action or "").lower()
        if action == "approve":
            item = set_status(item_id, "approved")
        elif action == "reject":
            item = set_status(item_id, "rejected")
        elif action == "publish":
            item = post_item(item_id, force=False, draft=draft not in {"0", "false", "off"})
        else:
            raise HTTPException(400, "Unknown action")
        if not item:
            raise HTTPException(404, "Unknown queue item")
        return item

    @app.get("/api/buffer/channels")
    def buffer_channels():
        from clipper.config import secret
        from clipper.publish import buffer_channels as list_channels

        key = secret("BUFFER_API_KEY")
        if not key:
            raise HTTPException(400, "Set BUFFER_API_KEY in your .env first.")
        try:
            return {"channels": list_channels(key)}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc)) from exc


    return app


def serve(host: str = "127.0.0.1", port: int = 8766) -> int:
    import uvicorn

    url = f"http://{host}:{port}"
    print(f"{__app_name__} {__version__}")
    print(f"Opening {url}")

    def _open():
        time.sleep(0.8)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open, daemon=True).start()
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
    return 0
