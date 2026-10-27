from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

import imgfactory as F
from doppel.core import finder, hashing
from doppel.core.cache import HashCache
from doppel.core.finder import Progress, ScanOptions, scan
from doppel.core.models import MatchKind, ScanCancelled, ScanResult
from doppel.core.selector import recommend

SIZE = (480, 360)


def opts(root, **kw):
    kw.setdefault("min_size_bytes", 0)
    kw.setdefault("workers", 2)
    roots = root if isinstance(root, list) else [root]
    return ScanOptions(roots=roots, **kw)


def jpg(img, path, q=92):
    path.parent.mkdir(parents=True, exist_ok=True)
    return F.save_jpeg(img, path, q)


def copy_to(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
    return dst


def names(group):
    return sorted(p.path.name for p in group.photos)


@pytest.fixture
def lib(tmp_path):
    """A small library: one photo with an exact copy, its look-alike variants, and unrelated pictures."""
    root = tmp_path / "lib"
    base = F.photo(100, SIZE)
    jpg(base, root / "IMG_0001.jpg")
    copy_to(root / "IMG_0001.jpg", root / "IMG_0001 (1).jpg")
    copy_to(root / "IMG_0001.jpg", root / "backup" / "Copy of IMG_0001.jpg")
    jpg(F.resized(base), root / "variants" / "small.jpg")
    jpg(base, root / "variants" / "q70.jpg", 70)
    F.save_exif_rotated(base, root / "variants" / "rot.jpg")
    jpg(F.cropped(base), root / "variants" / "crop.jpg")
    for i, im in enumerate(F.distinct_images(6, SIZE)[3:], start=10):
        jpg(im, root / "others" / f"other{i}.jpg")
    return root


def test_exact_and_similar_groups_do_not_repeat_exact_copies(lib):
    res = scan(opts(lib))
    assert isinstance(res, ScanResult)
    exact = [g for g in res.groups if g.kind is MatchKind.EXACT]
    similar = [g for g in res.groups if g.kind is MatchKind.SIMILAR]
    assert len(exact) == 1 and len(similar) == 1
    assert names(exact[0]) == ["Copy of IMG_0001.jpg", "IMG_0001 (1).jpg", "IMG_0001.jpg"]
    assert exact[0].keep == {lib / "IMG_0001.jpg"} and exact[0].similarity == 1.0
    assert exact[0].reclaimable_bytes == 2 * (lib / "IMG_0001.jpg").stat().st_size
    sim_names = names(similar[0])
    assert sorted(sim_names) == sorted(["small.jpg", "q70.jpg", "rot.jpg", "crop.jpg", "IMG_0001.jpg"])
    assert sum(n.startswith("IMG_0001") or n.startswith("Copy") for n in sim_names) == 1  # one representative only
    assert 0.8 < similar[0].similarity < 1.0
    assert len(similar[0].keep) == 1 and next(iter(similar[0].keep)) in {p.path for p in similar[0].photos}
    assert res.scanned == 3 + 4 + 3 and res.errors == [] and res.elapsed > 0
    assert [g.id for g in res.groups] == list(range(1, len(res.groups) + 1))
    assert [g.reclaimable_bytes for g in res.groups] == sorted((g.reclaimable_bytes for g in res.groups), reverse=True)


def test_representative_is_the_exact_groups_recommended_copy(lib):
    res = scan(opts(lib))
    exact = next(g for g in res.groups if g.kind is MatchKind.EXACT)
    similar = next(g for g in res.groups if g.kind is MatchKind.SIMILAR)
    rep = {p.path for p in similar.photos} & {p.path for p in exact.photos}
    assert rep == exact.keep == recommend(exact)


def test_group_photos_have_complete_metadata(lib):
    res = scan(opts(lib))
    g = next(g for g in res.groups if g.kind is MatchKind.EXACT)
    for p in g.photos:
        assert (p.width, p.height, p.format) == (480, 360, "JPEG")
        assert p.sha and p.phash is not None and p.dhash is not None and p.sharpness > 0
        assert p.size == p.path.stat().st_size and p.megapixels == pytest.approx(0.1728)
    assert len({p.sha for p in g.photos}) == 1
    sim = next(g for g in res.groups if g.kind is MatchKind.SIMILAR)
    rot = next(p for p in sim.photos if p.path.name == "rot.jpg")
    assert (rot.width, rot.height) == (480, 360)  # displayed size, not stored size
    # keep set first in photos
    assert sim.photos[0].path in sim.keep and g.photos[0].path in g.keep


def test_no_false_matches_among_24_distinct_images(tmp_path):
    for i, im in enumerate(F.distinct_images(24, SIZE)):
        jpg(im, tmp_path / f"d{i}.jpg")
    res = scan(opts(tmp_path))
    assert res.groups == [] and res.scanned == 24 and res.errors == []


def test_similarity_slider_strict_vs_loose(tmp_path):
    base = F.photo(2, SIZE)
    jpg(base, tmp_path / "a.jpg")
    jpg(F.cropped(base, 0.05), tmp_path / "b.jpg")
    jpg(F.photo(9, SIZE), tmp_path / "c.jpg")
    assert len(scan(opts(tmp_path, similarity=0)).groups) == 0
    assert len(scan(opts(tmp_path, similarity=20)).groups) == 1
    assert ScanOptions(roots=[]).similarity == 8


def _padded(jpeg_bytes: bytes, total: int, flip_at: int | None = None) -> bytes:
    """JPEG followed by zero padding (decoders ignore trailing bytes) to exactly ``total`` bytes."""
    pad = bytearray(total - len(jpeg_bytes))
    if flip_at is not None:
        pad[flip_at] = 7
    return jpeg_bytes + bytes(pad)


def test_only_files_sharing_size_and_partial_hash_are_fully_hashed(tmp_path, monkeypatch):
    j1, j2 = F.photo(1, SIZE), F.photo(2, SIZE)
    b1, b2 = (jpg(j1, tmp_path / "t1.jpg").read_bytes(), jpg(j2, tmp_path / "t2.jpg").read_bytes())
    for p in ("t1.jpg", "t2.jpg"):
        (tmp_path / p).unlink()
    total = 300_000
    big = {
        "A1.jpg": _padded(b1, total), "A2.jpg": _padded(b1, total),                           # identical
        "B1.jpg": _padded(b1, total, flip_at=150_000), "B2.jpg": _padded(b1, total, 150_001),  # same head+tail, differ in the middle
        "C1.jpg": _padded(b1, total + 1), "C2.jpg": _padded(b2, total + 1),                    # same size, different head
        "D.jpg": _padded(b2, total + 5),                                                       # unique size
    }
    for n, data in big.items():
        (tmp_path / n).write_bytes(data)
    (tmp_path / "S1.jpg").write_bytes(b1)   # small identical pair: partial hash == full hash
    (tmp_path / "S2.jpg").write_bytes(b1)
    partial_calls, full_calls = [], []
    orig_p, orig_f = hashing.partial_sha, hashing.file_sha
    monkeypatch.setattr(hashing, "partial_sha", lambda p, *a, **k: (partial_calls.append(Path(p).name), orig_p(p, *a, **k))[1])
    monkeypatch.setattr(hashing, "file_sha", lambda p, *a, **k: (full_calls.append(Path(p).name), orig_f(p, *a, **k))[1])
    res = scan(opts(tmp_path, find_similar=False))
    assert sorted(partial_calls) == ["A1.jpg", "A2.jpg", "B1.jpg", "B2.jpg", "C1.jpg", "C2.jpg", "S1.jpg", "S2.jpg"]
    assert sorted(full_calls) == ["A1.jpg", "A2.jpg", "B1.jpg", "B2.jpg"]   # not C*, D, S*
    found = sorted(names(g) for g in res.groups)
    assert found == [["A1.jpg", "A2.jpg"], ["S1.jpg", "S2.jpg"]]            # B differs in the middle
    assert all(g.kind is MatchKind.EXACT for g in res.groups)


def test_find_flags(lib):
    only_exact = scan(opts(lib, find_similar=False))
    assert [g.kind for g in only_exact.groups] == [MatchKind.EXACT]
    only_similar = scan(opts(lib, find_exact=False))
    assert [g.kind for g in only_similar.groups] == [MatchKind.SIMILAR]
    # exact copies still collapsed to a single representative
    assert sum(n.startswith(("IMG_0001", "Copy")) for n in names(only_similar.groups[0])) == 1
    assert scan(opts(lib, find_exact=False, find_similar=False)).groups == []


def test_min_size_and_subfolder_options(lib):
    sizes = sorted(p.stat().st_size for p in lib.rglob("*.jpg"))
    big_only = scan(opts(lib, min_size_bytes=sizes[-1] // 2))
    assert big_only.scanned < len(sizes)
    top = scan(opts(lib, include_subfolders=False))
    assert top.scanned == 2 and [g.kind for g in top.groups] == [MatchKind.EXACT]
    assert names(top.groups[0]) == ["IMG_0001 (1).jpg", "IMG_0001.jpg"]


def test_multiple_roots(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    img = F.photo(3, SIZE)
    jpg(img, a / "x.jpg")
    copy_to(a / "x.jpg", b / "x.jpg")
    res = scan(opts([a, b]))
    assert len(res.groups) == 1 and res.groups[0].kind is MatchKind.EXACT


# ----------------------------------------------------------------------- robustness
def test_unreadable_files_are_reported_and_do_not_stop_the_scan(tmp_path, monkeypatch):
    good = jpg(F.photo(1, SIZE), tmp_path / "good.jpg")
    shutil.copy(good, tmp_path / "good2.jpg")
    data = good.read_bytes()
    (tmp_path / "truncated.jpg").write_bytes(data[: len(data) // 2])
    (tmp_path / "zero.jpg").write_bytes(b"")
    (tmp_path / "text.png").write_text("I am a text file wearing a .png hat" * 50)
    (tmp_path / "locked.jpg").write_bytes(data[:-3] + b"xyz")
    real_open = Image.open

    def fake_open(fp, *a, **k):
        if "locked" in str(fp):
            raise PermissionError(13, "Permission denied")
        return real_open(fp, *a, **k)

    monkeypatch.setattr(hashing.Image, "open", fake_open)
    res = scan(opts(tmp_path))
    msgs = {p.name: m for p, m in res.errors}
    assert set(msgs) == {"truncated.jpg", "zero.jpg", "text.png", "locked.jpg"}
    assert "damaged" in msgs["truncated.jpg"] and "Empty" in msgs["zero.jpg"]
    assert "Not a valid image" in msgs["text.png"] and msgs["locked.jpg"] == "Permission denied"
    assert len(res.groups) == 1 and names(res.groups[0]) == ["good.jpg", "good2.jpg"]
    assert res.scanned == 5  # the empty file is reported but not counted as scanned


def test_zero_byte_files_are_ignored_with_default_min_size(tmp_path):
    (tmp_path / "zero.jpg").write_bytes(b"")
    (tmp_path / "zero2.jpg").write_bytes(b"")
    res = scan(opts(tmp_path, min_size_bytes=10_240))
    assert res.groups == [] and res.errors == [] and res.scanned == 0


def test_decompression_bomb_is_reported_not_fatal(tmp_path, monkeypatch):
    jpg(F.photo(1, (120, 100)), tmp_path / "ok.jpg")
    Image.new("L", (400, 300)).save(tmp_path / "huge.png")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100_000)  # 400*300 = 120k: above limit, below 2x (warning)
    res = scan(opts(tmp_path))
    assert [(p.name, "too large" in m) for p, m in res.errors] == [("huge.png", True)]
    assert res.scanned == 2


def test_exact_copies_of_unreadable_files_are_errors_not_groups(tmp_path):
    (tmp_path / "bad1.jpg").write_bytes(b"not an image" * 100)
    (tmp_path / "bad2.jpg").write_bytes(b"not an image" * 100)
    res = scan(opts(tmp_path))
    assert res.groups == [] and sorted(p.name for p, _ in res.errors) == ["bad1.jpg", "bad2.jpg"]


def test_symlinks_and_unicode_paths(tmp_path):
    root = tmp_path / "Fotos ☀ 写真"
    img = F.photo(5, SIZE)
    a = jpg(img, root / "été" / "café ☕.jpg")
    copy_to(a, root / "日本語 フォルダ" / "コピー.jpg")
    os.symlink(a, root / "link.jpg")
    os.symlink(root, root / "loop")
    res = scan(opts(root))
    assert len(res.groups) == 1 and res.scanned == 2   # symlink neither followed nor counted
    assert {p.path.name for p in res.groups[0].photos} == {"café ☕.jpg", "コピー.jpg"}


def test_heic_without_pillow_heif_is_skipped_gracefully(tmp_path, monkeypatch):
    jpg(F.photo(1, SIZE), tmp_path / "ok.jpg")
    (tmp_path / "phone.heic").write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 500)
    monkeypatch.setattr(hashing, "HEIF_AVAILABLE", False)
    res = scan(opts(tmp_path))
    msgs = {p.name: m for p, m in res.errors}
    assert list(msgs) == ["phone.heic"] and "pillow-heif" in msgs["phone.heic"]


def test_missing_root_is_an_error_entry(tmp_path):
    res = scan(opts([tmp_path / "does-not-exist"]))
    assert res.groups == [] and res.errors[0][1] == "Folder not found"


# ----------------------------------------------------------------------- cache
def test_warm_scan_uses_cache_and_detects_changes(lib, tmp_path, monkeypatch):
    calls = {"analyze": 0, "file": 0, "partial": 0}
    for name, attr in (("analyze", "analyze_image"), ("file", "file_sha"), ("partial", "partial_sha")):
        orig = getattr(hashing, attr)
        monkeypatch.setattr(hashing, attr, (lambda o, n: lambda *a, **k: (calls.__setitem__(n, calls[n] + 1), o(*a, **k))[1])(orig, name))
    with HashCache(tmp_path / "c.sqlite3") as cache:
        cold = scan(opts(lib), cache=cache)
        assert calls["analyze"] > 0
        cold_calls = dict(calls)
        warm = scan(opts(lib), cache=cache)
        assert calls == cold_calls                      # nothing recomputed
        sig = lambda r: [(g.kind, g.id, [str(p.path) for p in g.photos], sorted(map(str, g.keep))) for g in r.groups]
        assert sig(cold) == sig(warm) and warm.scanned == cold.scanned
        # touch one file -> only that one is decoded again
        victim = lib / "others" / "other10.jpg"
        jpg(F.photo(77, SIZE), victim)
        os.utime(victim, (time.time() + 5, time.time() + 5))
        scan(opts(lib), cache=cache)
        assert calls["analyze"] == cold_calls["analyze"] + 1


def test_cached_errors_are_not_retried_but_permission_errors_are(tmp_path, monkeypatch):
    jpg(F.photo(1, SIZE), tmp_path / "ok.jpg")
    (tmp_path / "bad.jpg").write_bytes(b"garbage" * 100)
    n = {"c": 0}
    orig = hashing.analyze_image
    monkeypatch.setattr(hashing, "analyze_image", lambda p: (n.__setitem__("c", n["c"] + 1), orig(p))[1])
    with HashCache(tmp_path / "c.sqlite3") as cache:
        r1 = scan(opts(tmp_path), cache=cache)
        r2 = scan(opts(tmp_path), cache=cache)
    assert n["c"] == 2 and r1.errors == r2.errors and len(r2.errors) == 1


def test_cache_prunes_deleted_files_under_scanned_roots(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    jpg(F.photo(1, SIZE), a / "1.jpg")
    jpg(F.photo(2, SIZE), a / "2.jpg")
    jpg(F.photo(3, SIZE), b / "3.jpg")
    with HashCache(tmp_path / "c.sqlite3") as cache:
        scan(opts(a), cache=cache)
        scan(opts(b), cache=cache)
        assert cache.count() == 3                       # scanning b did not forget a
        (a / "2.jpg").unlink()
        scan(opts(a), cache=cache)
        assert cache.count() == 2


# ----------------------------------------------------------------------- cancel & progress
def _many(tmp_path, n=40):
    for i in range(n):
        jpg(F.photo(i, (160, 120)), tmp_path / f"p{i}.jpg")


def test_precancelled_scan_raises_immediately(tmp_path):
    _many(tmp_path, 3)
    ev = threading.Event()
    ev.set()
    with pytest.raises(ScanCancelled):
        scan(opts(tmp_path), cancel=ev)


def test_cancel_during_slow_decoding_returns_within_a_second(tmp_path, monkeypatch):
    _many(tmp_path, 40)
    orig = hashing.analyze_image

    def slow(p):
        time.sleep(0.3)
        return orig(p)

    monkeypatch.setattr(hashing, "analyze_image", slow)
    ev = threading.Event()
    stamp = {}

    def trigger():
        time.sleep(0.4)
        stamp["set"] = time.monotonic()
        ev.set()

    threading.Thread(target=trigger, daemon=True).start()
    t0 = time.monotonic()
    with pytest.raises(ScanCancelled):
        scan(opts(tmp_path, workers=2), cancel=ev)
    assert time.monotonic() - stamp["set"] < 1.0
    assert time.monotonic() - t0 < 1.5


def test_cancel_from_progress_callback_in_each_stage(lib):
    for stage in ("Finding photos", "Checking files", "Comparing photos", "Grouping"):
        ev = threading.Event()

        def cb(p: Progress, stage=stage, ev=ev):
            if p.stage == stage:
                ev.set()

        with pytest.raises(ScanCancelled):
            scan(opts(lib), progress=cb, cancel=ev)


def test_cancel_keeps_partial_work_in_cache(tmp_path, monkeypatch):
    _many(tmp_path, 30)
    ev = threading.Event()

    def cb(p):
        if p.stage == "Comparing photos" and p.done >= 10:
            ev.set()

    with HashCache(tmp_path / "c.sqlite3") as cache:
        with pytest.raises(ScanCancelled):
            scan(opts(tmp_path), progress=cb, cancel=ev, cache=cache)
        assert 0 < cache.count() < 30


def test_cancelled_scan_inside_checking_files_stops_hashing_large_files(tmp_path):
    jpg_bytes = jpg(F.photo(1, SIZE), tmp_path / "t.jpg").read_bytes()
    (tmp_path / "t.jpg").unlink()
    for n in ("a", "b"):
        (tmp_path / f"{n}.jpg").write_bytes(jpg_bytes + bytes(40_000_000))   # 40 MB each, same size
    ev = threading.Event()
    threading.Timer(0.02, ev.set).start()
    t0 = time.monotonic()
    try:
        scan(opts(tmp_path, find_similar=False), cancel=ev)
    except ScanCancelled:
        pass
    assert time.monotonic() - t0 < 1.0


def test_progress_is_monotonic_per_stage_throttled_and_ends_done(tmp_path):
    for i in range(60):
        jpg(F.photo(i % 20, (96, 72)), tmp_path / f"p{i}.jpg")   # lots of exact copies too
    events: list[tuple[float, Progress]] = []
    res = scan(opts(tmp_path, workers=4), progress=lambda p: events.append((time.monotonic(), p)))
    prog = [p for _, p in events]
    stages = []
    for p in prog:
        if not stages or stages[-1] != p.stage:
            stages.append(p.stage)
    assert stages == ["Finding photos", "Checking files", "Comparing photos", "Grouping", "Done"]
    for stage in stages:
        ds = [p.done for p in prog if p.stage == stage]
        assert ds == sorted(ds), stage
        ts = {p.total for p in prog if p.stage == stage and p.total}
        assert all(p.done <= p.total for p in prog if p.stage == stage and p.total)
        assert len(ts) <= 1 or stage == "Finding photos"
    last = prog[-1]
    assert last.stage == "Done" and last.done == last.total == len(res.groups)
    for stage in ("Checking files", "Comparing photos"):
        final = [p for p in prog if p.stage == stage][-1]
        assert final.done == final.total
    # never more than ~50 calls/second
    times = [t for t, _ in events]
    for i, t in enumerate(times):
        assert sum(1 for u in times[i:] if u - t < 1.0) <= 60


def test_progress_flood_is_throttled(tmp_path):
    for i in range(300):
        (tmp_path / f"f{i}.jpg").write_bytes(bytes([i % 256]) * (50 + i))   # junk files: finish instantly
    calls = []
    t0 = time.monotonic()
    scan(opts(tmp_path), progress=calls.append)
    elapsed = time.monotonic() - t0
    assert len(calls) <= elapsed / finder._MIN_PROGRESS_INTERVAL + 12


def test_scan_without_callbacks_or_cache(lib):
    assert scan(opts(lib), None, None, None).groups


def test_result_is_stable_across_worker_counts(lib):
    sig = lambda r: [(g.kind, [str(p.path) for p in g.photos]) for g in r.groups]
    assert sig(scan(opts(lib, workers=1))) == sig(scan(opts(lib, workers=6)))


def test_flat_images_are_not_matched_by_look(tmp_path):
    for i, color in enumerate([(255, 255, 255), (0, 0, 0), (250, 250, 250)]):
        Image.new("RGB", (300, 300), color).save(tmp_path / f"flat{i}.png")
    assert scan(opts(tmp_path)).groups == []
    shutil.copy(tmp_path / "flat0.png", tmp_path / "flat0_copy.png")
    res = scan(opts(tmp_path))
    assert [g.kind for g in res.groups] == [MatchKind.EXACT]
