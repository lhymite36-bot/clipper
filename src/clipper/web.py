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
        _update(job_id, log_line=str(msg), message=str(msg))

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
        return {"ok": True, "version": __version__, "ffmpeg": ffmpeg}

    @app.post("/api/jobs")
    async def start_job(
        url: str = Form(""),
        count: int = Form(5),
        hook: str = Form(""),
        style: str = Form("auto"),
        model: str = Form("tiny"),
        gemini_key: str = Form(""),
        groq_key: str = Form(""),
        captions: str = Form("1"),
        file: UploadFile | None = File(None),
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

        opts = {
            "out_dir": out_dir,
            "pipeline": {
                "count": max(1, min(int(count or 5), 20)),
                "model": model or "tiny",
                "hook": hook.strip() or None,
                "style": style or "auto",
                "gemini_key": gemini_key.strip() or None,
                "groq_key": groq_key.strip() or None,
                "captions": captions not in {"0", "false", "off"},
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
