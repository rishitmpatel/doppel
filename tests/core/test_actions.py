from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from doppel.core import actions
from doppel.core.actions import ActionRecord, RemoveMode, UnsafeRemovalError, plan_removal, read_log, remove, undo
from doppel.core.models import DuplicateGroup, MatchKind, PhotoInfo
from doppel.core.scanner import REVIEW_MARKER, iter_images


def mk(tmp_path, name, data=b"data"):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def photo(path, size=10):
    return PhotoInfo(Path(path), size, 1.7e9, 10, 10, "JPEG")


def group(gid, paths, keep, kind=MatchKind.EXACT):
    return DuplicateGroup(gid, kind, [photo(p) for p in paths], {Path(k) for k in keep}, 1.0)


# ----------------------------------------------------------------------- TRASH
def test_trash_uses_send2trash_and_logs(tmp_path, trash):
    a, b = mk(tmp_path, "a.jpg"), mk(tmp_path, "b.jpg")
    log = tmp_path / "log.jsonl"
    recs = remove([a, b], RemoveMode.TRASH, log_path=log)
    assert [r.ok for r in recs] == [True, True]
    assert all(r.destination is None and r.mode is RemoveMode.TRASH and r.error is None for r in recs)
    assert trash == [str(a), str(b)]
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert [e["original"] for e in lines] == [str(a), str(b)] and lines[0]["mode"] == "trash"


def test_trash_failure_is_reported_per_file(tmp_path, monkeypatch):
    import send2trash

    def boom(path):
        raise PermissionError(13, "nope")

    monkeypatch.setattr(send2trash, "send2trash", boom)
    a = mk(tmp_path, "a.jpg")
    (rec,) = remove([a], RemoveMode.TRASH, log_path=tmp_path / "l")
    assert not rec.ok and rec.error == "Permission denied" and a.exists()


def test_patching_module_level_name_also_works(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(actions, "send2trash", lambda p: called.append(p))
    a = mk(tmp_path, "a.jpg")
    remove([a], RemoveMode.TRASH, log_path=tmp_path / "l")
    assert called == [str(a)]


def test_missing_files_and_folders_are_refused_not_raised(tmp_path, trash):
    d = tmp_path / "folder"
    d.mkdir()
    recs = remove([tmp_path / "ghost.jpg", d], RemoveMode.TRASH, log_path=tmp_path / "l")
    assert [r.ok for r in recs] == [False, False]
    assert "not found" in recs[0].error.lower() and "folder" in recs[1].error.lower()
    assert trash == [] and d.exists()


def test_default_log_goes_to_data_dir(tmp_path, trash):
    a = mk(tmp_path, "a.jpg")
    remove([a], RemoveMode.TRASH)
    assert (Path(os.environ["DOPPEL_DATA_DIR"]) / "actions.jsonl").exists()
    assert [e["original"] for e in read_log()] == [str(a)]


def test_unwritable_log_never_breaks_removal(tmp_path, trash):
    a = mk(tmp_path, "a.jpg")
    blocker = mk(tmp_path, "blocker")
    (rec,) = remove([a], RemoveMode.TRASH, log_path=blocker / "sub" / "log.jsonl")
    assert rec.ok


# ----------------------------------------------------------------------- MOVE
def test_move_preserves_structure_and_marks_review_folder(tmp_path):
    a = mk(tmp_path / "lib", "2020/trip/a.jpg", b"AAA")
    review = tmp_path / "Doppel Review"
    (rec,) = remove([a], RemoveMode.MOVE, review, log_path=tmp_path / "l")
    assert rec.ok and not a.exists() and rec.destination.read_bytes() == b"AAA"
    rel = rec.destination.relative_to(review)
    assert len(rel.parts[0]) == len("2026-01-01_1200") and rel.parts[0][4] == "-" and rel.parts[0][10] == "_"
    assert rel.parts[1] == "root"
    assert rel.parts[2:] == Path(os.path.abspath(a)).relative_to("/").parts
    assert (review / REVIEW_MARKER).exists()
    assert list(iter_images([tmp_path])) == []  # review folder is not scanned again


def test_move_never_overwrites(tmp_path):
    review = tmp_path / "rev"
    a = mk(tmp_path / "lib", "a.jpg", b"1")
    (r1,) = remove([a], RemoveMode.MOVE, review, log_path=tmp_path / "l")
    a = mk(tmp_path / "lib", "a.jpg", b"2")  # same path again, same minute
    (r2,) = remove([a], RemoveMode.MOVE, review, log_path=tmp_path / "l")
    a = mk(tmp_path / "lib", "a.jpg", b"3")
    (r3,) = remove([a], RemoveMode.MOVE, review, log_path=tmp_path / "l")
    dests = {r1.destination, r2.destination, r3.destination}
    assert len(dests) == 3
    assert {r.destination.read_bytes() for r in (r1, r2, r3)} == {b"1", b"2", b"3"}


def test_move_requires_review_dir(tmp_path):
    with pytest.raises(ValueError):
        remove([mk(tmp_path, "a.jpg")], RemoveMode.MOVE)


def test_move_failure_and_unusable_review_dir(tmp_path):
    a = mk(tmp_path, "a.jpg")
    blocker = mk(tmp_path, "file_not_dir")
    recs = remove([a], RemoveMode.MOVE, blocker / "rev", log_path=tmp_path / "l")
    assert not recs[0].ok and "review folder" in recs[0].error and a.exists()


def test_undo_restores_and_cleans_empty_folders(tmp_path):
    review = tmp_path / "rev"
    a = mk(tmp_path / "lib", "x/y/a.jpg", b"A")
    b = mk(tmp_path / "lib", "x/b.jpg", b"B")
    recs = remove([a, b], RemoveMode.MOVE, review, log_path=tmp_path / "l")
    assert not a.exists() and not b.exists()
    out = undo(recs, log_path=tmp_path / "l")
    assert [r.ok for r in out] == [True, True]
    assert a.read_bytes() == b"A" and b.read_bytes() == b"B"
    assert not any(p for p in review.rglob("*") if p.is_file() and p.name != REVIEW_MARKER)
    assert [d for d in review.iterdir() if d.is_dir()] == []  # session folder pruned
    actions_logged = [e["action"] for e in read_log(tmp_path / "l")]
    assert actions_logged == ["remove", "remove", "undo", "undo"]


def test_undo_does_not_overwrite_new_file_at_original_path(tmp_path):
    review = tmp_path / "rev"
    a = mk(tmp_path / "lib", "a.jpg", b"old")
    (rec,) = remove([a], RemoveMode.MOVE, review, log_path=tmp_path / "l")
    mk(tmp_path / "lib", "a.jpg", b"new")
    (res,) = undo([rec], log_path=tmp_path / "l")
    assert res.ok and res.destination != a and res.destination.read_bytes() == b"old"
    assert a.read_bytes() == b"new"


def test_undo_edge_cases(tmp_path, trash):
    a = mk(tmp_path, "a.jpg")
    (t,) = remove([a], RemoveMode.TRASH, log_path=tmp_path / "l")
    (u,) = undo([t], log_path=tmp_path / "l")
    assert not u.ok and "Recycle Bin" in u.error
    failed = ActionRecord(tmp_path / "z.jpg", None, RemoveMode.MOVE, False, "x")
    gone = ActionRecord(tmp_path / "g.jpg", tmp_path / "nowhere" / "g.jpg", RemoveMode.MOVE, True)
    r1, r2 = undo([failed, gone], log_path=tmp_path / "l")
    assert not r1.ok and not r2.ok and "no longer" in r2.error


def test_progress_callback_signatures(tmp_path, trash):
    files = [mk(tmp_path, f"{i}.jpg") for i in range(3)]
    seen2, seen3, seen1 = [], [], []
    remove(files[:1], RemoveMode.TRASH, progress=lambda d, t: seen2.append((d, t)), log_path=tmp_path / "l")
    remove([mk(tmp_path, "n.jpg")], RemoveMode.TRASH, progress=lambda d, t, c: seen3.append((d, t, c)), log_path=tmp_path / "l")
    remove([mk(tmp_path, "m.jpg"), mk(tmp_path, "o.jpg")], RemoveMode.TRASH, progress=lambda p: seen1.append(p), log_path=tmp_path / "l")
    assert seen2 == [(1, 1)] and seen3[0][:2] == (1, 1)
    assert [(p.done, p.total) for p in seen1] == [(1, 2), (2, 2)]


# ----------------------------------------------------------------------- plan_removal
def test_plan_removal_returns_everything_not_kept():
    g1 = group(1, ["/a/1.jpg", "/a/2.jpg", "/a/3.jpg"], ["/a/1.jpg"])
    g2 = group(2, ["/b/1.jpg", "/b/2.jpg"], ["/b/2.jpg"], MatchKind.SIMILAR)
    assert plan_removal([g1, g2]) == [Path("/a/2.jpg"), Path("/a/3.jpg"), Path("/b/1.jpg")]


def test_plan_removal_refuses_groups_without_a_keeper():
    with pytest.raises(UnsafeRemovalError):
        plan_removal([group(1, ["/a/1.jpg", "/a/2.jpg"], [])])
    with pytest.raises(UnsafeRemovalError):  # keep points at a path that is not in the group
        plan_removal([group(1, ["/a/1.jpg", "/a/2.jpg"], ["/zzz.jpg"])])
    assert issubclass(UnsafeRemovalError, ValueError)


def test_plan_removal_explicit_selection_must_leave_one():
    g = group(1, ["/a/1.jpg", "/a/2.jpg", "/a/3.jpg"], ["/a/1.jpg"])
    assert plan_removal([g], remove=[Path("/a/2.jpg")]) == [Path("/a/2.jpg")]
    with pytest.raises(UnsafeRemovalError):
        plan_removal([g], remove=[Path("/a/1.jpg"), Path("/a/2.jpg"), Path("/a/3.jpg")])


def test_plan_removal_group_overlap_checked_as_a_cluster():
    exact = group(1, ["/e/a.jpg", "/e/a copy.jpg"], ["/e/a.jpg"])
    # look-alike group whose representative of the exact set is /e/a.jpg; user keeps the other photo
    similar = group(2, ["/e/a.jpg", "/s/b.jpg"], ["/s/b.jpg"], MatchKind.SIMILAR)
    assert set(plan_removal([exact, similar])) == {Path("/e/a.jpg"), Path("/e/a copy.jpg")}
    # but never everything
    with pytest.raises(UnsafeRemovalError):
        plan_removal([exact, similar], remove=[Path("/e/a.jpg"), Path("/e/a copy.jpg"), Path("/s/b.jpg")])


def test_plan_removal_deduplicates():
    g1 = group(1, ["/a/1.jpg", "/a/2.jpg"], ["/a/1.jpg"])
    g2 = group(2, ["/a/1.jpg", "/a/2.jpg"], ["/a/1.jpg"], MatchKind.SIMILAR)
    assert plan_removal([g1, g2]) == [Path("/a/2.jpg")]
