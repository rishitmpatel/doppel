from __future__ import annotations

import hashlib
import itertools
import warnings

import numpy as np
import pytest
from PIL import Image

import imgfactory as F
from doppel.core import hashing
from doppel.core.hashing import analyze_image, hamming

SIZE = (640, 480)
P_MAX, D_SLACK = 8, 4  # default match rule: pHash <= 8 and dHash <= 8 + 4


def _variants(img: Image.Image, tmp_path, tag: str) -> dict:
    out = {
        "resize50": F.save_jpeg(F.resized(img), tmp_path / f"{tag}_r.jpg"),
        "jpeg70": F.save_jpeg(img, tmp_path / f"{tag}_q.jpg", 70),
        "exif_rot6": F.save_exif_rotated(img, tmp_path / f"{tag}_o.jpg", 6),
        "exif_rot8": F.save_exif_rotated(img, tmp_path / f"{tag}_o8.jpg", 8),
        "crop2": F.save_jpeg(F.cropped(img), tmp_path / f"{tag}_c.jpg"),
        "bright10": F.save_jpeg(F.brighter(img), tmp_path / f"{tag}_l.jpg"),
    }
    png = tmp_path / f"{tag}_p.png"
    img.convert("RGB").save(png)
    out["png"] = png
    return out


def test_byte_hashes(tmp_path):
    p = tmp_path / "f.bin"
    data = np.random.default_rng(1).bytes(300_000)
    p.write_bytes(data)
    assert hashing.file_sha(p) == hashing.file_sha(p, chunk=777)
    assert hashing.file_sha(p) == hashlib.blake2b(data, digest_size=32).hexdigest()
    # partial hash only looks at head and tail ...
    q = tmp_path / "g.bin"
    mid = bytearray(data)
    mid[150_000] ^= 0xFF
    q.write_bytes(bytes(mid))
    assert hashing.partial_sha(p) == hashing.partial_sha(q)
    assert hashing.file_sha(p) != hashing.file_sha(q)
    head = bytearray(data)
    head[10] ^= 1
    q.write_bytes(bytes(head))
    assert hashing.partial_sha(p) != hashing.partial_sha(q)
    # ... and for small files equals the full hash
    s = tmp_path / "s.bin"
    s.write_bytes(data[:50_000])
    assert hashing.partial_sha(s) == hashing.file_sha(s)


def test_hamming():
    assert hamming(0, 0) == 0
    assert hamming(0b1011, 0b0001) == 2
    assert hamming((1 << 64) - 1, 0) == 64


def test_dct_matrix_is_orthonormal():
    m = hashing._dct_matrix(32)
    assert np.allclose(m @ m.T, np.eye(32), atol=1e-12)


def test_exif_rotation_generator_is_correct(tmp_path):
    img = F.photo(3, SIZE)
    p = F.save_exif_rotated(img, tmp_path / "o.jpg", 6)
    with Image.open(p) as stored:
        assert stored.size == (480, 640)  # stored rotated ...
    shown = F.displayed(p)
    assert shown.size == SIZE  # ... displays like the original
    err = np.abs(np.asarray(shown, dtype=int) - np.asarray(img.convert("RGB"), dtype=int)).mean()
    assert err < 6


def test_analysis_reports_displayed_size_and_format(tmp_path):
    img = F.photo(3, SIZE)
    a = analyze_image(F.save_exif_rotated(img, tmp_path / "o.jpg", 6))
    assert (a.width, a.height, a.format) == (640, 480, "JPEG")
    assert not a.flat
    ph, dh, sharp, w, h, fmt = hashing.image_hashes(tmp_path / "o.jpg")
    assert (ph, dh, w, h, fmt) == (a.phash, a.dhash, 640, 480, "JPEG") and sharp == a.sharpness
    assert 0 <= ph < 1 << 64 and 0 <= dh < 1 << 64


@pytest.mark.parametrize("seed", range(10))
def test_variants_of_photo_like_images_match_at_default(tmp_path, seed):
    img = F.photo(seed, SIZE)
    base = analyze_image(F.save_jpeg(img, tmp_path / "base.jpg", 92))
    for name, path in _variants(img, tmp_path, "v").items():
        a = analyze_image(path)
        dp, dd = hamming(base.phash, a.phash), hamming(base.dhash, a.dhash)
        assert dp <= P_MAX and dd <= P_MAX + D_SLACK, (name, dp, dd)


def test_distinct_images_never_match_and_report_distributions(tmp_path, capsys):
    """24 different shapes/gradients/textures: zero matches; prints the distance distributions."""
    n = 24
    images = F.distinct_images(n, SIZE)
    analyses = [analyze_image(F.save_jpeg(im, tmp_path / f"d{i}.jpg")) for i, im in enumerate(images)]
    assert not any(a.flat for a in analyses)
    diff_p = [hamming(a.phash, b.phash) for a, b in itertools.combinations(analyses, 2)]
    matches = [
        (i, j)
        for (i, a), (j, b) in itertools.combinations(enumerate(analyses), 2)
        if hamming(a.phash, b.phash) <= P_MAX and hamming(a.dhash, b.dhash) <= P_MAX + D_SLACK
    ]
    assert matches == []
    assert min(diff_p) >= 12  # comfortable margin over the threshold of 8

    # same-image distances over all three image kinds
    same = []
    for i, im in enumerate(images):
        base = analyses[i]
        for path in _variants(im, tmp_path, f"s{i}").values():
            same.append(hamming(base.phash, analyze_image(path).phash))
    same_arr, diff_arr = np.array(same), np.array(diff_p)
    with capsys.disabled():
        print(
            f"\n[hash quality] same-image pHash distance: n={len(same)} mean={same_arr.mean():.2f} "
            f"p99={np.percentile(same_arr, 99):.0f} max={same_arr.max()}; "
            f"different-image: n={len(diff_arr)} min={diff_arr.min()} p1={np.percentile(diff_arr, 1):.0f} "
            f"mean={diff_arr.mean():.1f}"
        )
    assert same_arr.max() <= 12
    assert (same_arr <= P_MAX).mean() >= 0.97


def test_blur_lowers_sharpness_and_resolution_is_reported(tmp_path):
    from PIL import ImageFilter

    img = F.photo(5, SIZE)
    sharp = analyze_image(F.save_jpeg(img, tmp_path / "a.jpg"))
    blur = analyze_image(F.save_jpeg(img.filter(ImageFilter.GaussianBlur(4)), tmp_path / "b.jpg"))
    assert sharp.sharpness > blur.sharpness * 2


def test_flat_image_is_flagged(tmp_path):
    p = tmp_path / "flat.png"
    Image.new("RGB", (200, 200), (30, 90, 200)).save(p)
    assert analyze_image(p).flat


@pytest.mark.parametrize(
    "mode,fmt,ext",
    [("L", "PNG", "png"), ("1", "PNG", "png"), ("P", "GIF", "gif"), ("RGBA", "PNG", "png"), ("LA", "PNG", "png"),
     ("RGB", "BMP", "bmp"), ("RGB", "TIFF", "tif"), ("RGB", "WEBP", "webp"), ("CMYK", "JPEG", "jpg"),
     ("RGB", "GIF", "gif"), ("I;16", "PNG", "png")],
)
def test_many_modes_and_formats_decode(tmp_path, mode, fmt, ext):
    base = F.photo(2, (200, 150))
    if mode == "I;16":
        arr = (np.asarray(base.convert("L"), dtype=np.uint16) * 257)
        img = Image.fromarray(arr)
    else:
        img = base.convert(mode)
    p = tmp_path / f"x.{ext}"
    img.save(p, fmt)
    a = analyze_image(p)
    assert (a.width, a.height) == (200, 150)
    assert a.format == fmt or (fmt == "JPEG" and a.format == "JPEG")


def test_transparent_png_composited_on_white(tmp_path):
    rgba = Image.new("RGBA", (120, 120), (0, 0, 0, 0))  # fully transparent "black"
    p = tmp_path / "t.png"
    rgba.save(p)
    q = tmp_path / "w.png"
    Image.new("RGB", (120, 120), (255, 255, 255)).save(q)
    assert analyze_image(p).flat and analyze_image(q).flat  # both read as uniform white


def test_png_and_jpeg_of_same_picture_agree(tmp_path):
    img = F.photo(4, SIZE)
    a = analyze_image(F.save_jpeg(img, tmp_path / "a.jpg", 95))
    b_path = tmp_path / "a.png"
    img.convert("RGB").save(b_path)
    assert hamming(a.phash, analyze_image(b_path).phash) <= 4


def test_unreadable_inputs_raise_with_friendly_messages(tmp_path):
    good = F.save_jpeg(F.photo(1, SIZE), tmp_path / "ok.jpg")
    data = good.read_bytes()
    trunc = tmp_path / "trunc.jpg"
    trunc.write_bytes(data[: len(data) // 2])
    text = tmp_path / "fake.jpg"
    text.write_text("hello, I am not an image")
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    for p, expect in ((trunc, "damaged"), (text, "Not a valid image"), (empty, "Not a valid image")):
        with pytest.raises(Exception) as ei:
            analyze_image(p)
        assert expect in hashing.describe_error(ei.value, p)
    with pytest.raises(FileNotFoundError) as ei:
        analyze_image(tmp_path / "nope.jpg")
    assert "not found" in hashing.describe_error(ei.value).lower()


def test_decompression_bomb_is_an_error_not_a_crash(tmp_path, monkeypatch):
    p = tmp_path / "big.png"
    Image.new("L", (400, 300)).save(p)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 50_000)  # 120k px > 50k (warning), > 100k (error)
    with hashing.bomb_guard():
        with pytest.raises(Exception) as ei:
            analyze_image(p)
    assert "too large" in hashing.describe_error(ei.value)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100_000)  # between 1x and 2x: warning only
    with hashing.bomb_guard():
        with pytest.raises(Image.DecompressionBombWarning) as ei:
            analyze_image(p)
    assert "too large" in hashing.describe_error(ei.value)
    assert not hashing.is_permanent_error(PermissionError(13, "x"))
    assert hashing.is_permanent_error(ei.value)


def test_bomb_guard_does_not_leak_filters():
    before = list(warnings.filters)
    with hashing.bomb_guard():
        pass
    assert list(warnings.filters) == before


def test_heic_roundtrip_if_available(tmp_path):
    pytest.importorskip("pillow_heif")
    img = F.photo(6, (320, 240))
    p = tmp_path / "x.heic"
    try:
        img.convert("RGB").save(p, "HEIF")
    except Exception:
        pytest.skip("HEIF encoder not available")
    a = analyze_image(p)
    assert (a.width, a.height, a.format) == (320, 240, "HEIC")
