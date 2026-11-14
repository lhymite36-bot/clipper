"""Reframe landscape (or any) video to 9:16 1080x1920.

Order of preference:
1. Face-centered crop when a face is found
2. Center crop
3. Blurred-background fallback (used when style=blur, or when a crop would
   throw away too much of a near-square / portrait frame, or as the default
   fallback when no face is found and style=auto)
"""

from __future__ import annotations

from pathlib import Path

from clipper.ffmpeg_utils import find_ffmpeg, probe_size, run

TARGET_W = 1080
TARGET_H = 1920
TARGET_ASPECT = TARGET_W / TARGET_H  # 0.5625


def _haar_path() -> Path | None:
    bundled = Path(__file__).resolve().parent / "data" / "haarcascade_frontalface_default.xml"
    if bundled.is_file():
        return bundled
    try:
        import cv2

        p = Path(getattr(cv2.data, "haarcascades", "")) / "haarcascade_frontalface_default.xml"
        if p.is_file():
            return p
    except Exception:
        return None
    return None


def _yunet_path() -> Path | None:
    p = Path(__file__).resolve().parent / "data" / "face_detection_yunet_2023mar.onnx"
    return p if p.is_file() else None


def _make_face_detector(cv2, frame_size: tuple[int, int]):
    """Return a callable frame -> list of (x, y, w, h) in pixels, or None."""
    w, h = frame_size
    yunet = _yunet_path()
    if yunet and hasattr(cv2, "FaceDetectorYN_create"):
        try:
            det = cv2.FaceDetectorYN_create(str(yunet), "", (w, h), 0.7, 0.3, 5000)

            def _detect(frame):
                fh, fw = frame.shape[:2]
                if hasattr(det, "setInputSize"):
                    det.setInputSize((fw, fh))
                _retval, faces = det.detect(frame)
                if faces is None or len(faces) == 0:
                    return []
                return [(int(f[0]), int(f[1]), int(f[2]), int(f[3])) for f in faces]

            return _detect
        except Exception:
            pass
    haar = _haar_path()
    if haar and hasattr(cv2, "CascadeClassifier"):
        try:
            cascade = cv2.CascadeClassifier(str(haar))
            if cascade.empty():
                return None

            def _detect(frame):
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
                if faces is None or len(faces) == 0:
                    return []
                return [(int(x), int(y), int(fw), int(fh)) for x, y, fw, fh in faces]

            return _detect
        except Exception:
            return None
    return None


def detect_face_center(
    video: Path | str,
    start: float,
    end: float,
    *,
    samples: int = 8,
) -> tuple[float, float] | None:
    """Return (cx, cy) in 0–1 of the average largest-face center, or None."""
    try:
        import os
        os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
        import cv2
        import numpy as np
    except ImportError:
        return None

    try:
        duration = max(0.1, end - start)
        times = [start + duration * (i + 0.5) / samples for i in range(samples)]
        ffmpeg = find_ffmpeg()
        detector = None
        centers: list[tuple[float, float, float]] = []  # x, y, area
        for t in times:
            proc = run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-ss",
                    f"{t:.3f}",
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "mjpeg",
                    "pipe:1",
                ],
                check=False,
            )
            data = proc.stdout or b""
            if proc.returncode != 0 or not data:
                continue
            arr = np.frombuffer(data, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue
            h, w = frame.shape[:2]
            if detector is None:
                detector = _make_face_detector(cv2, (w, h))
                if detector is None:
                    return None
            faces = detector(frame)
            if not faces:
                continue
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            cx = (x + fw / 2) / w
            cy = (y + fh / 2) / h
            centers.append((cx, cy, (fw * fh) / (w * h)))
        if not centers:
            return None
        weight = sum(a for _x, _y, a in centers) or 1.0
        cx = sum(x * a for x, _y, a in centers) / weight
        cy = sum(y * a for _x, y, a in centers) / weight
        return float(cx), float(cy)
    except Exception:
        return None


def choose_style(
    src_w: int,
    src_h: int,
    style: str,
    has_face: bool,
) -> str:
    style = (style or "auto").lower()
    if style in {"face", "center", "blur"}:
        if style == "face" and not has_face:
            return "center"
        return style
    # auto
    if has_face:
        return "face"
    aspect = src_w / max(src_h, 1)
    # Very wide talking-head-less footage often looks better with a blur fill
    # than a tight center crop that throws the sides away.
    if aspect > 1.4:
        return "blur"
    return "center"


def build_vf(
    src_w: int,
    src_h: int,
    style: str,
    face: tuple[float, float] | None = None,
) -> str:
    """Return an ffmpeg filter graph that ends in a 1080x1920 yuv420p frame.

    The last filter's output is used as the main video (no labeled pads).
    """
    style = choose_style(src_w, src_h, style, has_face=bool(face))
    if style == "blur":
        return (
            f"split=2[bg][fg];"
            f"[bg]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},gblur=sigma=28,eq=brightness=-0.04[bg2];"
            f"[fg]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease[fg2];"
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,format=yuv420p"
        )

    # Crop a TARGET_ASPECT window, then scale to 1080x1920.
    # Crop size in source pixels:
    src_aspect = src_w / max(src_h, 1)
    if src_aspect > TARGET_ASPECT:
        crop_h = src_h
        crop_w = max(2, int(src_h * TARGET_ASPECT) // 2 * 2)
    else:
        crop_w = src_w
        crop_h = max(2, int(src_w / TARGET_ASPECT) // 2 * 2)

    if style == "face" and face:
        cx, cy = face
        x = int(cx * src_w - crop_w / 2)
        y = int(cy * src_h - crop_h / 2)
    else:
        x = (src_w - crop_w) // 2
        y = (src_h - crop_h) // 2
    # Keep the crop inside the frame
    x = max(0, min(x, src_w - crop_w))
    y = max(0, min(y, src_h - crop_h))
    x = x // 2 * 2
    y = y // 2 * 2
    return f"crop={crop_w}:{crop_h}:{x}:{y},scale={TARGET_W}:{TARGET_H},format=yuv420p"


def plan_reframe(
    video: Path | str,
    start: float,
    end: float,
    style: str = "auto",
    progress=None,
) -> tuple[str, str, tuple[float, float] | None]:
    """Return (filter_graph, resolved_style, face_center)."""
    log = progress or (lambda *_a, **_k: None)
    src_w, src_h = probe_size(video)
    want_face = (style or "auto").lower() in {"auto", "face"}
    face = None
    if want_face:
        log("Looking for a face to center the vertical crop…")
        face = detect_face_center(video, start, end)
        if face:
            log(f"Face found at ({face[0]:.2f}, {face[1]:.2f})")
        else:
            log("No face found")
    resolved = choose_style(src_w, src_h, style, has_face=bool(face))
    vf = build_vf(src_w, src_h, resolved if resolved != "face" or face else "center", face)
    # Recompute filter with the resolved style
    vf = build_vf(src_w, src_h, resolved, face)
    return vf, resolved, face
