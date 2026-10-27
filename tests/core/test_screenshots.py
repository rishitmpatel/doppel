"""Screenshots and documents: flat backgrounds + identical layouts defeat coarse perceptual
hashes, so candidate pairs must pass a structural thumbnail check (cluster.confirm_pairs)."""

from __future__ import annotations

import numpy as np
from PIL import Image

import imgfactory as F
import shotfactory as S
from doppel.core import cluster, hashing
from doppel.core.finder import ScanOptions, scan
from doppel.core.models import MatchKind


def opts(root, **kw):
    return ScanOptions(roots=[root], min_size_bytes=0, workers=2, **kw)


def save_set(images, root, prefix="shot"):
    root.mkdir(parents=True, exist_ok=True)
    return [_save(im, root / f"{prefix}_{i:03d}.png") for i, im in enumerate(images)]


def _save(im, path):
    im.save(path)
    return path


def names(g):
    return sorted(p.path.name for p in g.photos)


def test_forty_different_chat_screenshots_and_five_whatsapp_resaves(tmp_path):
    """The orchestrator's repro: nothing but the 5 re-saves may be grouped."""
    for i in range(40):
        S.chat_screenshot(i).save(tmp_path / f"shot_{i:02d}.png")
    for i in range(5):
        im = Image.open(tmp_path / f"shot_{i:02d}.png").convert("RGB").resize((540, 1170))
        im.save(tmp_path / f"wa_{i:02d}.jpg", quality=55)
        im.close()
    res = scan(opts(tmp_path))
    assert res.errors == []
    got = sorted(names(g) for g in res.groups)
    assert got == [[f"shot_{i:02d}.png", f"wa_{i:02d}.jpg"] for i in range(5)]
    assert all(g.kind is MatchKind.SIMILAR for g in res.groups)


def test_two_hundred_mixed_screenshots_and_documents_never_match(tmp_path):
    save_set(S.screenshot_set(200, scale=0.35), tmp_path)
    res = scan(opts(tmp_path))
    assert res.scanned == 200 and res.errors == []
    assert res.groups == []


def test_resaved_and_resized_screenshots_and_documents_still_match(tmp_path):
    originals = S.screenshot_set(16)
    save_set(originals, tmp_path)
    for i, im in enumerate(originals):
        w, h = im.size
        variant = (
            F.save_jpeg(im.resize((w // 2, h // 2)), tmp_path / f"v_{i:03d}.jpg", 55) if i % 4 == 0
            else F.save_jpeg(im, tmp_path / f"v_{i:03d}.jpg", 70) if i % 4 == 1
            else _save(im.resize((w * 3 // 4, h * 3 // 4), Image.Resampling.LANCZOS), tmp_path / f"v_{i:03d}.png") if i % 4 == 2
            else F.save_jpeg(im.resize((w // 3, h // 3)), tmp_path / f"v_{i:03d}.jpg", 80)
        )
        assert variant.exists()
    res = scan(opts(tmp_path))
    pairs = sorted(names(g) for g in res.groups)
    assert len(pairs) == 16, pairs
    for pair in pairs:
        assert pair[0].startswith("shot_") and pair[1].startswith("v_") and pair[0][5:8] == pair[1][2:5]


def test_cropped_graphic_still_matches_but_a_different_page_does_not(tmp_path):
    page = S.document_page(3)
    page.save(tmp_path / "page.png")
    F.save_jpeg(F.cropped(page, 0.02), tmp_path / "page_cropped.jpg")
    S.document_page(4).save(tmp_path / "other_page.png")
    res = scan(opts(tmp_path))
    assert [names(g) for g in res.groups] == [["page.png", "page_cropped.jpg"]]


def test_same_chat_layout_with_different_words_is_not_a_match(tmp_path):
    """Same bubble geometry, only the text differs."""
    import random

    def chat(words_seed):
        rng = random.Random(words_seed)
        im = S.Image.new("RGB", (540, 1170), "white")
        d = S.ImageDraw.Draw(im)
        d.rectangle([0, 0, 540, 90], fill=(18, 140, 126))
        y = 120
        for k in range(10):
            x = 20 if k % 2 else 200
            d.rounded_rectangle([x - 10, y - 5, x + 300, y + 30], 10, fill=(220, 248, 198) if x > 100 else (240, 240, 240))
            d.text((x, y), " ".join(rng.choices(S.WORDS, k=5)), fill="black", font=S._font(14))
            y += 45
        return im

    chat(1).save(tmp_path / "a.png")
    chat(2).save(tmp_path / "b.png")
    chat(3).save(tmp_path / "c.png")
    assert scan(opts(tmp_path)).groups == []


# ------------------------------------------------------------------ confirm_pairs unit tests
def _analysis(img, tmp_path, name="x.png"):
    p = tmp_path / name
    img.save(p)
    return hashing.analyze_image(p)


def _confirm(a, b):
    return bool(cluster.confirm_pairs(np.array([0]), np.array([1]), [a.thumb, b.thumb], [a.graphic, b.graphic])[0])


def test_confirm_pairs_strict_for_graphics_loose_for_photos(tmp_path):
    a = _analysis(S.chat_screenshot(1, (540, 1170)), tmp_path, "a.png")
    b = _analysis(S.chat_screenshot(2, (540, 1170)), tmp_path, "b.png")
    twin = _analysis(S.chat_screenshot(1, (540, 1170)).resize((270, 585)), tmp_path, "t.png")
    assert a.graphic >= cluster.GRAPHIC_SHARE and len(a.thumb) == hashing.THUMB_SIZE ** 2
    assert _confirm(a, twin) and not _confirm(a, b)
    photo = F.photo(1, (400, 300))
    pa = _analysis(photo, tmp_path, "pa.png")
    assert pa.graphic < cluster.GRAPHIC_SHARE
    assert _confirm(pa, _analysis(F.cropped(photo, 0.03), tmp_path, "pc.png"))   # photo crops allowed
    assert not _confirm(pa, _analysis(F.photo(2, (400, 300)), tmp_path, "pd.png"))  # gross mismatch rejected


def test_confirm_pairs_edge_cases():
    assert len(cluster.confirm_pairs(np.empty(0, int), np.empty(0, int), [], [])) == 0
    t = bytes(range(256)) * 16
    same = cluster.confirm_pairs(np.array([0, 0]), np.array([1, 1]), [t, t], [0.9, 0.9])
    assert same.tolist() == [True, True]
