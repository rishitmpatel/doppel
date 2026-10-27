"""Synthetic screenshot-like and document-like images (flat colours, text, repeated layout).

These are the hard negatives for perceptual hashing: different content, near-identical coarse structure.
"""

from __future__ import annotations

import functools
import random

from PIL import Image, ImageDraw, ImageFont

WORDS = ("the quick brown fox jumps over lazy dog meeting notes budget invoice total paid due chat message "
         "hello ok thanks see you tomorrow report quarterly figures attached please review schedule lunch "
         "photo battery wifi settings update version privacy account storage").split()


@functools.lru_cache(maxsize=None)
def _font(size: int):
    return ImageFont.load_default(size=size)


def chat_screenshot(seed: int, size: tuple[int, int] = (1080, 2340), dark: bool = False) -> Image.Image:
    """WhatsApp-style chat: header bar, left/right bubbles with different text."""
    rng = random.Random(seed)
    w, h = size
    s = w / 1080
    font = _font(int(28 * s))
    bg, head = ((18, 27, 34), (31, 44, 52)) if dark else ("white", (18, 140, 126))
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, int(180 * s)], fill=head)
    y = int(240 * s)
    for _ in range(rng.randint(8, 30)):
        if y > h - int(100 * s):
            break
        x = int(40 * s) if rng.random() < .5 else int(400 * s)
        right = x > 100 * s
        fill = ((5, 96, 98) if right else (32, 44, 51)) if dark else ((220, 248, 198) if right else (240, 240, 240))
        d.rounded_rectangle([x - 20 * s, y - 10 * s, x + 600 * s, y + 60 * s], int(20 * s), fill=fill)
        d.text((x, y), " ".join(rng.choices(WORDS, k=5)), fill="white" if dark else "black", font=font)
        y += int(90 * s)
    return im


def document_page(seed: int, size: tuple[int, int] = (1240, 1754)) -> Image.Image:
    """Black text on white: a title and several different paragraphs."""
    rng = random.Random(50_000 + seed)
    w, h = size
    s = w / 1240
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    d.text((int(100 * s), int(100 * s)), " ".join(rng.choices(WORDS, k=3)).title(), fill="black", font=_font(int(48 * s)))
    font = _font(int(26 * s))
    y = int(220 * s)
    for _ in range(rng.randint(2, 6)):
        for _ in range(rng.randint(3, 9)):
            if y > h - int(120 * s):
                break
            d.text((int(100 * s), y), " ".join(rng.choices(WORDS, k=rng.randint(8, 13))), fill="black", font=font)
            y += int(40 * s)
        y += int(50 * s)
    return im


def settings_screenshot(seed: int, size: tuple[int, int] = (1080, 2340)) -> Image.Image:
    """List-of-rows settings screen with toggles; rows differ in label and toggle state."""
    rng = random.Random(90_000 + seed)
    w, h = size
    s = w / 1080
    im = Image.new("RGB", size, (250, 250, 250))
    d = ImageDraw.Draw(im)
    d.text((int(60 * s), int(120 * s)), rng.choice(WORDS).title(), fill="black", font=_font(int(52 * s)))
    y = int(300 * s)
    while y < h - int(160 * s):
        d.text((int(60 * s), y), " ".join(rng.choices(WORDS, k=2)), fill=(30, 30, 30), font=_font(int(34 * s)))
        on = rng.random() < .5
        d.rounded_rectangle([w - 220 * s, y, w - 80 * s, y + 60 * s], int(30 * s), fill=(66, 133, 244) if on else (190, 190, 190))
        cx = w - 110 * s if on else w - 190 * s
        d.ellipse([cx - 22 * s, y + 8 * s, cx + 22 * s, y + 52 * s], fill="white")
        y += int(130 * s)
    return im


def screenshot_set(n: int, scale: float = 0.5) -> list[Image.Image]:
    """``n`` different images cycling through chat, dark chat, settings and document pages
    (phone-sized at ``scale`` x 1080x2340; pages at ``scale`` x 1240x1754)."""
    phone = (int(1080 * scale), int(2340 * scale))
    page = (int(1240 * scale), int(1754 * scale))
    makers = (
        lambda k: chat_screenshot(k, phone),
        lambda k: chat_screenshot(k, phone, dark=True),
        lambda k: settings_screenshot(k, phone),
        lambda k: document_page(k, page),
    )
    return [makers[i % 4](i // 4) for i in range(n)]
