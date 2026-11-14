"""Still-image / stick-figure scenes when no footage is available or a shot fails."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from clipper.recap_script import RecapLine

# Muted recap palettes (BGR would be later; we write RGB via ffmpeg raw).
PALETTES = [
    (18, 16, 22, 140, 90, 50),
    (12, 20, 28, 60, 90, 110),
    (24, 14, 14, 130, 40, 40),
    (16, 22, 16, 70, 110, 60),
    (20, 16, 28, 90, 60, 120),
]


def make_still(
    dest: Path,
    line: RecapLine,
    *,
    width: int,
    height: int,
    duration: float,
    index: int,
    hook: str = "",
    title: str = "",
) -> Path:
    """Write a short MP4 of an illustrated still (gradient + silhouettes + title)."""
    from clipper.ffmpeg_utils import find_ffmpeg, run

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    png = dest.with_suffix(".png")
    _draw_card(png, line, width=width, height=height, index=index, hook=hook, title=title)
    dur = max(1.5, float(duration))
    # Slow punch-in on the still so it isn't a frozen frame.
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"zoompan=z='min(1.08,1+0.08*on/({dur}*25))':d={int(dur*25)+2}:s={width}x{height}:fps=25,"
        f"format=yuv420p"
    )
    run(
        [
            find_ffmpeg(), "-y",
            "-loop", "1", "-i", str(png),
            "-t", f"{dur:.3f}",
            "-vf", vf,
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(dest),
        ]
    )
    return dest


def _draw_card(
    png: Path,
    line: RecapLine,
    *,
    width: int,
    height: int,
    index: int,
    hook: str,
    title: str,
) -> None:
    """NumPy + Pillow if present, else a raw PPM piped through ffmpeg."""
    pal = PALETTES[index % len(PALETTES)]
    bg1, bg2 = pal[:3], pal[3:]
    yy = np.linspace(0, 1, height)[:, None]
    xx = np.linspace(0, 1, width)[None, :]
    img = np.zeros((height, width, 3), dtype=np.uint8)
    for c in range(3):
        img[:, :, c] = np.clip(bg1[c] + (bg2[c] - bg1[c]) * (0.35 + 0.65 * yy), 0, 255)
    # Soft vignette
    vx = (xx - 0.5) ** 2 + (yy - 0.45) ** 2
    vig = np.clip(1.0 - vx * 1.6, 0.35, 1.0)
    img = (img.astype(np.float32) * vig[:, :, None]).astype(np.uint8)
    _stick_figures(img, index, line.beat)
    caption = (line.text or hook or title or "Recap")[:72]
    try:
        _label_pil(img, caption, title, width, height)
    except Exception:
        pass
    _save_png(png, img)


def _stick_figures(img: np.ndarray, index: int, beat: str) -> None:
    h, w, _ = img.shape
    # One or two silhouettes, placed in the lower third.
    rng = np.random.default_rng(1000 + index)
    n = 2 if beat in {"conflict", "twist"} else 1
    for k in range(n):
        cx = int(w * (0.32 + 0.36 * k + 0.04 * rng.normal()))
        foot = int(h * 0.78)
        scale = int(min(w, h) * (0.22 if h > w else 0.18))
        color = (20, 18, 16)
        # Head
        _circle(img, cx, foot - scale, int(scale * 0.18), color)
        # Body
        _line(img, cx, foot - int(scale * 0.82), cx, foot - int(scale * 0.28), color, 5)
        # Arms / legs with a bit of pose variety
        sway = int(scale * (0.12 if (index + k) % 2 == 0 else -0.08))
        _line(img, cx, foot - int(scale * 0.66), cx - int(scale * 0.28), foot - int(scale * 0.48) + sway, color, 4)
        _line(img, cx, foot - int(scale * 0.66), cx + int(scale * 0.30), foot - int(scale * 0.50) - sway, color, 4)
        _line(img, cx, foot - int(scale * 0.28), cx - int(scale * 0.18), foot, color, 5)
        _line(img, cx, foot - int(scale * 0.28), cx + int(scale * 0.20), foot, color, 5)


def _circle(img, cx, cy, r, color):
    h, w, _ = img.shape
    ys, xs = np.ogrid[-r:r + 1, -r:r + 1]
    mask = xs**2 + ys**2 <= r * r
    for dy, dx in zip(*np.where(mask)):
        y, x = cy - r + dy, cx - r + dx
        if 0 <= y < h and 0 <= x < w:
            img[y, x] = color


def _line(img, x0, y0, x1, y1, color, thickness=3):
    h, w, _ = img.shape
    n = max(abs(x1 - x0), abs(y1 - y0), 1)
    for i in range(n + 1):
        x = int(x0 + (x1 - x0) * i / n)
        y = int(y0 + (y1 - y0) * i / n)
        for dx in range(-thickness, thickness + 1):
            for dy in range(-thickness, thickness + 1):
                if dx * dx + dy * dy > thickness * thickness:
                    continue
                xx, yy = x + dx, y + dy
                if 0 <= yy < h and 0 <= xx < w:
                    img[yy, xx] = color


def _label_pil(img: np.ndarray, caption: str, title: str, width: int, height: int) -> None:
    from PIL import Image, ImageDraw, ImageFont

    im = Image.fromarray(img, mode="RGB")
    draw = ImageDraw.Draw(im)
    font_big = _font(int(height * 0.045 if height > width else height * 0.055))
    font_sm = _font(int(height * 0.028 if height > width else height * 0.035))
    # Title at the top
    if title:
        tw = title.upper()[:40]
        draw.text((width * 0.08, height * 0.08), tw, fill=(230, 220, 200), font=font_sm)
    # Caption wrapped in the lower band
    wrapped = _wrap(caption, 28)
    y = int(height * 0.82)
    for row in wrapped[:3]:
        draw.text((width * 0.08, y), row, fill=(245, 245, 240), font=font_big)
        y += int(height * 0.05)
    img[:, :, :] = np.array(im)


def _font(size: int):
    from PIL import ImageFont
    from clipper.captions import fonts_dir

    candidates = []
    d = fonts_dir()
    if d:
        candidates += [d / "Montserrat-ExtraBold.ttf", d / "Anton-Regular.ttf"]
    candidates += [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]
    for p in candidates:
        if p and Path(p).is_file():
            return ImageFont.truetype(str(p), size=size)
    return ImageFont.load_default()


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    rows, cur = [], []
    for w in words:
        if len(" ".join(cur + [w])) > width and cur:
            rows.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        rows.append(" ".join(cur))
    return rows


def _save_png(path: Path, img: np.ndarray) -> None:
    try:
        from PIL import Image

        Image.fromarray(img, mode="RGB").save(path)
        return
    except Exception:
        pass
    # PPM fallback, then ffmpeg.
    from clipper.ffmpeg_utils import find_ffmpeg, run

    ppm = path.with_suffix(".ppm")
    h, w, _ = img.shape
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    ppm.write_bytes(header + img.tobytes())
    run([find_ffmpeg(), "-y", "-i", str(ppm), str(path)])
