"""EXIF helpers. Everything here is best-effort and never raises."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

EXIF_IFD = 0x8769
TAG_ORIENTATION = 0x0112
TAG_MAKE = 0x010F
TAG_MODEL = 0x0110
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME_DIGITIZED = 0x9004

_DT_RE = re.compile(r"^\s*(\d{4})[:\-/](\d{2})[:\-/](\d{2})[ T](\d{2}):(\d{2}):(\d{2})")


def _clean(value: Any) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    if not isinstance(value, str):
        return None
    value = value.replace("\x00", "").strip()
    return value or None


def parse_exif_datetime(value: Any) -> datetime | None:
    """Parse ``YYYY:MM:DD HH:MM:SS`` (and close variants); None if invalid/zeroed."""
    text = _clean(value)
    if not text:
        return None
    m = _DT_RE.match(text)
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups()))
    except ValueError:  # e.g. 0000:00:00 00:00:00
        return None


def read_orientation(img: Any) -> int:
    """EXIF orientation 1..8 (1 when absent/invalid)."""
    try:
        value = int(img.getexif().get(TAG_ORIENTATION, 1))
    except Exception:
        return 1
    return value if 1 <= value <= 8 else 1


def read_exif(img: Any) -> tuple[datetime | None, str | None]:
    """Return ``(taken, camera)`` from an opened Pillow image.

    ``taken`` is DateTimeOriginal (falling back to DateTimeDigitized); ``camera`` is
    "Make Model" with the make not repeated when the model already starts with it.
    """
    try:
        exif = img.getexif()
        if not exif:
            return None, None
    except Exception:
        return None, None

    taken: datetime | None = None
    try:
        ifd = exif.get_ifd(EXIF_IFD)
    except Exception:
        ifd = {}
    for source in (ifd, exif):
        for tag in (TAG_DATETIME_ORIGINAL, TAG_DATETIME_DIGITIZED):
            try:
                taken = parse_exif_datetime(source.get(tag))
            except Exception:
                taken = None
            if taken:
                break
        if taken:
            break

    camera: str | None = None
    try:
        make = _clean(exif.get(TAG_MAKE))
        model = _clean(exif.get(TAG_MODEL))
        if make and model:
            camera = model if model.lower().startswith(make.lower()) else f"{make} {model}"
        else:
            camera = model or make
    except Exception:
        camera = None
    return taken, camera
