"""Plain data types shared by the whole engine (no Qt, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class ScanCancelled(Exception):
    """Raised by :func:`doppel.core.finder.scan` when the cancel event is set."""


@dataclass(frozen=True)
class PhotoInfo:
    """Everything the engine knows about one image file.

    ``sha``/``phash``/``dhash``/``sharpness`` are ``None`` when not computed (or, for
    the perceptual hashes, when the image is too flat to be compared meaningfully).
    ``width``/``height`` are the *displayed* size (EXIF orientation applied).
    """

    path: Path
    size: int
    mtime: float
    width: int
    height: int
    format: str
    taken: datetime | None = None
    camera: str | None = None
    sha: str | None = None
    phash: int | None = None
    dhash: int | None = None
    sharpness: float | None = None

    @property
    def megapixels(self) -> float:
        return (self.width * self.height) / 1_000_000.0


class MatchKind(Enum):
    EXACT = "exact"
    SIMILAR = "similar"


@dataclass
class DuplicateGroup:
    """A set of photos that are duplicates of each other.

    EXACT groups hold byte-identical files. SIMILAR groups hold 2+ *distinct-content*
    photos; an exact-copy set takes part in a SIMILAR group through a single
    representative only (see :func:`doppel.core.finder.scan`).
    """

    id: int
    kind: MatchKind
    photos: list[PhotoInfo]
    keep: set[Path] = field(default_factory=set)
    similarity: float = 1.0  # 1.0 for exact; else 1 - mean_hamming / 64

    @property
    def reclaimable_bytes(self) -> int:
        """Bytes freed if every photo not in ``keep`` is removed."""
        return sum(p.size for p in self.photos if p.path not in self.keep)

    @property
    def total_bytes(self) -> int:
        return sum(p.size for p in self.photos)


@dataclass
class ScanResult:
    """Outcome of a scan.

    ``errors`` lists (path, plain-language reason) for files that could not be read.
    ``scanned`` is the number of image files examined (those that passed the minimum
    size filter). ``elapsed`` is wall-clock seconds.
    """

    groups: list[DuplicateGroup] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)
    scanned: int = 0
    elapsed: float = 0.0

    @property
    def reclaimable_bytes(self) -> int:
        return sum(g.reclaimable_bytes for g in self.groups)
