from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from doppel.core.models import DuplicateGroup, MatchKind, PhotoInfo
from doppel.core.selector import KeepRule, best_photo, name_penalty, recommend


def P(path, size=1000, mtime=1.7e9, w=100, h=100, taken=None, camera=None, sharp=10.0):
    return PhotoInfo(Path(path), size, mtime, w, h, "JPEG", taken, camera, None, 1, 1, sharp)


def G(kind, *photos):
    return DuplicateGroup(1, kind, list(photos), set(), 0.9)


@pytest.mark.parametrize("name", ["IMG_0001.jpg", "DSC00012.JPG", "2023-05-12.jpg", "2023_05_12.jpg", "P1000123.jpg", "holiday.jpg",
                                  "photocopy.jpg", "IMG_20230512_101010.jpg", "Scan 2019.png", "a.b.jpg"])
def test_original_looking_names_have_no_penalty(name):
    assert name_penalty(name) == 0


@pytest.mark.parametrize("name", ["IMG_0001 (1).jpg", "IMG_0001 (2).jpg", "Copy of IMG_0001.jpg",
                                  "IMG_0001 - Copy.jpg", "IMG_0001 - Copy (2).jpg", "IMG_0001_copy.jpg",
                                  "IMG_0001-copy.jpg", "photo-1.jpg", "photo_2.jpg", "IMG_0001-1.jpg", "holiday copy.jpg",
                                  "COPY OF holiday.JPG", "holiday (1)(1).jpg"])
def test_copy_like_names_are_penalised(name):
    assert name_penalty(name) >= 1


def test_exact_group_prefers_original_name_even_if_newer():
    a = P("/p/IMG_001.jpg", mtime=1.7e9 + 500)
    b = P("/p/IMG_001 (1).jpg", mtime=1.7e9 + 100)
    c = P("/p/Copy of IMG_001.jpg", mtime=1.7e9 + 50)
    d = P("/p/sub/IMG_001-1.jpg", mtime=1.7e9 + 10)
    g = G(MatchKind.EXACT, b, c, d, a)
    assert recommend(g) == {a.path}


def test_exact_group_then_oldest_then_shortest_path():
    old = P("/very/long/folder/name/a.jpg", mtime=1.7e9 + 10)
    new = P("/a.jpg", mtime=1.7e9 + 20)
    assert recommend(G(MatchKind.EXACT, new, old)) == {old.path}
    t1 = P("/x/a.jpg", mtime=99, taken=datetime(2020, 1, 1))
    t2 = P("/y/a.jpg", mtime=1, taken=datetime(2021, 1, 1))
    assert recommend(G(MatchKind.EXACT, t2, t1)) == {t1.path}  # earlier *taken* wins over mtime
    s1, s2 = P("/a/b.jpg", mtime=5), P("/a/bb/b.jpg", mtime=5)
    assert recommend(G(MatchKind.EXACT, s2, s1)) == {s1.path}


def test_best_quality_order():
    base = dict(w=1000, h=1000)
    big = P("/big.jpg", w=2000, h=1500, sharp=1, size=10)
    assert recommend(G(MatchKind.SIMILAR, P("/s.jpg", **base), big)) == {big.path}
    sharp = P("/sharp.jpg", sharp=50, **base)
    assert recommend(G(MatchKind.SIMILAR, P("/dull.jpg", sharp=5, **base), sharp)) == {sharp.path}
    large = P("/large.jpg", size=9000, **base)
    assert recommend(G(MatchKind.SIMILAR, P("/small.jpg", size=100, **base), large)) == {large.path}
    exif = P("/exif.jpg", camera="Canon", **base)
    assert recommend(G(MatchKind.SIMILAR, P("/noexif.jpg", **base), exif)) == {exif.path}
    short, long_ = P("/a.jpg", **base), P("/aaaa/a.jpg", **base)
    assert recommend(G(MatchKind.SIMILAR, long_, short)) == {short.path}
    assert recommend(G(MatchKind.SIMILAR, P("/b (1).jpg", **base), P("/bb.jpg", **base))) == {Path("/bb.jpg")}


def test_other_rules():
    a = P("/a/aaaaaaaa.jpg", size=300, mtime=1.7e9 + 30, taken=datetime(2020, 1, 1))
    b = P("/b.jpg", size=100, mtime=1.7e9 + 10, taken=datetime(2022, 1, 1))
    c = P("/cc/c.jpg", size=900, mtime=1.6e9)
    g = G(MatchKind.SIMILAR, a, b, c)
    assert recommend(g, KeepRule.OLDEST) == {a.path}
    assert recommend(g, KeepRule.NEWEST) in ({b.path}, {a.path}, {c.path})
    assert recommend(g, KeepRule.NEWEST) == {b.path}
    assert recommend(g, KeepRule.LARGEST_FILE) == {c.path}
    assert recommend(g, KeepRule.SHORTEST_PATH) == {b.path}


@pytest.mark.parametrize("rule", list(KeepRule))
@pytest.mark.parametrize("kind", list(MatchKind))
def test_exactly_one_kept_and_deterministic(rule, kind):
    photos = [P(f"/d{i}/img.jpg", size=100, mtime=5.0) for i in range(4)]  # total ties
    first = recommend(G(kind, *photos), rule)
    assert len(first) == 1
    assert recommend(G(kind, *reversed(photos)), rule) == first
    assert best_photo(photos, rule).path in {p.path for p in photos}


def test_empty_group_rejected():
    with pytest.raises(ValueError):
        recommend(G(MatchKind.EXACT))
