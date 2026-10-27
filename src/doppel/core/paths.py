"""Per-user cache/data directories (tiny platformdirs replacement).

Override with the ``DOPPEL_CACHE_DIR`` / ``DOPPEL_DATA_DIR`` environment variables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def user_cache_dir() -> Path:
    """Directory for disposable data (the hash cache)."""
    override = os.environ.get("DOPPEL_CACHE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(_home() / "AppData" / "Local")
        return Path(base) / "Doppel"
    if sys.platform == "darwin":
        return _home() / "Library" / "Caches" / "Doppel"
    base = os.environ.get("XDG_CACHE_HOME") or str(_home() / ".cache")
    return Path(base) / "doppel"


def user_data_dir() -> Path:
    """Directory for durable data (the action log)."""
    override = os.environ.get("DOPPEL_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(_home() / "AppData" / "Local")
        return Path(base) / "Doppel"
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / "Doppel"
    base = os.environ.get("XDG_DATA_HOME") or str(_home() / ".local" / "share")
    return Path(base) / "doppel"
