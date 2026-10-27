"""Which photo(s) of a group to keep."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

from .models import DuplicateGroup, MatchKind, PhotoInfo


class KeepRule(Enum):
    BEST_QUALITY = "best"
    OLDEST = "oldest"
    NEWEST = "newest"
    LARGEST_FILE = "largest"
    SHORTEST_PATH = "path"


_SUFFIX_NUM = re.compile(r"[-_ ]\d{1,2}$")  # "photo-1", "IMG_0001-1" (but not IMG_0001 or a date)

# Patterns typical of copies made by file managers, browsers and cloud sync.
_COPY_PATTERNS = (
    re.compile(r"\(\s*\d+\s*\)\s*$"),                       # "IMG (1)", "IMG (2)"
    re.compile(r"(?<![\w])copy(?![\w])", re.IGNORECASE),     # "Copy of IMG", "IMG - Copy", "IMG_copy"
    re.compile(r"(?<![\w])copy\s*\d*\s*$", re.IGNORECASE),   # trailing "copy 2"
    _SUFFIX_NUM,
    re.compile(r"[-_ ]copy[-_ ]?\d*$", re.IGNORECASE),       # "photo_copy", "photo-copy2"
)


_DATE_END = re.compile(r"\d{4}[-_.]\d{1,2}[-_.]\d{1,2}$")  # "2023-05-12" is a date, not "copy 12"


def name_penalty(path: str | Path) -> int:
    """How much a file name looks like a copy (0 = looks original)."""
    stem = Path(path).stem
    score = 0
    for pat in _COPY_PATTERNS:
        if pat.search(stem) and not (pat is _SUFFIX_NUM and _DATE_END.search(stem)):
            score += 1
    return score


def _age(p: PhotoInfo) -> tuple[float, float]:
    ts = p.mtime
    if p.taken is not None:
        try:
            ts = p.taken.timestamp()
        except (OverflowError, OSError, ValueError):
            pass
    return ts, p.mtime


def _has_exif(p: PhotoInfo) -> int:
    return 1 if (p.taken is not None or p.camera) else 0


def _tail(p: PhotoInfo) -> tuple:
    return (name_penalty(p.path), len(str(p.path)), str(p.path))


def _key(p: PhotoInfo, rule: KeepRule, exact: bool) -> tuple:
    if rule is KeepRule.BEST_QUALITY:
        if exact:  # identical content: look for the original, then the oldest, then the shortest path
            return (name_penalty(p.path), _age(p), len(str(p.path)), str(p.path))
        return (
            -(p.width * p.height),
            -(p.sharpness if p.sharpness is not None else -1.0),
            -p.size,
            -_has_exif(p),
            *_tail(p),
        )
    if rule is KeepRule.OLDEST:
        return (_age(p), *_tail(p))
    if rule is KeepRule.NEWEST:
        a = _age(p)
        return ((-a[0], -a[1]), *_tail(p))
    if rule is KeepRule.LARGEST_FILE:
        return (-p.size, _age(p), *_tail(p))
    if rule is KeepRule.SHORTEST_PATH:
        return (len(str(p.path)), name_penalty(p.path), _age(p), str(p.path))
    raise ValueError(f"unknown rule {rule!r}")


def best_photo(photos: list[PhotoInfo], rule: KeepRule = KeepRule.BEST_QUALITY, exact: bool = False) -> PhotoInfo:
    """The single photo ``rule`` would keep (deterministic)."""
    if not photos:
        raise ValueError("empty group")
    return min(photos, key=lambda p: _key(p, rule, exact))


def recommend(group: DuplicateGroup, rule: KeepRule = KeepRule.BEST_QUALITY) -> set[Path]:
    """Exactly one path to keep for ``group`` under ``rule``.

    BEST_QUALITY (look-alikes): most megapixels, then sharpness, file size, has EXIF,
    fewest copy-like name markers, shortest path. For EXACT groups (identical bytes)
    quality is meaningless, so the original-looking name wins (names containing
    "(1)", "copy", "Copy of", "-1"/"_1" suffixes lose), then the oldest taken/modified
    time, then the shortest path.
    """
    return {best_photo(group.photos, rule, group.kind is MatchKind.EXACT).path}
