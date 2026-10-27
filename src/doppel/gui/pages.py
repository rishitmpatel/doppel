"""Smaller full-screen states: nothing found, and removal finished (with Undo)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from doppel.core.actions import RemoveMode

from . import icons, theme
from .util import human_size, plural, short_path, trash_name
from .widgets import make_button, make_label


def _centered_card(page: QWidget, max_w: int = 640) -> QVBoxLayout:
    outer = QVBoxLayout(page)
    outer.setContentsMargins(24, 0, 24, 40)
    outer.addStretch(2)
    card = QFrame()
    card.setObjectName("card")
    card.setMaximumWidth(max_w)
    card.setMinimumWidth(440)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(40, 36, 40, 32)
    lay.setSpacing(10)
    wrap = QHBoxLayout()
    wrap.addStretch(1)
    wrap.addWidget(card, 100)
    wrap.addStretch(1)
    outer.addLayout(wrap)
    outer.addStretch(3)
    return lay


class EmptyPage(QWidget):
    newScanRequested = Signal()
    errorsRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        lay = _centered_card(self)
        self.glyph = QLabel()
        self.glyph.setFixedSize(72, 72)
        self.glyph.setAlignment(Qt.AlignCenter)
        self.title = make_label("No duplicates found", "h1")
        self.title.setAlignment(Qt.AlignCenter)
        self.sub = make_label("", "lead", wrap=True)
        self.sub.setAlignment(Qt.AlignCenter)
        self.tip = make_label("Expecting some? Go back and move the slider toward Loose to catch more look-alikes.",
                              "small", wrap=True)
        self.tip.setAlignment(Qt.AlignCenter)
        self.errors_btn = make_button("", "link")
        self.errors_btn.clicked.connect(self.errorsRequested)
        self.again = make_button("Scan other folders", "primary")
        self.again.clicked.connect(self.newScanRequested)
        lay.addWidget(self.glyph, 0, Qt.AlignHCenter)
        lay.addSpacing(6)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addSpacing(4)
        lay.addWidget(self.tip)
        lay.addWidget(self.errors_btn, 0, Qt.AlignHCenter)
        lay.addSpacing(14)
        lay.addWidget(self.again, 0, Qt.AlignHCenter)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = theme.tokens()
        self.glyph.setStyleSheet(f"background: {t.accent_soft}; border-radius: 36px;")
        self.glyph.setPixmap(icons.pixmap("circle-check", 36, t.accent_text, 2.0, 1.7))

    def show_result(self, result) -> None:
        n = getattr(result, "scanned", 0)
        if n:
            self.sub.setText(f"Your library is tidy. Doppel looked at {plural(n, 'photo')} and found no copies or look-alikes.")
        else:
            self.sub.setText("Your library is tidy. Doppel found no copies or look-alikes.")
        errs = list(getattr(result, "errors", []) or [])
        self.errors_btn.setVisible(bool(errs))
        if errs:
            self.errors_btn.setText(f"{plural(len(errs), 'file')} couldn't be read")


class SuccessPage(QWidget):
    undoRequested = Signal()
    openReviewRequested = Signal()
    newScanRequested = Signal()
    backToResultsRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        lay = _centered_card(self, 680)
        self.glyph = QLabel()
        self.glyph.setFixedSize(72, 72)
        self.glyph.setAlignment(Qt.AlignCenter)
        self.title = make_label("", "h1", wrap=True)
        self.title.setAlignment(Qt.AlignCenter)
        self.sub = make_label("", "lead", wrap=True)
        self.sub.setAlignment(Qt.AlignCenter)
        self.note = make_label("", "small", wrap=True)
        self.note.setAlignment(Qt.AlignCenter)
        self.problems_btn = make_button("", "link")
        self.problems_btn.clicked.connect(self._toggle_problems)
        self.problems = QPlainTextEdit()
        self.problems.setReadOnly(True)
        self.problems.setMaximumHeight(130)
        self.problems.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.problems.hide()

        self.undo_btn = make_button("Undo", None, "undo")
        self.undo_btn.clicked.connect(self.undoRequested)
        self.open_btn = make_button("Open review folder", None, "folder-open")
        self.open_btn.clicked.connect(self.openReviewRequested)
        self.back_btn = make_button("Back to results", None, "arrow-left")
        self.back_btn.clicked.connect(self.backToResultsRequested)
        self.again = make_button("Done", "primary")
        self.again.setMinimumWidth(140)
        self.again.clicked.connect(self.newScanRequested)

        lay.addWidget(self.glyph, 0, Qt.AlignHCenter)
        lay.addSpacing(6)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addWidget(self.note)
        lay.addWidget(self.problems_btn, 0, Qt.AlignHCenter)
        lay.addWidget(self.problems)
        lay.addSpacing(16)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        row.addWidget(self.undo_btn)
        row.addWidget(self.open_btn)
        row.addWidget(self.back_btn)
        row.addWidget(self.again)
        row.addStretch(1)
        lay.addLayout(row)
        self._records: list = []
        self._review_dir: Path | None = None
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = theme.tokens()
        self.glyph.setStyleSheet(f"background: {t.accent}; border-radius: 36px;")
        self.glyph.setPixmap(icons.pixmap("check", 36, t.on_accent, 2.0, 2.4))
        self.undo_btn.setIcon(icons.icon("undo", t.text, 18))
        self.open_btn.setIcon(icons.icon("folder-open", t.text, 18))
        self.back_btn.setIcon(icons.icon("arrow-left", t.text, 18))

    def _toggle_problems(self) -> None:
        self.problems.setVisible(not self.problems.isVisible())

    def _fill_problems(self, bad) -> None:
        self.problems.hide()
        self.problems_btn.setVisible(bool(bad))
        if bad:
            self.problems_btn.setText(f"{plural(len(bad), 'photo')} couldn't be moved. Show details")
            self.problems.setPlainText("\n".join(f"{r.original}\n    {r.error or 'Unknown problem'}" for r in bad[:500]))

    # -- states ----------------------------------------------------------------------
    def show_removed(self, records, mode: RemoveMode, review_dir: Path | None, total_bytes: int) -> None:
        self._records = list(records)
        self._review_dir = review_dir
        ok = [r for r in records if r.ok]
        bad = [r for r in records if not r.ok]
        freed = total_bytes
        where = trash_name() if mode == RemoveMode.TRASH else "your review folder"
        self.glyph.setStyleSheet(f"background: {theme.tokens().accent}; border-radius: 36px;")
        self.glyph.setPixmap(icons.pixmap("check", 36, theme.tokens().on_accent, 2.0, 2.4))
        self.title.setText(f"Done. {plural(len(ok), 'photo')} moved to {where}.")
        sub = f"{human_size(freed)} freed." if freed else ""
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        if mode == RemoveMode.MOVE:
            self.note.setText(f"They're in {short_path(review_dir)}. Changed your mind? Press Undo to put every photo back where it was.")
        else:
            self.note.setText(f"Changed your mind? Open your {trash_name()} and choose Restore on any photo. Doppel never deletes anything for good.")
        self._fill_problems(bad)
        can_undo = mode == RemoveMode.MOVE and bool(ok)
        self.undo_btn.setVisible(can_undo)
        self.undo_btn.setEnabled(True)
        self.undo_btn.setText("Undo")
        self.open_btn.setVisible(mode == RemoveMode.MOVE and bool(ok))
        self.back_btn.setVisible(False)
        self.again.setText("Done")

    def show_undone(self, restored: int, failed) -> None:
        t = theme.tokens()
        self.glyph.setStyleSheet(f"background: {t.accent_soft}; border-radius: 36px;")
        self.glyph.setPixmap(icons.pixmap("undo", 34, t.accent_text, 2.0, 1.9))
        self.title.setText(f"Put back. {plural(restored, 'photo')} restored.")
        self.sub.setText("Everything is where it was before.")
        self.sub.setVisible(True)
        self.note.setText("You can go back to your results and choose again.")
        self._fill_problems(failed)
        self.undo_btn.setVisible(False)
        self.open_btn.setVisible(False)
        self.back_btn.setVisible(True)
        self.again.setText("Start over")

    def set_undoing(self, busy: bool) -> None:
        self.undo_btn.setEnabled(not busy)
        self.undo_btn.setText("Putting photos back..." if busy else "Undo")
