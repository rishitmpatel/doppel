from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path_factory, monkeypatch):
    """Never touch the real user cache/data dirs."""
    base = tmp_path_factory.mktemp("appdirs")
    monkeypatch.setenv("DOPPEL_CACHE_DIR", str(base / "cache"))
    monkeypatch.setenv("DOPPEL_DATA_DIR", str(base / "data"))


@pytest.fixture
def trash(monkeypatch):
    """Replace send2trash so nothing is really trashed; returns the list of paths 'trashed'."""
    import os

    import send2trash

    calls: list[str] = []

    def fake(path):
        calls.append(str(path))
        os.remove(path)  # emulate "gone from the folder"

    monkeypatch.setattr(send2trash, "send2trash", fake)
    return calls
