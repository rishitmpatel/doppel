from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import pytest

from doppel.core import cache as cache_mod
from doppel.core.cache import HashCache, default_cache_dir
from doppel.core.models import PhotoInfo


def info(path="/p/a.jpg", size=100, mtime=1_700_000_000.5, **kw):
    base = dict(path=Path(path), size=size, mtime=mtime, width=40, height=30, format="JPEG",
                taken=datetime(2020, 5, 17, 12, 30, 1), camera="Canon EOS", sha=None,
                phash=(1 << 63) | 12345, dhash=(1 << 64) - 1, sharpness=12.5)
    base.update(kw)
    return PhotoInfo(**base)


NS = 1_700_000_000_500_000_000


@pytest.fixture
def db(tmp_path):
    c = HashCache(tmp_path / "sub" / "c.sqlite3")
    yield c
    c.close()


def test_roundtrip_with_full_range_64bit_hashes(db):
    i = info()
    db.put(i, NS)
    got = db.get(i.path, i.size, NS)
    assert got is not None
    assert (got.phash, got.dhash) == (i.phash, i.dhash)
    assert got.taken == i.taken and got.camera == i.camera and got.sharpness == i.sharpness
    assert (got.width, got.height, got.format) == (40, 30, "JPEG")
    assert got.mtime == pytest.approx(i.mtime)


def test_put_without_mtime_ns_derives_it(db):
    i = info()
    db.put(i)
    assert db.get(i.path, i.size, round(i.mtime * 1e9)) is not None


def test_miss_when_size_or_mtime_changed_or_unknown(db):
    i = info()
    db.put(i, NS)
    assert db.get(i.path, i.size + 1, NS) is None
    assert db.get(i.path, i.size, NS + 1) is None
    assert db.get("/other.jpg", i.size, NS) is None


def test_changed_file_replaces_row_but_same_version_merges(db):
    db.put(info(), NS)
    db.put(info(width=0, height=0, format="", taken=None, camera=None, phash=None, dhash=None,
                sharpness=None, sha="abc"), NS)  # sha-only update keeps analysis
    got = db.get(Path("/p/a.jpg"), 100, NS)
    assert got.sha == "abc" and got.width == 40 and got.phash == (1 << 63) | 12345
    db.put(info(size=200, width=0, height=0, format="", phash=None, dhash=None, sharpness=None,
                taken=None, camera=None, sha="new"), NS + 5)  # file changed: old data dropped
    got = db.get(Path("/p/a.jpg"), 200, NS + 5)
    assert got.sha == "new" and got.width == 0 and got.phash is None
    assert db.count() == 1


def test_put_many_and_prune(db, tmp_path):
    rows = [(info(f"/r/a/{i}.jpg"), NS) for i in range(5)] + [(info(f"/r/b/{i}.jpg"), NS) for i in range(3)]
    db.put_many(rows)
    db.put_partials([("/r/a/0.jpg", 100, NS, "pp")])
    db.put_errors([("/r/a/1.jpg", 100, NS, "bad")])
    assert db.get_partial("/r/a/0.jpg", 100, NS) == "pp" and db.get_partial("/r/a/0.jpg", 101, NS) is None
    assert db.get_error("/r/a/1.jpg", 100, NS) == "bad"
    removed = db.prune([f"/r/a/{i}.jpg" for i in range(3)], under=["/r/a"])
    assert removed == 2 and db.count() == 6  # /r/b untouched
    assert db.get_error("/r/a/1.jpg", 100, NS) == "bad"
    assert db.prune([]) == 6 and db.count() == 0


def test_schema_version_mismatch_resets(tmp_path):
    p = tmp_path / "c.sqlite3"
    c = HashCache(p)
    c.put(info(), NS)
    c.close()
    raw = sqlite3.connect(p)
    assert raw.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(cache_mod.SCHEMA_VERSION)
    raw.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
    raw.commit()
    raw.close()
    c = HashCache(p)
    assert c.count() == 0
    c.put(info(), NS)
    c.close()
    with HashCache(p) as again:
        assert again.count() == 1  # same version: preserved


def test_wal_mode_and_corrupt_file_recovery(tmp_path):
    p = tmp_path / "c.sqlite3"
    c = HashCache(p)
    assert c._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    c.close()
    p.write_bytes(b"this is definitely not a sqlite database" * 50)
    c = HashCache(p)  # recovers by starting over
    c.put(info(), NS)
    assert c.count() == 1
    c.close()


def test_memory_cache_and_default_location(tmp_path, monkeypatch):
    m = HashCache(":memory:")
    m.put(info(), NS)
    assert m.count() == 1
    m.close()
    monkeypatch.setenv("DOPPEL_CACHE_DIR", str(tmp_path / "dflt"))
    assert default_cache_dir() == tmp_path / "dflt"
    d = HashCache()
    d.put(info(), NS)
    d.close()
    assert (tmp_path / "dflt" / "hashes.sqlite3").exists()


def test_thread_safe_shared_instance(db):
    errors = []

    def work(t):
        try:
            for i in range(150):
                p = f"/t{t}/{i}.jpg"
                db.put(info(p), NS)
                assert db.get(Path(p), 100, NS) is not None
                db.put_partials([(p, 100, NS, "x")])
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    ts = [threading.Thread(target=work, args=(t,)) for t in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == [] and db.count() == 8 * 150


def test_two_instances_same_file_concurrently(tmp_path):
    p = tmp_path / "shared.sqlite3"
    caches = [HashCache(p) for _ in range(4)]
    errors = []

    def work(idx):
        try:
            for i in range(100):
                caches[idx].put_many([(info(f"/c{idx}/{i}.jpg"), NS), (info(f"/shared/{i}.jpg", sha=str(idx)), NS)])
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []
    assert caches[0].count() == 4 * 100 + 100
    for c in caches:
        c.close()
