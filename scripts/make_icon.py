"""Generate the Doppel app icon (two overlapping rounded photo frames).

Outputs into src/doppel/gui/assets/:
    icon.png        256 px   (window / about dialog)
    icon_1024.png   1024 px  (source for macOS .icns)
    icon.ico        multi-size Windows icon (16..256)

Usage:  python scripts/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "src" / "doppel" / "gui" / "assets"
S = 4096  # supersampled canvas
TEAL_TOP = (45, 212, 191)
TEAL_BOT = (8, 118, 128)


def _gradient(size: int, top, bottom) -> Image.Image:
    import numpy as np

    y = np.linspace(0.0, 1.0, size)[:, None]
    x = np.linspace(0.0, 1.0, size)[None, :]
    t = np.clip(y * 0.85 + x * 0.15, 0, 1)  # mostly vertical, slightly diagonal
    arr = np.stack([top[i] + (bottom[i] - top[i]) * t for i in range(3)], axis=-1)
    return Image.fromarray(arr.astype("uint8"), "RGB")


def _rounded_mask(size: int, box, radius) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


def _shadow(size: int, box, radius, offset, blur, alpha) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(m).rounded_rectangle(
        (x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]), radius=radius, fill=alpha
    )
    return m.filter(ImageFilter.GaussianBlur(blur))


def _scene(w: int, h: int) -> Image.Image:
    """A tiny landscape photo: sky, sun, two hills."""
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(255 - 70 * t), int(205 - 30 * t), int(160 + 40 * t)))
    r = int(h * 0.13)
    cx, cy = int(w * 0.70), int(h * 0.30)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 247, 224))
    d.ellipse((int(-w * 0.15), int(h * 0.58), int(w * 0.70), int(h * 1.5)), fill=(20, 120, 120))
    d.ellipse((int(w * 0.30), int(h * 0.68), int(w * 1.25), int(h * 1.6)), fill=(11, 83, 98))
    return img


def build() -> Image.Image:
    size = S
    # Background squircle-ish tile with gradient
    tile_box = (int(size * 0.04), int(size * 0.04), int(size * 0.96), int(size * 0.96))
    bg = _gradient(size, TEAL_TOP, TEAL_BOT).convert("RGBA")
    mask = _rounded_mask(size, tile_box, int(size * 0.22))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(bg, (0, 0), mask)

    # subtle top highlight
    hl = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    ImageDraw.Draw(hl).ellipse((-size * 0.2, -size * 0.75, size * 1.2, size * 0.45), fill=(255, 255, 255, 38))
    hl.putalpha(ImageChops.multiply(hl.getchannel("A"), mask))
    canvas = Image.alpha_composite(canvas, hl)

    fw, fh = int(size * 0.46), int(size * 0.38)
    rad = int(size * 0.055)

    # back frame (translucent white outline-ish card)
    bx0, by0 = int(size * 0.20), int(size * 0.22)
    back_box = (bx0, by0, bx0 + fw, by0 + fh)
    sh = _shadow(size, back_box, rad, (0, int(size * 0.012)), size * 0.012, 70)
    canvas = Image.alpha_composite(canvas, Image.merge("RGBA", (
        Image.new("L", (size, size), 6), Image.new("L", (size, size), 50),
        Image.new("L", (size, size), 70), sh)))
    back = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    bd = ImageDraw.Draw(back)
    bd.rounded_rectangle(back_box, radius=rad, fill=(255, 255, 255, 120))
    inset = int(size * 0.02)
    bd.rounded_rectangle(
        (back_box[0] + inset, back_box[1] + inset, back_box[2] - inset, back_box[3] - inset),
        radius=rad - inset // 2, fill=(255, 255, 255, 0), outline=(255, 255, 255, 170), width=int(size * 0.006))
    canvas = Image.alpha_composite(canvas, back)

    # front frame: white card with a scene inside
    fx0, fy0 = int(size * 0.34), int(size * 0.40)
    front_box = (fx0, fy0, fx0 + fw, fy0 + fh)
    sh = _shadow(size, front_box, rad, (0, int(size * 0.02)), size * 0.02, 110)
    canvas = Image.alpha_composite(canvas, Image.merge("RGBA", (
        Image.new("L", (size, size), 4), Image.new("L", (size, size), 40),
        Image.new("L", (size, size), 52), sh)))
    card = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle(front_box, radius=rad, fill=(255, 255, 255, 255))
    canvas = Image.alpha_composite(canvas, card)
    pad = int(size * 0.026)
    ib = (front_box[0] + pad, front_box[1] + pad, front_box[2] - pad, front_box[3] - pad)
    scene = _scene(ib[2] - ib[0], ib[3] - ib[1]).convert("RGBA")
    smask = _rounded_mask(size, ib, rad - pad // 2).crop(ib)
    canvas.paste(scene, (ib[0], ib[1]), smask)
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = build()
    img1024 = big.resize((1024, 1024), Image.Resampling.LANCZOS)
    img1024.save(OUT / "icon_1024.png")
    img1024.resize((256, 256), Image.Resampling.LANCZOS).save(OUT / "icon.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    # Pillow's ICO writer resamples from the base image; give it the best source
    img1024.save(OUT / "icon.ico", format="ICO", sizes=[(s, s) for s in sizes])
    print("wrote", [p.name for p in OUT.iterdir()])


if __name__ == "__main__":
    main()
