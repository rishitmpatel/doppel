"""Tiny embedded SVG icon set (24x24 grid, stroke based) rendered with QSvgRenderer."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).parent / "assets"

_P = {
    "folder": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.2h7.5A2.5 2.5 0 0 1 21 9.7v7.8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>',
    "folder-plus": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.2h7.5A2.5 2.5 0 0 1 21 9.7v7.8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/><path d="M12 10.8v5.4M9.3 13.5h5.4"/>',
    "folder-open": '<path d="M4 19.5h13.6a2 2 0 0 0 1.9-1.4l1.7-5.2a1.5 1.5 0 0 0-1.4-2H9.2a2 2 0 0 0-1.9 1.4L4 19.5zM4 19.5V6.5A1.5 1.5 0 0 1 5.5 5H9l2 2.2h6.5A1.5 1.5 0 0 1 19 8.7V10"/>',
    "close": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "check": '<path d="M5 12.8l4.4 4.4L19 7.6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.2M12 7.8h.01"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V5.2c0-.7.5-1.2 1.2-1.2h2.6c.7 0 1.2.5 1.2 1.2V7M6.5 7l.9 11.6A2 2 0 0 0 9.4 20.4h5.2a2 2 0 0 0 2-1.8L17.5 7M10 11v5.4M14 11v5.4"/>',
    "arrow-left": '<path d="M19 12H5.5M11.5 6l-6 6 6 6"/>',
    "arrow-right": '<path d="M5 12h13.5M12.5 6l6 6-6 6"/>',
    "chevron-down": '<path d="M6.5 9.5l5.5 5.5 5.5-5.5"/>',
    "chevron-right": '<path d="M9.5 6.5l5.5 5.5-5.5 5.5"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.4-4.4"/>',
    "undo": '<path d="M8.5 5L4 9.5 8.5 14"/><path d="M4.5 9.5h9a6 6 0 0 1 0 12H9"/>',
    "reveal": '<path d="M14 4.5h5.5V10M19.5 4.5L11 13M17.5 14.5v3a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2h3"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    "expand": '<path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/>',
    "compare": '<rect x="3.5" y="5" width="7.5" height="14" rx="2"/><rect x="13" y="5" width="7.5" height="14" rx="2"/>',
    "wand": '<path d="M12 3.5l1.7 4.4 4.4 1.7-4.4 1.7L12 15.7l-1.7-4.4L5.9 9.6l4.4-1.7z"/><path d="M18.5 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    "alert": '<path d="M10.3 4.6a2 2 0 0 1 3.4 0l7.5 13A2 2 0 0 1 19.5 20.6h-15a2 2 0 0 1-1.7-3z"/><path d="M12 9.5v4M12 17h.01"/>',
    "shield": '<path d="M12 3.2l7.5 2.8v5.6c0 4.6-3.2 7.9-7.5 9.2-4.3-1.3-7.5-4.6-7.5-9.2V6z"/><path d="M8.8 12.2l2.2 2.2 4.2-4.4"/>',
    "photo": '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="M20.5 16l-4.8-4.6L7 19.5"/>',
    "photo-off": '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M3.5 4.5l17 15"/>',
    "refresh": '<path d="M19.5 10.5a7.5 7.5 0 1 0-1.4 6.3"/><path d="M19.8 4.5v6h-6"/>',
    "star": '<path d="M12 3.8l2.4 5 5.4.7-4 3.8 1 5.4-4.8-2.6-4.8 2.6 1-5.4-4-3.8 5.4-.7z"/>',
    "keyboard": '<rect x="2.8" y="6" width="18.4" height="12" rx="2.5"/><path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M7.5 14h9"/>',
    "layers": '<path d="M12 3.8l8.5 4.6L12 13 3.5 8.4z"/><path d="M3.5 12.4L12 17l8.5-4.6M3.5 16.2L12 20.8l8.5-4.6"/>',
    "sparkle": '<path d="M12 3.5l1.7 4.4 4.4 1.7-4.4 1.7L12 15.7l-1.7-4.4L5.9 9.6l4.4-1.7z"/>',
    "list": '<path d="M8.5 7h11M8.5 12h11M8.5 17h11M4.5 7h.01M4.5 12h.01M4.5 17h.01"/>',
    "circle-check": '<circle cx="12" cy="12" r="9"/><path d="M8.2 12.3l2.6 2.6 5-5.2"/>',
}


def _svg(name: str, color: str, stroke: float = 1.8) -> bytes:
    body = _P[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode()


@lru_cache(maxsize=512)
def _render(name: str, color: str, px: int, stroke: float) -> QImage:
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    return img


def pixmap(name: str, size: int = 20, color: str = "#000000", dpr: float = 2.0, stroke: float = 1.8) -> QPixmap:
    """A crisp pixmap of ``size`` logical pixels."""
    px = max(1, int(round(size * dpr)))
    pm = QPixmap.fromImage(_render(name, color, px, stroke))
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = "#000000", size: int = 20, stroke: float = 1.8) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, size, color, 2.0, stroke))
    return ic


def draw(painter: QPainter, name: str, rect: QRectF, color: str, stroke: float = 1.8) -> None:
    """Paint an icon directly into ``rect`` (used by delegates and custom widgets)."""
    dpr = painter.device().devicePixelRatioF() if painter.device() is not None else 1.0
    px = max(1, int(round(rect.width() * max(dpr, 1.0))))
    img = _render(name, color, px, stroke)
    painter.drawImage(QRectF(rect), img)


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    ic = QIcon()
    for fname in ("icon.png", "icon_1024.png"):
        f = ASSETS / fname
        if f.exists():
            ic.addFile(str(f))
    return ic


@lru_cache(maxsize=4)
def logo_pixmap(size: int = 32, dpr: float = 2.0) -> QPixmap:
    f = ASSETS / "icon.png"
    pm = QPixmap(str(f))
    if pm.isNull():
        return QPixmap()
    px = int(size * dpr)
    pm = pm.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pm.setDevicePixelRatio(dpr)
    return pm


_ = QPointF  # re-exported for type checkers
