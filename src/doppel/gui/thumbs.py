"""Background thumbnail loading with an LRU cache.

All decoding happens on a QThreadPool; the UI thread only ever does cheap cache
lookups and QPixmap conversion. Thumbnails are EXIF-transposed, and JPEGs are
decoded with ``Image.draft`` (DCT scaling) so very large photos stay fast.
"""
from __future__ import annotations

import os
import warnings
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

try:  # HEIC from iPhones, if available
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - optional dependency
    pass

BUCKETS = (160, 320, 640, 1280, 2560)


def bucket_for(px: float) -> int:
    for b in BUCKETS:
        if px <= b:
            return b
    return BUCKETS[-1]


def load_qimage(path: str | Path, bucket: int) -> QImage | None:
    """Decode ``path`` to a QImage that fits inside bucket x bucket. Returns None on failure."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(path) as im:
                try:
                    im.draft("RGB", (bucket, bucket))
                except Exception:
                    pass
                im = ImageOps.exif_transpose(im)
                if im.width > bucket or im.height > bucket:
                    im.thumbnail((bucket, bucket), Image.Resampling.BILINEAR, reducing_gap=2.0)
                has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
                im = im.convert("RGBA" if has_alpha else "RGB")
                w, h = im.size
                data = im.tobytes()
                fmt = QImage.Format_RGBA8888 if has_alpha else QImage.Format_RGB888
                stride = w * (4 if has_alpha else 3)
                return QImage(data, w, h, stride, fmt).copy()
    except Exception:
        return None


class _Signals(QObject):
    done = Signal(str, int, QImage)  # path, bucket, image (null on failure)


class _Job(QRunnable):
    def __init__(self, path: str, bucket: int, signals: _Signals):
        super().__init__()
        self.path, self.bucket, self.signals = path, bucket, signals
        self.setAutoDelete(True)

    def run(self) -> None:
        img = load_qimage(self.path, self.bucket)
        try:
            self.signals.done.emit(self.path, self.bucket, img if img is not None else QImage())
        except RuntimeError:  # loader destroyed while running
            pass


class ThumbnailLoader(QObject):
    """``get()`` returns a cached pixmap or None and schedules a background load."""

    loaded = Signal(str, int)  # path, bucket

    def __init__(self, parent: QObject | None = None, max_bytes: int = 256 * 1024 * 1024, threads: int | None = None):
        super().__init__(parent)
        self._cache: OrderedDict[tuple[str, int], QPixmap] = OrderedDict()
        self._failed: set[str] = set()
        self._pending: set[tuple[str, int]] = set()
        self._bytes = 0
        self._max_bytes = max_bytes
        self._prio = 0
        self._signals = _Signals(self)
        self._signals.done.connect(self._on_done)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(threads or max(2, min(4, (os.cpu_count() or 2))))
        self.requests = 0  # for tests / diagnostics

    # -- public API -------------------------------------------------------
    def get(self, path: str | Path, px: float) -> QPixmap | None:
        """Cached pixmap for at least ``px`` physical pixels (largest side), else None (and a load starts)."""
        key = (str(path), bucket_for(px))
        pm = self._cache.get(key)
        if pm is not None:
            self._cache.move_to_end(key)
            return pm
        self._request(key)
        return None

    def best_available(self, path: str | Path) -> QPixmap | None:
        """Any cached size of this file (largest first) - used as a placeholder while a better one loads."""
        p = str(path)
        for b in reversed(BUCKETS):
            pm = self._cache.get((p, b))
            if pm is not None:
                return pm
        return None

    def failed(self, path: str | Path) -> bool:
        return str(path) in self._failed

    def prefetch(self, paths, px: float) -> None:
        for p in paths:
            self.get(p, px)

    def clear(self) -> None:
        self._pool.clear()
        self._cache.clear()
        self._pending.clear()
        self._failed.clear()
        self._bytes = 0

    def shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(1500)

    def wait_idle(self, timeout_ms: int = 5000) -> bool:
        return self._pool.waitForDone(timeout_ms)

    # -- internals --------------------------------------------------------
    def _request(self, key: tuple[str, int]) -> None:
        if key in self._pending or key[0] in self._failed:
            return
        self._pending.add(key)
        self.requests += 1
        self._prio += 1  # newest request first: what is on screen now wins over what scrolled past
        self._pool.start(_Job(key[0], key[1], self._signals), self._prio)

    def _on_done(self, path: str, bucket: int, img: QImage) -> None:
        key = (path, bucket)
        self._pending.discard(key)
        if img.isNull():
            self._failed.add(path)
        else:
            pm = QPixmap.fromImage(img)
            self._cache[key] = pm
            self._bytes += img.sizeInBytes()
            while self._bytes > self._max_bytes and len(self._cache) > 8:
                _, old = self._cache.popitem(last=False)
                self._bytes -= old.width() * old.height() * 4
        self.loaded.emit(path, bucket)
