"""Design tokens, palette and the single application stylesheet.

Everything visual flows from the ``Tokens`` below. Custom-painted widgets call
``tokens()`` at paint time so that they follow a live light/dark switch.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Tokens:
    name: str
    bg: str            # window background
    surface: str       # cards
    surface_alt: str   # subtle fills, hovered rows
    surface_sunken: str  # inputs, drop zones
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_faint: str
    accent: str
    accent_hover: str
    accent_press: str
    accent_soft: str   # tinted backgrounds
    accent_text: str   # accent when used as text on bg/surface
    on_accent: str
    danger: str
    danger_hover: str
    danger_soft: str
    danger_text: str
    warn: str
    warn_soft: str
    warn_text: str
    shadow: str        # rgba for subtle overlays
    scrim: str         # overlay behind a preview


LIGHT = Tokens(
    name="light",
    bg="#F5F7F9", surface="#FFFFFF", surface_alt="#EEF1F4", surface_sunken="#F1F4F7",
    border="#E2E7EC", border_strong="#CBD3DB",
    text="#14202B", text_muted="#55636F", text_faint="#8593A0",
    accent="#0B8A7E", accent_hover="#09786E", accent_press="#076960",
    accent_soft="#E1F4F1", accent_text="#0A766C", on_accent="#FFFFFF",
    danger="#D14343", danger_hover="#B93636", danger_soft="#FCE9E9", danger_text="#B42F2F",
    warn="#B7791F", warn_soft="#FCF1DA", warn_text="#8A5A0E",
    shadow="rgba(20,32,43,0.10)", scrim="#0E151B",
)

DARK = Tokens(
    name="dark",
    bg="#12171C", surface="#1A2128", surface_alt="#232C35", surface_sunken="#151B21",
    border="#2A343E", border_strong="#3B4854",
    text="#EAF0F4", text_muted="#A3B1BD", text_faint="#74838F",
    accent="#2BB8A8", accent_hover="#3CC7B7", accent_press="#22A596",
    accent_soft="#123A37", accent_text="#4FD3C4", on_accent="#04211D",
    danger="#E5675F", danger_hover="#EE7C75", danger_soft="#3E1F20", danger_text="#F28B85",
    warn="#E0A030", warn_soft="#3A2E12", warn_text="#EFC060",
    shadow="rgba(0,0,0,0.40)", scrim="#07090B",
)

_current: Tokens = LIGHT
FONT_FAMILIES = [
    "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue",
    "Inter", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans",
]


def tokens() -> Tokens:
    return _current


def is_dark() -> bool:
    return _current.name == "dark"


def qcolor(value: str, alpha: float | None = None) -> QColor:
    c = QColor(value)
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def detect_scheme() -> Tokens:
    app = QGuiApplication.instance()
    if app is not None:
        try:
            scheme = app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return DARK
        except Exception:
            pass
    return LIGHT


def build_palette(t: Tokens) -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, QColor(t.bg))
    p.setColor(QPalette.WindowText, QColor(t.text))
    p.setColor(QPalette.Base, QColor(t.surface))
    p.setColor(QPalette.AlternateBase, QColor(t.surface_alt))
    p.setColor(QPalette.Text, QColor(t.text))
    p.setColor(QPalette.Button, QColor(t.surface))
    p.setColor(QPalette.ButtonText, QColor(t.text))
    p.setColor(QPalette.ToolTipBase, QColor(t.surface))
    p.setColor(QPalette.ToolTipText, QColor(t.text))
    p.setColor(QPalette.PlaceholderText, QColor(t.text_faint))
    p.setColor(QPalette.Highlight, QColor(t.accent))
    p.setColor(QPalette.HighlightedText, QColor(t.on_accent))
    p.setColor(QPalette.Link, QColor(t.accent_text))
    p.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    dis = QColor(t.text_faint)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, dis)
    return p


def build_stylesheet(t: Tokens) -> str:
    """One stylesheet for the whole app, generated from the tokens."""
    return f"""
* {{ font-size: 14px; outline: none; }}
QWidget {{ color: {t.text}; }}
QMainWindow, QDialog, QStackedWidget, QWidget#page, QWidget#scrollInner {{ background: {t.bg}; }}
QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong};
           padding: 6px 8px; border-radius: 8px; }}

QLabel {{ background: transparent; }}
QLabel[role="title"]    {{ font-size: 32px; font-weight: 700; }}
QLabel[role="h1"]       {{ font-size: 24px; font-weight: 700; }}
QLabel[role="h2"]       {{ font-size: 17px; font-weight: 650; }}
QLabel[role="h3"]       {{ font-size: 14px; font-weight: 650; }}
QLabel[role="lead"]     {{ font-size: 16px; color: {t.text_muted}; }}
QLabel[role="muted"]    {{ color: {t.text_muted}; }}
QLabel[role="faint"]    {{ color: {t.text_faint}; font-size: 13px; }}
QLabel[role="small"]    {{ color: {t.text_muted}; font-size: 13px; }}
QLabel[role="accent"]   {{ color: {t.accent_text}; font-weight: 650; }}
QLabel[role="danger"]   {{ color: {t.danger_text}; }}
QLabel[role="hint"]     {{ color: {t.warn_text}; font-size: 13px; }}

QFrame#card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 16px; }}
QFrame#plain {{ background: transparent; border: none; }}
QFrame#topbar {{ background: {t.bg}; border: none; }}
QFrame#actionbar {{ background: {t.surface}; border: none; border-top: 1px solid {t.border}; }}
QFrame#sep {{ background: {t.border}; border: none; max-height: 1px; min-height: 1px; }}
QFrame#vsep {{ background: {t.border}; border: none; max-width: 1px; min-width: 1px; }}
QFrame#panel {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 16px; }}

QFrame#dropzone {{ background: {t.surface_sunken}; border: 2px dashed {t.border_strong}; border-radius: 16px; }}
QFrame#dropzone[active="true"] {{ background: {t.accent_soft}; border: 2px dashed {t.accent}; }}

QFrame#optionCard {{ background: {t.surface}; border: 1px solid {t.border_strong}; border-radius: 14px; }}
QFrame#optionCard:hover {{ border-color: {t.text_faint}; }}
QFrame#optionCard[checked="true"] {{ background: {t.accent_soft}; border: 1px solid {t.accent}; }}
QFrame#optionCard:focus {{ border: 2px solid {t.accent}; }}

QFrame#folderRow {{ background: {t.surface_sunken}; border: 1px solid {t.border}; border-radius: 12px; }}

/* Buttons -------------------------------------------------------------- */
QPushButton, QToolButton {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong};
    border-radius: 10px; padding: 8px 16px; font-weight: 600;
}}
QPushButton:hover, QToolButton:hover {{ background: {t.surface_alt}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {t.border}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {t.text_faint}; background: {t.surface_alt}; border-color: {t.border}; }}
QPushButton:focus, QToolButton:focus {{ border: 2px solid {t.accent}; padding: 7px 15px; }}

QPushButton[variant="primary"] {{
    background: {t.accent}; color: {t.on_accent}; border: 1px solid {t.accent}; padding: 12px 28px;
    font-size: 15px; font-weight: 650; border-radius: 12px;
}}
QPushButton[variant="primary"]:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {t.accent_press}; border-color: {t.accent_press}; }}
QPushButton[variant="primary"]:disabled {{ background: {t.surface_alt}; color: {t.text_faint}; border-color: {t.border}; }}
QPushButton[variant="primary"]:focus {{ border: 2px solid {t.text}; padding: 11px 27px; }}

QPushButton[variant="danger"] {{
    background: {t.danger}; color: #FFFFFF; border: 1px solid {t.danger}; padding: 12px 28px;
    font-size: 15px; font-weight: 650; border-radius: 12px;
}}
QPushButton[variant="danger"]:hover {{ background: {t.danger_hover}; }}

QPushButton[variant="ghost"], QToolButton[variant="ghost"] {{
    background: transparent; border: 1px solid transparent; color: {t.text_muted}; padding: 8px 12px;
}}
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover {{ background: {t.surface_alt}; color: {t.text}; }}

QPushButton[variant="link"], QToolButton[variant="link"] {{
    background: transparent; border: none; color: {t.accent_text}; padding: 2px 4px; font-weight: 600;
}}
QPushButton[variant="link"]:hover, QToolButton[variant="link"]:hover {{ color: {t.accent_hover}; text-decoration: underline; background: transparent; }}

QPushButton[variant="icon"], QToolButton[variant="icon"] {{
    background: transparent; border: none; padding: 6px; border-radius: 8px;
}}
QPushButton[variant="icon"]:hover, QToolButton[variant="icon"]:hover {{ background: {t.surface_alt}; }}

QToolButton::menu-indicator {{ image: none; width: 0; }}

/* Segmented controls -------------------------------------------------- */
QFrame#segmented {{ background: {t.surface_alt}; border: 1px solid {t.border}; border-radius: 12px; }}
QPushButton[segment="true"] {{
    background: transparent; border: 1px solid transparent; color: {t.text_muted};
    padding: 7px 14px; border-radius: 9px; font-weight: 600;
}}
QPushButton[segment="true"]:hover {{ color: {t.text}; background: transparent; }}
QPushButton[segment="true"]:checked {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong}; }}
QPushButton[segment="true"]:focus {{ border: 1px solid {t.accent}; padding: 7px 14px; }}

QPushButton[keepbtn="keep"]:checked {{ background: {t.accent}; color: {t.on_accent}; border: 1px solid {t.accent}; }}
QPushButton[keepbtn="remove"]:checked {{ background: {t.danger}; color: #FFFFFF; border: 1px solid {t.danger}; }}
QPushButton[keepbtn] {{ padding: 6px 10px; border-radius: 8px; font-size: 13px; }}
QPushButton[keepbtn]:disabled {{ color: {t.text_faint}; }}

/* Card of a single photo ---------------------------------------------- */
QFrame#photoCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 16px; }}
QFrame#photoCard[state="remove"] {{ border: 1px solid {t.danger}; background: {t.surface}; }}
QFrame#photoCard[current="true"] {{ border: 2px solid {t.accent}; }}
QFrame#photoCard[current="true"][state="remove"] {{ border: 2px solid {t.danger}; }}

/* Inputs --------------------------------------------------------------- */
QSlider::groove:horizontal {{ height: 6px; background: {t.border_strong}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {t.surface}; border: 2px solid {t.accent}; width: 18px; height: 18px;
                             margin: -9px 0; border-radius: 11px; }}
QSlider::handle:horizontal:hover {{ background: {t.accent_soft}; }}
QSlider:disabled::sub-page:horizontal {{ background: {t.border_strong}; }}
QSlider::handle:horizontal:disabled {{ border-color: {t.border_strong}; }}

QProgressBar {{ background: {t.surface_alt}; border: none; border-radius: 5px; max-height: 10px; min-height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 5px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.border_strong}; min-height: 36px; border-radius: 4px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {t.text_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t.border_strong}; min-width: 36px; border-radius: 4px; margin: 2px 0; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QListView {{ background: transparent; border: none; }}
QListView#groupList {{ background: transparent; }}

QPlainTextEdit, QTextBrowser {{ background: {t.surface_sunken}; border: 1px solid {t.border}; border-radius: 10px; padding: 8px; }}

QSplitter::handle {{ background: transparent; }}

QMenu {{ background: {t.surface}; border: 1px solid {t.border_strong}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 8px 28px 8px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 6px 8px; }}

QDialog {{ background: {t.bg}; }}
QToolTip {{ font-size: 13px; }}
"""


def install(app: QApplication | None = None, scheme: Tokens | None = None) -> Tokens:
    """Apply Fusion + palette + stylesheet. Safe to call repeatedly."""
    global _current
    app = app or QApplication.instance()
    t = scheme or detect_scheme()
    _current = t
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPixelSize(14)
    app.setFont(font)
    app.setPalette(build_palette(t))
    app.setStyleSheet(build_stylesheet(t))
    return t


def follow_system(app: QApplication, on_change=None) -> None:
    """Re-theme when the OS switches between light and dark."""
    def _changed(*_):
        install(app)
        if on_change:
            on_change()
    try:
        app.styleHints().colorSchemeChanged.connect(_changed)
    except Exception:
        pass


# Make sure every token is a valid colour (caught by tests).
def validate(t: Tokens) -> list[str]:
    bad = []
    for f in fields(t):
        v = getattr(t, f.name)
        if f.name in ("name", "shadow"):
            continue
        if not QColor(v).isValid():
            bad.append(f.name)
    return bad
