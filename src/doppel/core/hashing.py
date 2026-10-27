"""Content hashes: byte-level (blake2b) and perceptual (pHash / dHash / sharpness).

Perceptual pipeline (one decode per image):

1. open, remember the EXIF orientation and the displayed size;
2. for JPEG use ``Image.draft`` so libjpeg decodes at 1/2, 1/4 or 1/8 scale in
   grayscale (several times faster than a full decode);
3. convert to grayscale (alpha composited on white), shrink to at most
   ``WORK_SIZE`` px, apply the EXIF orientation to the small image;
4. pHash: 32x32 -> orthonormal 2-D DCT (a DCT matrix built with numpy, no scipy) ->
   top-left 8x8 block -> bit = coefficient > median of the 63 AC coefficients
   (the DC bit is always 0; the 32x32 input is tapered by a Tukey window first so
   small crops barely change the hash); dHash: 9x8 -> horizontal gradient signs;
   sharpness: variance of the Laplacian of the small grayscale image;
5. a 64x64 grayscale thumbnail plus a "graphic" score (share of pixels in the single most
   common 4-level gray band: ~0.4-0.9 for screenshots/documents, ~0.05 for photos). Hash
   matches are only candidates; ``cluster.confirm_pairs`` compares the thumbnails, strictly
   for graphic images, whose coarse hashes collide easily (same layout, different text).
"""

from __future__ import annotations

import contextlib
import hashlib
import threading
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image, UnidentifiedImageError

from .errors import describe_oserror
from .metadata import read_exif, read_orientation
from .models import ScanCancelled

# Bumped whenever hash output changes; the cache is wiped when it differs.
HASH_VERSION = 2

PARTIAL_BYTES = 64 * 1024
WORK_SIZE = 256
FLAT_STD = 0.75  # 32x32 grayscale std below this => "flat", not comparable
THUMB_SIZE = 64  # side of the structural thumbnail used to confirm candidate pairs

Image.init()  # load every plugin once so worker threads never race on registration

try:  # optional HEIC/HEIF support
    import pillow_heif  # type: ignore[import-not-found]

    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except Exception:  # pragma: no cover - depends on environment
    HEIF_AVAILABLE = False

_BOMB_ERRORS = (Image.DecompressionBombWarning, Image.DecompressionBombError)


# --------------------------------------------------------------------------- byte hashes
def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ScanCancelled()


def file_sha(path: str | Path, chunk: int = 1 << 20, cancel: threading.Event | None = None) -> str:
    """Full-content blake2b (hex). ``cancel`` aborts between chunks."""
    h = hashlib.blake2b(digest_size=32)
    buf = bytearray(chunk)
    view = memoryview(buf)
    with open(path, "rb", buffering=0) as f:
        while True:
            _check(cancel)
            n = f.readinto(buf)
            if not n:
                break
            h.update(view[:n])
    return h.hexdigest()


def partial_sha(path: str | Path, nbytes: int = PARTIAL_BYTES, cancel: threading.Event | None = None) -> str:
    """Cheap pre-filter hash of the first + last ``nbytes`` of a file.

    Files of at most ``2 * nbytes`` are hashed completely, so for them the result
    equals :func:`file_sha` and can be used as the full hash.
    """
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        if size <= 2 * nbytes:
            f.seek(0)
            h = hashlib.blake2b(digest_size=32)
            h.update(f.read())
            return h.hexdigest()
        h = hashlib.blake2b(digest_size=32)
        _check(cancel)
        f.seek(0)
        h.update(f.read(nbytes))
        f.seek(size - nbytes)
        h.update(f.read(nbytes))
        h.update(size.to_bytes(8, "little"))
        return h.hexdigest()


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two hashes."""
    return (a ^ b).bit_count()


# --------------------------------------------------------------------------- perceptual
def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    m = np.cos(np.pi * (2 * i + 1) * k / (2 * n)) * np.sqrt(2.0 / n)
    m[0, :] = np.sqrt(1.0 / n)
    return m


def _tukey(n: int, alpha: float) -> np.ndarray:
    """Tukey (tapered-cosine) window of length ``n``."""
    w = np.ones(n)
    m = int(alpha * (n - 1) / 2)
    for i in range(m + 1):
        w[i] = w[n - 1 - i] = 0.5 * (1 + np.cos(np.pi * (2 * i / (alpha * (n - 1)) - 1)))
    return w


_DCT32 = _dct_matrix(32)
_LOW = 8
# Tapering the borders before the DCT makes the hash far less sensitive to small
# crops (2% crop: 87% -> 100% of test images within distance 8).
_WIN2D = np.outer(_tukey(32, 0.5), _tukey(32, 0.5))


def phash_from_gray(small: np.ndarray) -> int:
    """pHash of a 32x32 float grayscale array."""
    coeffs = _DCT32 @ ((small - small.mean()) * _WIN2D) @ _DCT32.T
    low = coeffs[:_LOW, :_LOW].ravel()
    med = np.median(low[1:])
    bits = low > med
    bits[0] = False
    return _bits_to_int(bits)


def dhash_from_gray(small: np.ndarray) -> int:
    """dHash of a 8-row x 9-column float grayscale array."""
    bits = (small[:, :-1] > small[:, 1:]).ravel()
    return _bits_to_int(bits)


def _bits_to_int(bits: np.ndarray) -> int:
    value = 0
    for b in bits.tolist():
        value = (value << 1) | int(b)
    return value


def sharpness_of(gray: np.ndarray) -> float:
    """Variance of the Laplacian (higher = sharper)."""
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    g = gray.astype(np.float32, copy=False)
    lap = -4.0 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


_ORIENT_OPS = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def _to_gray(img: Image.Image) -> Image.Image:
    """Grayscale ('L') copy of any Pillow image; alpha is composited on white."""
    mode = img.mode
    if mode == "L":
        return img.copy()  # the source is closed after decoding
    if mode in ("I;16", "I;16L", "I;16B", "I;16N", "I", "F"):
        arr = np.asarray(img, dtype=np.float64)
        if mode.startswith("I;16"):
            arr = arr / 257.0
        else:
            mx = float(arr.max()) if arr.size else 0.0
            if mx > 255.0:
                arr = arr * (255.0 / mx)
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "L")
    if mode in ("RGBA", "LA", "PA") or (mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        return bg.convert("L")
    return img.convert("L")


@dataclass(frozen=True)
class ImageAnalysis:
    """Result of decoding one image once."""

    phash: int
    dhash: int
    sharpness: float
    width: int
    height: int
    format: str
    taken: datetime | None
    camera: str | None
    flat: bool  # too uniform for perceptual comparison
    thumb: bytes = b""  # THUMB_SIZE x THUMB_SIZE uint8 grayscale, row-major
    graphic: float = 0.0  # share of pixels in the dominant gray band (0..1)


def _format_name(img: Image.Image) -> str:
    fmt = (img.format or "").upper()
    return {"MPO": "JPEG", "HEIF": "HEIC"}.get(fmt, fmt or "UNKNOWN")


def analyze_image(path: str | Path) -> ImageAnalysis:
    """Decode ``path`` once and return hashes, size, format and EXIF data.

    Raises on unreadable files (see :func:`describe_error`). Without the
    ``bomb_guard`` filter Pillow only *warns* for images above ``MAX_IMAGE_PIXELS``.
    """
    with Image.open(path) as img:
        fmt = _format_name(img)
        orientation = read_orientation(img)
        taken, camera = read_exif(img)
        width, height = img.size
        if orientation >= 5:
            width, height = height, width
        if img.format in ("JPEG", "MPO"):
            img.draft("L", (WORK_SIZE, WORK_SIZE))
        img.load()
        gray = _to_gray(img)
    if max(gray.size) > WORK_SIZE:
        gray.thumbnail((WORK_SIZE, WORK_SIZE), Image.Resampling.LANCZOS, reducing_gap=2.0)
    op = _ORIENT_OPS.get(orientation)
    if op is not None:
        gray = gray.transpose(op)
    work = np.asarray(gray, dtype=np.float64)
    small = np.asarray(gray.resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64)
    d_small = np.asarray(gray.resize((9, 8), Image.Resampling.LANCZOS), dtype=np.float64)
    thumb = np.asarray(gray.resize((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS), dtype=np.uint8)
    bands = np.asarray(gray.histogram(), dtype=np.int64).reshape(64, 4).sum(axis=1)
    return ImageAnalysis(
        phash=phash_from_gray(small),
        dhash=dhash_from_gray(d_small),
        sharpness=sharpness_of(work),
        width=int(width),
        height=int(height),
        format=fmt,
        taken=taken,
        camera=camera,
        flat=bool(small.std() < FLAT_STD),
        thumb=thumb.tobytes(),
        graphic=float(bands.max() / max(1, bands.sum())),
    )


def image_hashes(path: str | Path) -> tuple[int, int, float, int, int, str]:
    """``(phash, dhash, sharpness, width, height, format)`` for an image file."""
    a = analyze_image(path)
    return a.phash, a.dhash, a.sharpness, a.width, a.height, a.format


@contextlib.contextmanager
def bomb_guard() -> Iterator[None]:
    """Turn Pillow's DecompressionBombWarning into an exception while active.

    Warning filters are process-global, so use it around a whole scan (from one
    thread), not per image.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        yield


def describe_error(exc: BaseException, path: str | Path | None = None) -> str:
    """Plain-language reason an image could not be read."""
    if isinstance(exc, _BOMB_ERRORS):
        return "Image is too large to scan safely"
    if isinstance(exc, UnidentifiedImageError):
        if path is not None and Path(path).suffix.lower() in (".heic", ".heif") and not HEIF_AVAILABLE:
            return "HEIC/HEIF photos need the optional 'pillow-heif' package"
        return "Not a valid image (damaged or wrong file type)"
    if isinstance(exc, OSError) and not exc.errno:
        text = str(exc).lower()
        if "truncated" in text or "broken" in text or "corrupt" in text or "decode" in text:
            return "Image file is damaged or incomplete"
        return "Image file is damaged or unreadable"
    if isinstance(exc, (ValueError, SyntaxError, EOFError, MemoryError, OverflowError)):
        return "Image file is damaged or unreadable"
    if isinstance(exc, OSError):
        return describe_oserror(exc)
    return f"{exc.__class__.__name__}: {exc}"


def is_permanent_error(exc: BaseException) -> bool:
    """True if retrying the same unchanged file is pointless (safe to cache)."""
    if isinstance(exc, OSError) and exc.errno and not isinstance(exc, _BOMB_ERRORS):
        return False
    return not isinstance(exc, (MemoryError, ScanCancelled))
