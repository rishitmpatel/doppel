"""Confirmation, error list and About dialogs."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)

from . import icons, theme
from .util import app_version
from .widgets import make_button, make_label


class ConfirmDialog(QDialog):
    """Plain-language confirmation before anything is moved."""

    def __init__(self, title: str, lines: list[str], confirm_text: str, parent=None, icon_name: str = "trash",
                 reassurance: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(16)
        glyph = QLabel()
        glyph.setFixedSize(52, 52)
        glyph.setAlignment(Qt.AlignCenter)
        t = theme.tokens()
        glyph.setStyleSheet(f"background: {t.accent_soft}; border-radius: 26px;")
        glyph.setPixmap(icons.pixmap(icon_name, 26, t.accent_text, 2.0))
        top.addWidget(glyph, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(8)
        col.addWidget(make_label(title, "h1", wrap=True))
        for ln in lines:
            col.addWidget(make_label(ln, "muted", wrap=True))
        top.addLayout(col, 1)
        lay.addLayout(top)
        if reassurance:
            box = QFrame()
            box.setObjectName("card")
            bl = QHBoxLayout(box)
            bl.setContentsMargins(14, 12, 14, 12)
            ic = QLabel()
            ic.setPixmap(icons.pixmap("shield", 20, t.accent_text, 2.0))
            bl.addWidget(ic, 0, Qt.AlignTop)
            bl.addWidget(make_label(reassurance, "small", wrap=True), 1)
            lay.addWidget(box)
        lay.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = make_button("Cancel")
        self.ok_btn = make_button(confirm_text, "primary")
        self.ok_btn.setDefault(True)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok_btn)
        lay.addLayout(row)
        self.ok_btn.setFocus()


class ErrorsDialog(QDialog):
    def __init__(self, errors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Files that couldn't be read")
        self.resize(640, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 20)
        lay.setSpacing(10)
        n = len(errors)
        lay.addWidget(make_label(f"{n:,} file{'s' if n != 1 else ''} couldn't be read", "h1"))
        lay.addWidget(make_label(
            "These files may be damaged, empty, or not really photos. Doppel skipped them and did not touch them.",
            "muted", wrap=True))
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setLineWrapMode(QPlainTextEdit.NoWrap)
        lines = []
        for path, reason in errors[:2000]:
            lines.append(f"{path}\n    {reason}")
        if n > 2000:
            lines.append(f"... and {n - 2000:,} more")
        box.setPlainText("\n".join(lines))
        lay.addWidget(box, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = make_button("Close", "primary")
        ok.setStyleSheet("padding: 8px 24px;")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Doppel")
        self.setMinimumWidth(480)
        t = theme.tokens()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 30, 32, 24)
        lay.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(84, 2.0))
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)
        name = make_label("Doppel", "h1")
        name.setAlignment(Qt.AlignCenter)
        lay.addWidget(name)
        ver = make_label(f"Version {app_version()}", "faint")
        ver.setAlignment(Qt.AlignCenter)
        lay.addWidget(ver)
        tag = make_label("Find and safely clean up duplicate and look-alike photos.", "muted", wrap=True)
        tag.setAlignment(Qt.AlignCenter)
        lay.addWidget(tag)
        lay.addSpacing(10)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(8)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("shield", 22, t.accent_text, 2.0))
        head.addWidget(ic)
        head.addWidget(make_label("Your privacy", "h2"))
        head.addStretch(1)
        cl.addLayout(head)
        for txt in (
            "Doppel works entirely on your computer. It never connects to the internet, and it has no accounts, "
            "tracking or ads.",
            "Your photos are only ever read, never changed. Nothing is uploaded or shared.",
            "When you remove photos, they go to your Recycle Bin or to a review folder you choose, so you can always "
            "get them back. Doppel never deletes anything permanently.",
        ):
            cl.addWidget(make_label(txt, "muted", wrap=True))
        lay.addWidget(card)
        lay.addSpacing(6)
        foot = make_label("Free and open source (MIT licence). Made by Rishit Patel.", "faint")
        foot.setAlignment(Qt.AlignCenter)
        lay.addWidget(foot)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = make_button("Close", "primary")
        ok.setStyleSheet("padding: 8px 24px;")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        row.addStretch(1)
        lay.addSpacing(6)
        lay.addLayout(row)


_ = (QPixmap, QScrollArea, QWidget)
