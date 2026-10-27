from __future__ import annotations

import os
import threading

import pytest

from doppel.core import scanner
from doppel.core.models import ScanCancelled
from doppel.core.scanner import IMAGE_EXTS, REVIEW_MARKER, iter_images


def touch(p, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def names(paths, root):
    return sorted(str(p.relative_to(root)) for p in paths)


def test_extensions_case_insensitive(tmp_path):
    for n in ["a.jpg", "b.JPEG", "c.Png", "d.gif", "e.bmp", "f.tif", "g.TIFF", "h.webp", "i.heic", "j.HEIF",
              "k.txt", "l.jpg.bak", "m.mp4", "noext"]:
        touch(tmp_path / n)
    got = names(iter_images([tmp_path]), tmp_path)
    assert got == ["a.jpg", "b.JPEG", "c.Png", "d.gif", "e.bmp", "f.tif", "g.TIFF", "h.webp", "i.heic", "j.HEIF"]
    assert set(IMAGE_EXTS) == {"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif"}


def test_subfolders_flag_and_overlapping_roots(tmp_path):
    touch(tmp_path / "top.jpg")
    touch(tmp_path / "sub" / "deep" / "x.jpg")
    assert names(iter_images([tmp_path], include_subfolders=False), tmp_path) == ["top.jpg"]
    both = list(iter_images([tmp_path, tmp_path / "sub"]))
    assert len(both) == 2 and len(set(both)) == 2  # nested root does not yield files twice


def test_hidden_and_system_folders_skipped(tmp_path):
    touch(tmp_path / "ok.jpg")
    touch(tmp_path / ".hidden.jpg")
    touch(tmp_path / "._ok.jpg")
    touch(tmp_path / ".cache" / "a.jpg")
    for d in ["$RECYCLE.BIN", "System Volume Information", ".Trash", ".Trash-1000", "AppData", ".git",
              "Photos Library.photoslibrary", "node_modules"]:
        touch(tmp_path / d / "junk.jpg")
    assert names(iter_images([tmp_path]), tmp_path) == ["ok.jpg"]
    shown = names(iter_images([tmp_path], skip_hidden=False), tmp_path)
    assert ".hidden.jpg" in shown and ".cache/a.jpg" in shown and "._ok.jpg" not in shown
    assert not any("Trash" in n or "RECYCLE" in n or "AppData" in n for n in shown)


def test_review_folders_are_skipped_but_not_when_chosen_as_root(tmp_path):
    touch(tmp_path / "keep.jpg")
    touch(tmp_path / "Review" / REVIEW_MARKER, b"")
    touch(tmp_path / "Review" / "2026" / "moved.jpg")
    assert names(iter_images([tmp_path]), tmp_path) == ["keep.jpg"]
    assert names(iter_images([tmp_path / "Review"]), tmp_path) == ["Review/2026/moved.jpg"]


def test_symlinks_not_followed_and_loops_terminate(tmp_path):
    real = touch(tmp_path / "real" / "a.jpg")
    os.symlink(real, tmp_path / "link.jpg")                   # file symlink
    os.symlink(tmp_path / "real", tmp_path / "dirlink")       # dir symlink
    os.symlink(tmp_path, tmp_path / "real" / "loop")          # loop back to the root
    got = names(iter_images([tmp_path]), tmp_path)
    assert got == ["real/a.jpg"]


def test_hardlinks_yield_once(tmp_path):
    a = touch(tmp_path / "a.jpg")
    os.link(a, tmp_path / "b.jpg")
    assert len(list(iter_images([tmp_path]))) == 1


def test_unicode_and_odd_names(tmp_path):
    for n in ["café ☕.jpg", "写真/東京.png", "ñandú  spaced .JPG", "emoji_🙂.webp"]:
        touch(tmp_path / n)
    assert len(list(iter_images([tmp_path]))) == 4


def test_missing_root_and_file_root_reported(tmp_path):
    f = touch(tmp_path / "file.jpg")
    errs = []
    assert list(iter_images([tmp_path / "nope", f], on_error=lambda p, m: errs.append((p.name, m)))) == []
    assert [e[0] for e in errs] == ["nope", "file.jpg"]


def test_permission_error_on_folder_is_reported_not_raised(tmp_path, monkeypatch):
    touch(tmp_path / "ok.jpg")
    touch(tmp_path / "locked" / "x.jpg")
    real_scandir = os.scandir

    def fake(path):
        if str(path).endswith("locked"):
            raise PermissionError(13, "denied")
        return real_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", fake)
    errs = []
    got = names(iter_images([tmp_path], on_error=lambda p, m: errs.append((p.name, m))), tmp_path)
    assert got == ["ok.jpg"] and errs == [("locked", "Permission denied")]


def test_cancel_stops_enumeration(tmp_path):
    for i in range(5):
        touch(tmp_path / f"d{i}" / "a.jpg")
    ev = threading.Event()
    ev.set()
    with pytest.raises(ScanCancelled):
        list(scanner.iter_entries([tmp_path], cancel=ev))
