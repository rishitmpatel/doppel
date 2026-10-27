"""Synthetic photo-like test images (no external files)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageOps


def photo(seed: int, size: tuple[int, int] = (640, 480)) -> Image.Image:
    """Smooth colour field + random shapes + a little texture: roughly photo-like."""
    rng = np.random.default_rng(seed)
    w, h = size
    coarse = rng.integers(0, 256, (5, 7, 3), dtype=np.uint8)
    img = Image.fromarray(coarse).resize(size, Image.Resampling.BICUBIC)
    draw = ImageDraw.Draw(img)
    for _ in range(int(rng.integers(6, 12))):
        x0, y0 = int(rng.integers(0, w - 40)), int(rng.integers(0, h - 40))
        x1, y1 = x0 + int(rng.integers(30, w // 2)), y0 + int(rng.integers(30, h // 2))
        color = tuple(int(c) for c in rng.integers(0, 256, 3))
        kind = int(rng.integers(0, 3))
        if kind == 0:
            draw.ellipse((x0, y0, x1, y1), fill=color)
        elif kind == 1:
            draw.rectangle((x0, y0, x1, y1), fill=color)
        else:
            draw.polygon([(x0, y1), ((x0 + x1) // 2, y0), (x1, y1)], fill=color)
    arr = np.asarray(img).astype(np.int16) + rng.normal(0, 3, (h, w, 3)).astype(np.int16)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def gradient(seed: int, size: tuple[int, int] = (640, 480)) -> Image.Image:
    """Linear gradient at a random angle between two random colours, plus 1-2 shapes."""
    rng = np.random.default_rng(10_000 + seed)
    w, h = size
    angle = rng.uniform(0, 2 * np.pi)
    yy, xx = np.mgrid[0:h, 0:w]
    t = (xx / w - 0.5) * np.cos(angle) + (yy / h - 0.5) * np.sin(angle)
    t = (t - t.min()) / (t.max() - t.min())
    c0, c1 = rng.integers(0, 256, 3), rng.integers(0, 256, 3)
    arr = c0[None, None, :] * (1 - t[..., None]) + c1[None, None, :] * t[..., None]
    img = Image.fromarray(arr.astype(np.uint8))
    d = ImageDraw.Draw(img)
    for _ in range(int(rng.integers(1, 3))):
        x0, y0 = int(rng.integers(0, w // 2)), int(rng.integers(0, h // 2))
        d.ellipse((x0, y0, x0 + int(rng.integers(40, w // 2)), y0 + int(rng.integers(40, h // 2))),
                  fill=tuple(int(c) for c in rng.integers(0, 256, 3)))
    return img


def texture(seed: int, size: tuple[int, int] = (640, 480)) -> Image.Image:
    """Band-limited random noise at a random scale."""
    rng = np.random.default_rng(20_000 + seed)
    cells = int(rng.integers(3, 40))
    coarse = rng.integers(0, 256, (cells, max(2, cells * 4 // 3), 3), dtype=np.uint8)
    return Image.fromarray(coarse).resize(size, Image.Resampling.BICUBIC)


def distinct_images(count: int = 24, size: tuple[int, int] = (640, 480)) -> list[Image.Image]:
    """``count`` genuinely different images: a third each shapes / gradients / textures."""
    makers = (photo, gradient, texture)
    return [makers[i % 3](i // 3, size) for i in range(count)]


# ----------------------------------------------------------------------- variants
def save_jpeg(img: Image.Image, path: Path, quality: int = 92, **kw) -> Path:
    img.convert("RGB").save(path, "JPEG", quality=quality, **kw)
    return path


def resized(img: Image.Image, factor: float = 0.5) -> Image.Image:
    return img.resize((max(1, int(img.width * factor)), max(1, int(img.height * factor))), Image.Resampling.LANCZOS)


def cropped(img: Image.Image, frac: float = 0.02) -> Image.Image:
    dx, dy = int(img.width * frac), int(img.height * frac)
    return img.crop((dx, dy, img.width - dx, img.height - dy))


def brighter(img: Image.Image, factor: float = 1.10) -> Image.Image:
    return ImageEnhance.Brightness(img).enhance(factor)


def save_exif_rotated(img: Image.Image, path: Path, orientation: int = 6) -> Path:
    """Store pixels pre-rotated + EXIF orientation tag so the file *displays* like ``img``."""
    inverse = {
        2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_90, 7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_270,
    }[orientation]
    stored = img.convert("RGB").transpose(inverse)
    exif = Image.Exif()
    exif[0x0112] = orientation
    stored.save(path, "JPEG", quality=92, exif=exif)
    return path


def displayed(path: Path) -> Image.Image:
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGB")
