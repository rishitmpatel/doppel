"""Background work: scanning, removing and undoing run off the UI thread in QThreads."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot


class _Worker(QObject):
    progress = Signal(object)
    result = Signal(object)
    cancelled = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(self, fn: Callable[..., Any], cancel_exc: type[BaseException] | None = None):
        super().__init__()
        self._fn = fn
        self._cancel_exc = cancel_exc
        self.cancel_event = threading.Event()
        self._last_emit = 0.0
        self._last_stage: Any = None

    def emit_progress(self, payload: Any, key: Any = None, min_interval: float = 0.05) -> None:
        """Throttled (~20 Hz) progress; always lets stage changes and completion through."""
        now = time.monotonic()
        done = getattr(payload, "done", None)
        total = getattr(payload, "total", None)
        final = done is not None and total is not None and total > 0 and done >= total
        if key != self._last_stage or final or now - self._last_emit >= min_interval:
            self._last_stage = key
            self._last_emit = now
            self.progress.emit(payload)

    @Slot()
    def run(self) -> None:
        try:
            res = self._fn(self)
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.result.emit(res)
        except BaseException as exc:  # noqa: BLE001 - report everything to the UI
            if self._cancel_exc is not None and isinstance(exc, self._cancel_exc):
                self.cancelled.emit()
            elif self.cancel_event.is_set() and type(exc).__name__ == "ScanCancelled":
                self.cancelled.emit()
            else:
                self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class Job(QObject):
    """Owns a QThread + worker. ``start()`` runs ``fn(worker)`` in the background."""

    progress = Signal(object)
    result = Signal(object)
    cancelled = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(self, fn: Callable[[_Worker], Any], cancel_exc: type[BaseException] | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = _Worker(fn, cancel_exc)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.result.connect(self.result)
        self._worker.cancelled.connect(self.cancelled)
        self._worker.failed.connect(self.failed)
        self._worker.finished.connect(self._on_finished)
        self._running = False

    @property
    def worker(self) -> _Worker:
        return self._worker

    @property
    def cancel_event(self) -> threading.Event:
        return self._worker.cancel_event

    def start(self) -> None:
        self._running = True
        self._thread.start()

    def cancel(self) -> None:
        self._worker.cancel_event.set()

    def is_running(self) -> bool:
        return self._running

    def wait(self, ms: int = 5000) -> bool:
        return self._thread.wait(ms)

    def _on_finished(self) -> None:
        self._running = False
        self._thread.quit()
        self.finished.emit()


# ---------------------------------------------------------------------------
def make_scan_job(options, cache=None, parent: QObject | None = None) -> Job:
    from doppel.core.finder import scan
    from doppel.core.models import ScanCancelled

    def run(w: _Worker):
        def on_progress(p):
            w.emit_progress(p, key=getattr(p, "stage", None))

        kwargs: dict[str, Any] = {"progress": on_progress, "cancel": w.cancel_event}
        if cache is not None:
            kwargs["cache"] = cache
        return scan(options, **kwargs)

    return Job(run, cancel_exc=ScanCancelled, parent=parent)


def make_remove_job(paths: list[Path], mode, review_dir: Path | None, parent: QObject | None = None) -> Job:
    from doppel.core.actions import remove

    def run(w: _Worker):
        total = len(paths)
        state = {"done": 0}

        def on_progress(*args):
            # Tolerant of (done, total) or a single ActionRecord/Progress-like argument.
            done = None
            if len(args) >= 2 and isinstance(args[0], int):
                done, tot = args[0], args[1]
            else:
                state["done"] += 1
                done, tot = state["done"], total
            w.emit_progress(_Count(done, tot), key="remove")

        kwargs: dict[str, Any] = {"progress": on_progress}
        if review_dir is not None:
            kwargs["review_dir"] = review_dir
        return remove(paths, mode, **kwargs)

    return Job(run, parent=parent)


def make_undo_job(records, parent: QObject | None = None) -> Job:
    from doppel.core.actions import undo

    def run(w: _Worker):
        return undo(records)

    return Job(run, parent=parent)


class _Count:
    __slots__ = ("done", "total")

    def __init__(self, done: int, total: int):
        self.done, self.total = done, total
