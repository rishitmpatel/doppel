"""Removing duplicates safely: Recycle Bin / Trash, or MOVE to a review folder (undoable).

Nothing here ever deletes permanently. Every action is appended as a JSON line to
``actions.jsonl`` in the app data dir (failures to log never break an action).
"""

from __future__ import annotations

import contextlib
import inspect
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Collection, Iterable, Sequence

import send2trash

from .errors import describe_oserror
from .models import DuplicateGroup
from .paths import user_data_dir
from .scanner import REVIEW_MARKER

_SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}$")
_LOG_LOCK = threading.Lock()


class RemoveMode(Enum):
    TRASH = "trash"
    MOVE = "move"


@dataclass
class ActionRecord:
    original: Path
    destination: Path | None
    mode: RemoveMode
    ok: bool
    error: str | None = None


class _Refused(Exception):
    """A path we deliberately do not touch (message is user-facing)."""


class UnsafeRemovalError(ValueError):
    """A removal plan would delete every photo of a group."""


def default_log_path() -> Path:
    return user_data_dir() / "actions.jsonl"


# --------------------------------------------------------------------------- planning
def plan_removal(groups: Iterable[DuplicateGroup], remove: Collection[Path] | None = None) -> list[Path]:
    """Paths to remove for ``groups``; raises :class:`UnsafeRemovalError` if unsafe.

    By default a group contributes every photo not in its ``keep`` set (so an empty
    ``keep`` is refused). Pass ``remove`` to plan an explicit selection instead.
    Groups that share files (an exact set and the look-alike group it represents) are
    checked together: at least one file of each connected cluster must survive, and
    a group may never be left with no member at all unless another group sharing
    its files keeps one. The result has no duplicates and a stable order.
    """
    groups = list(groups)
    removal: dict[Path, None] = {}
    explicit = {Path(p) for p in remove} if remove is not None else None
    for g in groups:
        members = [p.path for p in g.photos]
        if explicit is None:
            if not g.keep or not (g.keep & set(members)):
                raise UnsafeRemovalError(f"Group {g.id} has no photo marked to keep.")
            doomed = [m for m in members if m not in g.keep]
        else:
            doomed = [m for m in members if m in explicit]
        for p in doomed:
            removal.setdefault(p, None)
    doomed_set = set(removal)

    # connected clusters of groups that share files
    parent = list(range(len(groups)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[Path, int] = {}
    for gi, g in enumerate(groups):
        for p in g.photos:
            if p.path in owner:
                parent[find(gi)] = find(owner[p.path])
            else:
                owner[p.path] = gi
    clusters: dict[int, list[int]] = {}
    for gi in range(len(groups)):
        clusters.setdefault(find(gi), []).append(gi)
    for gis in clusters.values():
        paths = {p.path for gi in gis for p in groups[gi].photos}
        if paths and paths <= doomed_set:
            first = groups[gis[0]]
            raise UnsafeRemovalError(
                f"This would remove every photo in group {first.id}; at least one must be kept."
            )
    return list(removal)


# --------------------------------------------------------------------------- logging
def _log(entries: Sequence[dict[str, Any]], log_path: Path | None) -> None:
    try:
        path = Path(log_path) if log_path is not None else default_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
        with _LOG_LOCK, open(path, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def _entry(action: str, rec: ActionRecord, session: str) -> dict[str, Any]:
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "session": session,
        "mode": rec.mode.value,
        "original": str(rec.original),
        "destination": str(rec.destination) if rec.destination else None,
        "ok": rec.ok,
        "error": rec.error,
    }


def read_log(log_path: Path | None = None) -> list[dict[str, Any]]:
    """All logged actions, oldest first (unreadable lines are skipped)."""
    path = Path(log_path) if log_path is not None else default_log_path()
    out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                with contextlib.suppress(ValueError):
                    out.append(json.loads(line))
    except OSError:
        pass
    return out


def _adapt_progress(progress: Callable[..., None] | None) -> Callable[[int, int, str], None]:
    """Accept ``progress(done, total)``, ``progress(done, total, current)`` or ``progress(Progress)``."""
    if progress is None:
        return lambda done, total, current: None
    try:
        params = [
            p for p in inspect.signature(progress).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        variadic = any(p.kind is p.VAR_POSITIONAL for p in inspect.signature(progress).parameters.values())
    except (TypeError, ValueError):
        params, variadic = [None, None], False
    n = len(params)
    if n == 1 and not variadic:
        from .finder import Progress

        return lambda d, t, c: progress(Progress("Removing", d, t, c))
    if n >= 3 or variadic:
        return lambda d, t, c: progress(d, t, c)
    return lambda d, t, c: progress(d, t)


# --------------------------------------------------------------------------- remove / undo
def _trash(path: Path) -> None:
    fn = send2trash if callable(send2trash) else send2trash.send2trash
    fn(str(path))


def _anchor_name(p: Path) -> str:
    drive = p.drive
    if drive:
        return re.sub(r"[:\\/]+", "_", drive).strip("_") or "drive"
    return "root"


def _reserve_unique(dest: Path) -> Path:
    """Atomically create an empty placeholder at ``dest`` or ``dest (n)``; never overwrites."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    while True:
        cand = dest if n == 0 else dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        try:
            fd = os.open(cand, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            n += 1
            continue
        os.close(fd)
        return cand


def _move_unique(src: Path, dest: Path) -> Path:
    placeholder = _reserve_unique(dest)
    try:
        shutil.move(str(src), str(placeholder))
    except BaseException:
        if os.path.lexists(src):  # source intact: our placeholder/partial copy is garbage
            with contextlib.suppress(OSError):
                placeholder.unlink()
        raise
    return placeholder


def remove(
    paths: Iterable[Path],
    mode: RemoveMode,
    review_dir: Path | None = None,
    progress: Callable[..., None] | None = None,
    log_path: Path | None = None,
) -> list[ActionRecord]:
    """Remove files; one :class:`ActionRecord` per input path, in order.

    TRASH sends files to the OS Recycle Bin/Trash. MOVE moves them under
    ``review_dir/<YYYY-MM-DD_HHMM>/<drive-or-"root">/<original relative path>``,
    never overwriting (a numeric suffix is added on collision). Only regular files
    and symlinks are touched; missing files and folders are reported, not raised.
    ``progress(done, total)`` is called after each file.
    """
    items = [Path(p) for p in paths]
    mode = RemoveMode(mode)
    if mode is RemoveMode.MOVE and review_dir is None:
        raise ValueError("review_dir is required for RemoveMode.MOVE")
    report = _adapt_progress(progress)
    session = datetime.now().strftime("%Y-%m-%d_%H%M")
    session_dir: Path | None = None
    if mode is RemoveMode.MOVE:
        review_root = Path(review_dir)  # type: ignore[arg-type]
        session_dir = review_root / session
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            (review_root / REVIEW_MARKER).touch(exist_ok=True)
        except OSError as exc:
            msg = f"Could not create the review folder: {exc.strerror or exc}"
            recs = [ActionRecord(p, None, mode, False, msg) for p in items]
            _log([_entry("remove", r, session) for r in recs], log_path)
            return recs

    records: list[ActionRecord] = []
    total = len(items)
    for i, src in enumerate(items):
        try:
            if not os.path.lexists(src):
                raise _Refused("File not found (it may have been moved or deleted)")
            if os.path.isdir(src) and not os.path.islink(src):
                raise _Refused("Is a folder, not a file")
            if mode is RemoveMode.TRASH:
                _trash(src)
                rec = ActionRecord(src, None, mode, True)
            else:
                absolute = Path(os.path.abspath(src))
                rel = absolute.relative_to(absolute.anchor)
                dest = _move_unique(src, session_dir / _anchor_name(absolute) / rel)  # type: ignore[operator]
                rec = ActionRecord(src, dest, mode, True)
        except Exception as exc:
            msg = str(exc) if isinstance(exc, _Refused) else describe_oserror(exc)
            rec = ActionRecord(src, None, mode, False, msg)
        records.append(rec)
        report(i + 1, total, str(src))
    _log([_entry("remove", r, session) for r in records], log_path)
    return records


def _prune_empty_dirs(start: Path) -> None:
    """Remove now-empty folders from ``start`` up to and including the session folder."""
    cur = start
    while True:
        try:
            cur.rmdir()
        except OSError:
            return
        if _SESSION_RE.match(cur.name) or cur.parent == cur:
            return
        cur = cur.parent


def undo(records: Iterable[ActionRecord], log_path: Path | None = None) -> list[ActionRecord]:
    """Restore MOVEd files to their original location; one result record per input.

    Never overwrites: if something now exists at the original path the file is
    restored beside it with a numeric suffix (see the returned ``destination``).
    Trashed files cannot be restored by Doppel - the returned record has ``ok=False``
    and tells the user to use the Recycle Bin / Trash.
    """
    session = datetime.now().strftime("%Y-%m-%d_%H%M")
    out: list[ActionRecord] = []
    for rec in records:
        if rec.mode is RemoveMode.TRASH:
            res = ActionRecord(rec.original, rec.destination, rec.mode, False,
                               "Restore this file from the Recycle Bin / Trash.")
        elif not rec.ok or rec.destination is None:
            res = ActionRecord(rec.original, rec.destination, rec.mode, False, "Nothing to restore (it was not moved).")
        elif not os.path.lexists(rec.destination):
            res = ActionRecord(rec.original, rec.destination, rec.mode, False,
                               "The moved file is no longer in the review folder.")
        else:
            try:
                restored = _move_unique(rec.destination, rec.original)
                _prune_empty_dirs(rec.destination.parent)
                res = ActionRecord(rec.original, restored, rec.mode, True)
            except Exception as exc:
                res = ActionRecord(rec.original, rec.destination, rec.mode, False, describe_oserror(exc))
        out.append(res)
    _log([_entry("undo", r, session) for r in out], log_path)
    return out
