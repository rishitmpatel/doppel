"""Generated demo photos + a hand-built ScanResult, used by screenshots and GUI tests.

No external images: colourful landscapes are painted with numpy + Pillow so the
screenshots look like a real photo library without shipping anyone's pictures.
"""
from __future__ import annotations

import math
import zlib
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from doppel.core.models import DuplicateGroup, MatchKind, PhotoInfo, ScanResult
from doppel.core.selector import KeepRule, recommend


# --------------------------------------------------------------------------- painting
def _lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _vgrad(w: int, h: int, stops: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    ys = np.linspace(0, 1, h)
    out = np.zeros((h, w, 3), dtype=np.float32)
    for c in range(3):
        out[:, :, c] = np.interp(ys, [s[0] for s in stops], [s[1][c] for s in stops])[:, None]
    return out


def _ridge(w: int, base: float, amp: float, rng, octaves=3, sharp=False) -> np.ndarray:
    x = np.linspace(0, 1, w)
    y = np.zeros(w)
    for o in range(octaves):
        f = (1.2 + o * 1.7) * (1 + rng.random() * 0.6)
        y += (amp / (1 + o * 1.4)) * np.sin(x * math.pi * 2 * f + rng.random() * 6.28)
    if sharp:
        y = -np.abs(y) * 1.3
    return base + y


def _poly_under(draw: ImageDraw.ImageDraw, ys: np.ndarray, h: int, fill) -> None:
    pts = [(i, float(y)) for i, y in enumerate(ys)] + [(len(ys) - 1, h), (0, h)]
    draw.polygon(pts, fill=fill)


def _glow(img: Image.Image, cx: float, cy: float, r: float, color, strength=0.8) -> Image.Image:
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
    a = np.clip(1 - d, 0, 1) ** 2 * strength
    arr = np.asarray(img, dtype=np.float32)
    col = np.array(color, dtype=np.float32)
    arr = arr * (1 - a[..., None]) + col * a[..., None]
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


def _finish(img: Image.Image, rng) -> Image.Image:
    w, h = img.size
    arr = np.asarray(img, dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    v = 1 - 0.22 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 2
    arr *= v[..., None]
    arr += rng.normal(0, 2.2, arr.shape)
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))


KINDS = ["sunset", "alpine", "beach", "forest", "city", "desert", "lake", "meadow", "autumn", "harbor"]


def scene(kind: str, seed: int, w: int = 1200, h: int = 800) -> Image.Image:
    rng = np.random.default_rng(seed * 7919 + zlib.crc32(kind.encode()) % 1000)
    j = lambda c, a=14: tuple(int(max(0, min(255, v + rng.integers(-a, a + 1)))) for v in c)  # noqa: E731
    if kind == "sunset":
        arr = _vgrad(w, h, [(0, j((52, 41, 110))), (0.35, j((178, 76, 125))), (0.6, j((255, 140, 80))), (0.75, j((255, 214, 120)))])
        img = Image.fromarray(arr.astype(np.uint8))
        sx, sy = w * (0.3 + rng.random() * 0.4), h * 0.62
        img = _glow(img, sx, sy, h * 0.7, (255, 200, 120), 0.9)
        d = ImageDraw.Draw(img)
        d.ellipse((sx - h * 0.06, sy - h * 0.06, sx + h * 0.06, sy + h * 0.06), fill=(255, 244, 214))
        for k, (col, base, amp) in enumerate([((120, 70, 110), 0.72, 0.03), ((78, 48, 96), 0.80, 0.04), ((38, 28, 66), 0.90, 0.04)]):
            _poly_under(d, _ridge(w, h * base, h * amp, rng), h, j(col, 6))
    elif kind == "alpine":
        arr = _vgrad(w, h, [(0, j((70, 130, 210))), (0.55, j((170, 210, 240))), (0.75, j((225, 236, 245)))])
        img = Image.fromarray(arr.astype(np.uint8))
        d = ImageDraw.Draw(img)
        far = _ridge(w, h * 0.55, h * 0.12, rng, 4, sharp=True)
        _poly_under(d, far, h, j((120, 140, 170), 8))
        thr = h * 0.47
        run: list[int] = []
        for i in range(w + 1):
            if i < w and far[i] < thr:
                run.append(i)
                continue
            if len(run) > 3:
                top = [(x, float(far[x])) for x in run]
                bot = [(x, float(far[x] + (thr - far[x]) * 0.55 + 6 * math.sin(x * 0.2))) for x in reversed(run)]
                d.polygon(top + bot, fill=(246, 250, 255))
            run = []
        near = _ridge(w, h * 0.74, h * 0.07, rng, 3)
        _poly_under(d, near, h, j((42, 92, 80), 8))
        for _ in range(60):
            x = rng.integers(0, w)
            y = int(near[x]) + rng.integers(0, int(h * 0.2))
            s = rng.integers(18, 54)
            d.polygon([(x, y - s * 2.2), (x - s * 0.55, y), (x + s * 0.55, y)], fill=j((22, 66, 52), 10))
    elif kind == "beach":
        arr = _vgrad(w, h, [(0, j((110, 190, 235))), (0.45, j((200, 232, 248))), (0.46, j((40, 160, 180))), (0.62, j((70, 200, 200))),
                            (0.64, j((240, 226, 190))), (1, j((226, 200, 150)))])
        img = Image.fromarray(arr.astype(np.uint8))
        img = _glow(img, w * 0.75, h * 0.18, h * 0.5, (255, 250, 220), 0.7)
        d = ImageDraw.Draw(img)
        for k in range(6):
            y = h * (0.50 + k * 0.025)
            ys = y + 4 * np.sin(np.linspace(0, 14 + k, w) + k)
            d.line([(i, float(v)) for i, v in enumerate(ys)], fill=(235, 250, 250), width=2)
        d.polygon([(0, h * 0.86), (w * 0.4, h * 0.70), (w * 0.9, h * 0.66), (w, h * 0.7), (w, h), (0, h)], fill=j((230, 205, 160), 6))
        tx = w * 0.14
        d.line([(tx, h), (tx + 30, h * 0.5)], fill=(70, 50, 30), width=14)
        for a in range(7):
            ang = -0.4 + a * 0.5
            d.polygon([(tx + 30, h * 0.5), (tx + 30 + 240 * math.cos(ang), h * 0.5 - 90 * math.sin(abs(ang) + 0.6)),
                       (tx + 30 + 200 * math.cos(ang), h * 0.5 - 20 * math.sin(abs(ang)))], fill=(30, 100, 60))
    elif kind == "forest":
        arr = _vgrad(w, h, [(0, j((196, 226, 205))), (0.5, j((140, 190, 160))), (1, j((26, 70, 52)))])
        img = Image.fromarray(arr.astype(np.uint8))
        img = _glow(img, w * 0.65, h * 0.1, h * 0.9, (255, 250, 210), 0.65)
        d = ImageDraw.Draw(img)
        for layer, (n, smin, smax, col) in enumerate([(26, 80, 130, (92, 150, 120)), (22, 120, 190, (54, 112, 84)), (16, 170, 270, (24, 70, 52))]):
            base = h * (0.55 + layer * 0.17)
            for _ in range(n):
                x = rng.integers(-20, w + 20)
                s = rng.integers(smin, smax)
                y = base + rng.integers(0, int(h * 0.12))
                c = j(col, 8)
                for t in range(4):
                    d.polygon([(x, y - s * (1 - t * 0.2)), (x - s * (0.3 + t * 0.07), y - s * (0.7 - t * 0.2)), (x + s * (0.3 + t * 0.07), y - s * (0.7 - t * 0.2))], fill=c)
                d.rectangle((x - 5, y - s * 0.15, x + 5, y + s * 0.2), fill=(50, 34, 24))
    elif kind == "city":
        arr = _vgrad(w, h, [(0, j((14, 18, 52))), (0.5, j((92, 44, 120))), (0.72, j((236, 110, 120)))])
        img = Image.fromarray(arr.astype(np.uint8))
        img = _glow(img, w * 0.78, h * 0.2, h * 0.28, (255, 240, 220), 0.9)
        d = ImageDraw.Draw(img)
        d.ellipse((w * 0.78 - 30, h * 0.2 - 30, w * 0.78 + 30, h * 0.2 + 30), fill=(255, 250, 238))
        x = 0
        while x < w:
            bw = int(rng.integers(50, 120))
            bh = int(rng.integers(int(h * 0.15), int(h * 0.5)))
            top = h * 0.78 - bh
            d.rectangle((x, top, x + bw, h * 0.78), fill=j((20, 22, 44), 6))
            for wy in range(int(top) + 12, int(h * 0.76), 22):
                for wx in range(x + 8, x + bw - 8, 16):
                    if rng.random() < 0.45:
                        d.rectangle((wx, wy, wx + 7, wy + 11), fill=(255, int(190 + rng.integers(0, 50)), int(110 + rng.integers(0, 60))))
            x += bw + int(rng.integers(0, 6))
        d.rectangle((0, h * 0.78, w, h), fill=(18, 20, 44))
        for k in range(40):
            y = h * 0.8 + k * (h * 0.2 / 40)
            d.line([(0, y), (w, y)], fill=(40 + k, 30 + k // 2, 70 + k), width=1)
        for _ in range(60):
            x = int(rng.integers(0, w))
            d.rectangle((x, h * 0.8, x + 3, h * 0.8 + rng.integers(10, 80)), fill=(255, 190, 120))
    elif kind == "desert":
        arr = _vgrad(w, h, [(0, j((70, 140, 220))), (0.45, j((250, 214, 170))), (0.6, j((255, 180, 110)))])
        img = Image.fromarray(arr.astype(np.uint8))
        img = _glow(img, w * 0.25, h * 0.3, h * 0.5, (255, 250, 230), 0.8)
        d = ImageDraw.Draw(img)
        for col, base, amp in [((232, 150, 90), 0.62, 0.05), ((206, 112, 70), 0.74, 0.07), ((150, 70, 52), 0.88, 0.06)]:
            _poly_under(d, _ridge(w, h * base, h * amp, rng, 3), h, j(col, 6))
    elif kind == "lake":
        arr = _vgrad(w, h, [(0, j((250, 190, 190))), (0.4, j((255, 222, 200))), (0.5, j((255, 222, 200))), (0.5, j((150, 160, 200))), (1, j((70, 90, 140)))])
        img = Image.fromarray(arr.astype(np.uint8))
        d = ImageDraw.Draw(img)
        ridge = _ridge(w, h * 0.38, h * 0.1, rng, 4, sharp=True)
        _poly_under(d, np.minimum(ridge, h * 0.5), int(h * 0.5), j((88, 76, 126), 6))
        refl = h * 0.5 + (h * 0.5 - np.minimum(ridge, h * 0.5))
        pts = [(i, float(y)) for i, y in enumerate(refl)] + [(w - 1, h * 0.5), (0, h * 0.5)]
        d.polygon(pts, fill=j((98, 98, 150), 6))
        for k in range(50):
            y = h * 0.5 + k * (h * 0.5 / 50)
            d.line([(0, y), (w, y)], fill=(180, 190, 230), width=1) if k % 6 == 0 else None
    elif kind == "meadow":
        arr = _vgrad(w, h, [(0, j((100, 170, 235))), (0.6, j((200, 230, 245)))])
        img = Image.fromarray(arr.astype(np.uint8))
        d = ImageDraw.Draw(img)
        for _ in range(7):
            cx, cy = rng.integers(0, w), rng.integers(30, int(h * 0.4))
            for k in range(6):
                rx = int(rng.integers(40, 90))
                d.ellipse((cx + k * 40 - rx, cy - 22, cx + k * 40 + rx, cy + 22), fill=(255, 255, 255))
        img = img.filter(ImageFilter.GaussianBlur(3))
        d = ImageDraw.Draw(img)
        for col, base, amp in [((120, 190, 110), 0.6, 0.04), ((80, 160, 80), 0.72, 0.05), ((50, 128, 60), 0.86, 0.04)]:
            _poly_under(d, _ridge(w, h * base, h * amp, rng, 3), h, j(col, 6))
        for _ in range(420):
            x, y = int(rng.integers(0, w)), int(rng.integers(int(h * 0.72), h))
            r = 2 + (y - h * 0.72) / h * 14
            d.ellipse((x - r, y - r, x + r, y + r), fill=[(255, 90, 120), (255, 230, 80), (250, 250, 250), (180, 120, 240)][int(rng.integers(0, 4))])
    elif kind == "autumn":
        arr = _vgrad(w, h, [(0, j((250, 200, 130))), (0.5, j((240, 150, 90))), (1, j((120, 60, 40)))])
        img = Image.fromarray(arr.astype(np.uint8))
        img = _glow(img, w * 0.5, h * 0.25, h * 0.6, (255, 240, 190), 0.7)
        d = ImageDraw.Draw(img)
        for layer, (n, col) in enumerate([(30, (214, 110, 50)), (22, (180, 70, 40)), (14, (110, 40, 30))]):
            base = h * (0.55 + layer * 0.16)
            for _ in range(n):
                x = int(rng.integers(0, w))
                r = int(rng.integers(50, 110) * (1 + layer * 0.3))
                y = base + rng.integers(0, 60)
                d.rectangle((x - 5, y, x + 5, y + 110), fill=(60, 36, 26))
                d.ellipse((x - r, y - r * 1.1, x + r, y + r * 0.4), fill=j(col, 14))
        d.rectangle((0, h * 0.9, w, h), fill=(100, 56, 34))
    else:  # harbor
        arr = _vgrad(w, h, [(0, j((120, 180, 230))), (0.5, j((230, 240, 250))), (0.5, j((50, 110, 160))), (1, j((20, 60, 100)))])
        img = Image.fromarray(arr.astype(np.uint8))
        d = ImageDraw.Draw(img)
        for i in range(7):
            bx = w * (0.08 + i * 0.13)
            bw, bh = w * 0.1, h * (0.12 + 0.1 * rng.random())
            col = [(230, 90, 80), (250, 200, 80), (90, 170, 200), (240, 240, 240), (120, 190, 130)][i % 5]
            d.rectangle((bx, h * 0.5 - bh, bx + bw, h * 0.5), fill=col)
            d.polygon([(bx - 6, h * 0.5 - bh), (bx + bw / 2, h * 0.5 - bh - 40), (bx + bw + 6, h * 0.5 - bh)], fill=(90, 60, 60))
            d.rectangle((bx + bw * 0.35, h * 0.5 - bh * 0.5, bx + bw * 0.65, h * 0.5), fill=(60, 40, 40))
            d.rectangle((bx, h * 0.5, bx + bw, h * 0.5 + bh * 0.8), fill=tuple(int(c * 0.55) for c in col))
        for k in range(30):
            y = h * 0.5 + k * (h * 0.5 / 30)
            d.line([(0, y + 2 * math.sin(k)), (w, y)], fill=(70, 130, 180), width=1)
    return _finish(img, rng)


# --------------------------------------------------------------------------- variants
def variant(img: Image.Image, how: str) -> Image.Image:
    if how == "resize":
        return img.resize((img.width // 2, img.height // 2), Image.Resampling.LANCZOS)
    if how == "bright":
        return ImageEnhance.Brightness(img).enhance(1.12)
    if how == "crop":
        w, h = img.size
        return img.crop((int(w * 0.02), int(h * 0.02), int(w * 0.98), int(h * 0.98)))
    if how == "warm":
        arr = np.asarray(img, dtype=np.float32)
        arr[..., 0] *= 1.08
        arr[..., 2] *= 0.92
        return ImageEnhance.Contrast(Image.fromarray(arr.clip(0, 255).astype(np.uint8))).enhance(1.08)
    if how == "mono":
        return ImageEnhance.Contrast(img.convert("L").convert("RGB")).enhance(1.1)
    return img


def _save(img: Image.Image, path: Path, q: int = 90) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=q, subsampling=0 if q > 85 else 2)


INFLATE = 1.0  # screenshots pretend the files are camera-sized (metadata only)


def _info(path: Path, taken: datetime | None, camera: str | None, sharp: float) -> PhotoInfo:
    with Image.open(path) as im:
        w, h = im.size
    st = path.stat()
    k = INFLATE
    return PhotoInfo(path=path, size=int(st.st_size * (1 if k == 1 else k * k * 2.4)), mtime=st.st_mtime, width=int(w * k), height=int(h * k), format="JPEG",
                     taken=taken, camera=camera, sharpness=sharp)


# --------------------------------------------------------------------------- result
def build_demo(root: Path) -> ScanResult:
    """Create demo photos under ``root`` and return a ScanResult describing duplicates among them."""
    root = Path(root)
    pics = root / "Pictures"
    if pics.exists():
        shutil.rmtree(pics)
    base_date = datetime(2023, 6, 3, 9, 14)
    cams = ["Apple iPhone 14", "Canon EOS R6", "Samsung Galaxy S23", "Sony ILCE-7M3"]
    groups: list[DuplicateGroup] = []
    gid = 0

    def exact(kind: str, seed: int, folder_names: list[tuple[str, str]], size=(1600, 1067), when=0):
        nonlocal gid
        img = scene(kind, seed, *size)
        taken = base_date + timedelta(days=when * 9, minutes=when * 37)
        photos = []
        for k, (folder, name) in enumerate(folder_names):
            p = pics / folder / name
            _save(img, p, 92)
            if k:
                shutil.copystat(photos[0].path, p)
            photos.append(_info(p, taken, cams[seed % 4], 180.0))
        g = DuplicateGroup(id=gid, kind=MatchKind.EXACT, photos=photos, keep=set(), similarity=1.0)
        g.keep = recommend(g, KeepRule.BEST_QUALITY)
        groups.append(g)
        gid += 1

    def similar(kind: str, seed: int, folder: str, base_name: str, hows: list[str], size=(1800, 1200), when=0, portrait=False):
        nonlocal gid
        w, h = size if not portrait else (size[1], size[0])
        img = scene(kind, seed, w, h)
        taken = base_date + timedelta(days=when * 6 + 2, minutes=when * 53)
        photos = []
        for k, how in enumerate(["orig"] + hows):
            im = img if how == "orig" else variant(img, how)
            name = f"{base_name}.jpg" if how == "orig" else f"{base_name}_{how}.jpg" if how != "resize" else f"{base_name} - small.jpg"
            p = pics / folder / name
            q = 60 if how == "bright" and k == 2 else 90
            _save(im, p, q)
            photos.append(_info(p, taken + timedelta(seconds=k * 4), cams[seed % 4], 220.0 - 40 * k))
        sim = 0.97 - 0.01 * (len(hows) % 3)
        g = DuplicateGroup(id=gid, kind=MatchKind.SIMILAR, photos=photos, keep=set(), similarity=sim)
        g.keep = recommend(g, KeepRule.BEST_QUALITY)
        groups.append(g)
        gid += 1

    exact("sunset", 1, [("Family Photos/Summer in Lisbon", "IMG_4021.jpg"), ("Family Photos/Summer in Lisbon", "IMG_4021 (1).jpg"),
                        ("Backup 2023/Phone", "IMG_4021.jpg")], when=0)
    similar("alpine", 2, "Family Photos/Alps Trip", "DSC_0312", ["resize", "bright", "crop"], when=1)
    exact("beach", 3, [("Camera Uploads", "20230704_141233.jpg"), ("Downloads", "20230704_141233 - Copy.jpg")], when=2)
    similar("forest", 4, "Family Photos/Black Forest", "IMG_5530", ["warm", "resize"], when=3)
    similar("city", 5, "Camera Uploads", "PXL_20230811_201455", ["bright", "resize"], when=4, portrait=False)
    exact("desert", 6, [("Family Photos/Morocco", "IMG_7102.jpg"), ("Backup 2023/Phone", "IMG_7102.jpg"), ("Desktop", "morocco-dunes.jpg")], when=5)
    similar("lake", 7, "Family Photos/Lake Bled", "DSC_1844", ["crop", "mono"], when=6)
    similar("meadow", 8, "Camera Uploads", "IMG_2208", ["resize", "warm", "bright"], size=(1500, 1000), when=7)
    exact("autumn", 9, [("Camera Uploads", "IMG_8841.jpg"), ("Camera Uploads", "IMG_8841 (2).jpg")], when=8)
    similar("harbor", 10, "Family Photos/Croatia", "IMG_3317", ["bright", "crop"], when=9)
    similar("sunset", 11, "Family Photos/Summer in Lisbon", "IMG_4107", ["warm", "resize"], when=10)
    similar("beach", 12, "Downloads", "beach-sunday", ["resize", "crop"], when=11)
    exact("forest", 13, [("Backup 2023/Phone", "IMG_5601.jpg"), ("Family Photos/Black Forest", "IMG_5601.jpg")], when=12)
    similar("alpine", 14, "Family Photos/Alps Trip", "DSC_0377", ["bright", "resize"], when=13, portrait=True)
    groups.sort(key=lambda g: g.reclaimable_bytes, reverse=True)
    errors = [(pics / "Old Phone" / f"IMG_{n}.jpg", "The file is damaged or is not a real photo") for n in (1017, 1018, 1230)]
    return ScanResult(groups=groups, errors=errors, scanned=5320, elapsed=47.0)


def fake_groups(n: int, base: Path | None = None) -> list[DuplicateGroup]:
    """Many synthetic groups (files need not exist) for responsiveness tests."""
    base = base or Path("/nonexistent/photos")
    out = []
    for i in range(n):
        k = 2 + (i % 3)
        kind = MatchKind.EXACT if i % 4 == 0 else MatchKind.SIMILAR
        photos = [
            PhotoInfo(path=base / f"g{i:05d}" / f"IMG_{i:05d}_{j}.jpg", size=2_000_000 + 1000 * j, mtime=1.7e9 + i * 100 + j,
                      width=4000 - j * 100, height=3000 - j * 75, format="JPEG", taken=datetime(2022, 1, 1) + timedelta(minutes=i),
                      camera="Test Cam", sharpness=100.0 - j)
            for j in range(k)
        ]
        g = DuplicateGroup(id=i, kind=kind, photos=photos, keep={photos[0].path}, similarity=1.0 if kind == MatchKind.EXACT else 0.95)
        out.append(g)
    return out
