"""Plain-language descriptions of low-level errors (no Pillow dependency)."""

from __future__ import annotations

import errno
import os


def describe_oserror(exc: BaseException) -> str:
    """Short, user-presentable reason for an OS-level failure."""
    if isinstance(exc, PermissionError):
        return "Permission denied"
    if isinstance(exc, FileNotFoundError):
        return "File not found (it may have been moved or deleted)"
    if isinstance(exc, IsADirectoryError):
        return "Is a folder, not a file"
    if isinstance(exc, OSError):
        if exc.errno == errno.ELOOP:
            return "Too many levels of links"
        if exc.errno == errno.ENAMETOOLONG:
            return "Path is too long"
        if exc.errno:
            return os.strerror(exc.errno) or str(exc)
        return str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {exc}"
