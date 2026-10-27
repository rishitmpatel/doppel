from __future__ import annotations

import threading

import numpy as np
import pytest

from doppel.core import cluster, scanner
from doppel.core.models import ScanCancelled
from doppel.core.paths import user_cache_dir, user_data_dir


def test_find_pairs_matches_brute_force():
    rng = np.random.default_rng(3)
    base = rng.integers(0, 2**63, 40, dtype=np.uint64)
    ph = np.concatenate([base, base ^ np.uint64(0b1011), base ^ np.uint64(0xFFFFFFFF)])  # distances 3 and 32
    dh = ph.copy()
    i, j = cluster.find_pairs(list(map(int, ph)), list(map(int, dh)), 8)
    got = set(zip(i.tolist(), j.tolist()))
    want = {(a, b) for a in range(len(ph)) for b in range(a + 1, len(ph)) if (int(ph[a]) ^ int(ph[b])).bit_count() <= 8}
    assert got == want and len(got) == 40 + 0  # 40 near pairs (distance 3); far copies and mixed pairs are > 8


def test_dhash_confirmation_and_block_boundaries(monkeypatch):
    monkeypatch.setattr(cluster, "_TARGET_ELEMS", 50)  # force many tiny blocks
    ph = [0, 1, 3, (1 << 64) - 1]
    dh_close = [0, 1, 3, (1 << 64) - 1]
    dh_far = [0, (1 << 40) - 1, 3, (1 << 64) - 1]   # item 1's dHash is 40 bits away from item 0's
    i, j = cluster.find_pairs(ph, dh_close, 4)
    assert set(zip(i.tolist(), j.tolist())) == {(0, 1), (0, 2), (1, 2)}
    i, j = cluster.find_pairs(ph, dh_far, 4)
    assert set(zip(i.tolist(), j.tolist())) == {(0, 2)}


def test_empty_and_single_inputs():
    for ph in ([], [5]):
        i, j = cluster.find_pairs(ph, ph, 8)
        assert len(i) == len(j) == 0
    assert cluster.clusters(0, np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)) == []


def test_clusters_are_connected_components():
    pi, pj = np.array([0, 1, 5, 7]), np.array([1, 2, 6, 8])
    assert sorted(cluster.clusters(10, pi, pj)) == [[0, 1, 2], [5, 6], [7, 8]]


def test_find_pairs_cancel():
    ev = threading.Event()
    ev.set()
    with pytest.raises(ScanCancelled):
        cluster.find_pairs([1, 2, 3], [1, 2, 3], 8, cancel=ev)


def test_popcount_fallback_agrees(monkeypatch):
    x = np.random.default_rng(1).integers(0, 2**63, (4, 5), dtype=np.uint64)
    want = np.vectorize(lambda v: int(v).bit_count())(x)
    pop16 = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.uint8)
    got = pop16[np.ascontiguousarray(x).view(np.uint16).reshape(*x.shape, 4)].sum(axis=-1, dtype=np.uint8)
    assert (cluster.popcount(x) == want).all() and (got == want).all()


def test_windows_attribute_filters():
    f = scanner._win_skip
    assert f(0, False, True) is False and f(0, True, True) is False
    assert f(0x2, False, True) and not f(0x2, False, False)          # hidden
    assert f(0x400, True, True) and not f(0x400, False, True)         # junction / reparse point dir
    assert f(0x1000, False, True) and f(0x400000, False, False)       # cloud-only placeholders


def test_app_dirs_follow_env_and_platform(monkeypatch, tmp_path):
    monkeypatch.delenv("DOPPEL_CACHE_DIR")
    monkeypatch.delenv("DOPPEL_DATA_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xc"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xd"))
    monkeypatch.setattr("sys.platform", "linux")
    assert user_cache_dir() == tmp_path / "xc" / "doppel" and user_data_dir() == tmp_path / "xd" / "doppel"
    monkeypatch.setattr("sys.platform", "darwin")
    assert user_cache_dir().parts[-3:] == ("Library", "Caches", "Doppel")
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    assert user_cache_dir() == tmp_path / "lad" / "Doppel"
