"""Fast, safe enumeration of image files."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .errors import describe_oserror
from .models import ScanCancelled

#: Lower-case extensions (without dot) that are treated as photos.
IMAGE_EXTS: tuple[str, ...] = ("jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif")
_EXT_SET = frozenset("." + e for e in IMAGE_EXTS)

#: Folder that contains this file is ignored (written by ``actions.remove`` into review folders
#: so moved duplicates are not found again).
REVIEW_MARKER = ".doppel_review"

_SKIP_DIRS = frozenset(
    {
        "$recycle.bin", "system volume information", ".trash", ".trashes", ".spotlight-v100",
        ".fseventsd", ".temporaryitems", "appdata", "node_modules", ".git", "__pycache__",
        ".thumbnails", "lost+found", "$winre_backup", "windows.old",
    }
)
_SKIP_DIR_SUFFIXES = (".photoslibrary", ".aplibrary", ".lrdata", ".app")
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_OFFLINE = 0x1000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400  # junctions, OneDrive placeholders, ...
_FILE_ATTRIBUTE_RECALL = 0x40000 | 0x400000  # RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS


def _skip_dir(name: str) -> bool:
    low = name.lower()
    return low in _SKIP_DIRS or low.startswith(".trash-") or low.endswith(_SKIP_DIR_SUFFIXES)


def _win_skip(attrs: int, is_dir: bool, skip_hidden: bool) -> bool:
    """Windows-only filters (``attrs`` is 0 elsewhere): hidden, junctions/reparse points and
    cloud-only placeholders (reading those would silently download them)."""
    if skip_hidden and attrs & _FILE_ATTRIBUTE_HIDDEN:
        return True
    if is_dir:
        return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)
    return bool(attrs & (_FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL))


def iter_entries(
    roots: Iterable[str | Path],
    include_subfolders: bool = True,
    skip_hidden: bool = True,
    on_error: Callable[[Path, str], None] | None = None,
    cancel: threading.Event | None = None,
) -> Iterator[tuple[Path, os.stat_result]]:
    """Like :func:`iter_images` but also yields each file's ``stat`` result."""
    seen_files: set[str] = set()
    seen_inodes: set[tuple[int, int]] = set()

    def report(p: Path, msg: str) -> None:
        if on_error is not None:
            on_error(p, msg)

    for root in roots:
        root_s = os.path.abspath(os.fspath(root))
        if not os.path.isdir(root_s):
            report(Path(root_s), "Folder not found" if not os.path.exists(root_s) else "Not a folder")
            continue
        stack = [root_s]
        while stack:
            if cancel is not None and cancel.is_set():
                raise ScanCancelled()
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError as exc:
                report(Path(current), describe_oserror(exc))
                continue
            if current != root_s and any(e.name == REVIEW_MARKER for e in entries):
                continue
            subdirs: list[str] = []
            for e in entries:
                name = e.name
                if name.startswith("._") or (skip_hidden and name.startswith(".")):
                    continue
                try:
                    if e.is_symlink():
                        continue  # never follow links: no loops, no double counting
                    if e.is_dir(follow_symlinks=False):
                        if include_subfolders and not _skip_dir(name):
                            attrs = getattr(e.stat(follow_symlinks=False), "st_file_attributes", 0)
                            if _win_skip(attrs, True, skip_hidden):
                                continue
                            subdirs.append(e.path)
                        continue
                    if os.path.splitext(name)[1].lower() not in _EXT_SET or not e.is_file(follow_symlinks=False):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError as exc:
                    report(Path(e.path), describe_oserror(exc))
                    continue
                if _win_skip(getattr(st, "st_file_attributes", 0), False, skip_hidden):
                    continue
                norm = os.path.normcase(e.path)
                if norm in seen_files:
                    continue
                seen_files.add(norm)
                if st.st_nlink > 1 and st.st_ino:  # hard link of a file already seen: same data
                    ident = (st.st_dev, st.st_ino)
                    if ident in seen_inodes:
                        continue
                    seen_inodes.add(ident)
                yield Path(e.path), st
            stack.extend(reversed(subdirs))


def iter_images(
    roots: list[Path],
    include_subfolders: bool = True,
    skip_hidden: bool = True,
    on_error: Callable[[Path, str], None] | None = None,
) -> Iterator[Path]:
    """Yield image files below ``roots`` (depth-first, sorted by name).

    Symbolic links and Windows junctions (to files or folders) are never followed, cloud-only
    OneDrive-style placeholders are skipped (not downloaded), hard links to a file
    already yielded are skipped, system/trash/cache folders and folders marked as
    Doppel review folders are skipped, and unreadable folders are reported through
    ``on_error(path, reason)`` instead of raising.
    """
    for path, _st in iter_entries(roots, include_subfolders, skip_hidden, on_error):
        yield path
