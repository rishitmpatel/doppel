"""Scanning / working screen: stage steps, progress bar, current file, Cancel."""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QProgressBar, QVBoxLayout, QWidget

from . import icons, theme
from .util import fmt_duration, plural
from .widgets import ElidedLabel, make_button, make_label

STAGES = ["Finding photos", "Checking files", "Comparing photos", "Grouping"]

STAGE_TEXT = {
    "Finding photos": "Looking through your folders",
    "Checking files": "Reading your photos",
    "Comparing photos": "Comparing photos with each other",
    "Grouping": "Putting matching photos together",
    "Done": "All done",
}


class StepDots(QWidget):
    """Four labelled steps; finished steps show a check mark, the current step is highlighted."""

    def __init__(self, labels: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.labels = labels
        self.current = 0
        self.setFixedHeight(54)
        self.setMinimumWidth(420)

    def set_current(self, i: int) -> None:
        self.current = i
        self.update()

    def paintEvent(self, _e) -> None:
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.labels)
        if n == 0:
            return
        seg = self.width() / n
        cy = 14.0
        r = 11.0
        # connectors
        for i in range(n - 1):
            x0 = seg * (i + 0.5) + r + 6
            x1 = seg * (i + 1.5) - r - 6
            p.setPen(QPen(QColor(t.accent if i < self.current else t.border_strong), 2.0, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(int(x0), int(cy), int(x1), int(cy))
        f = p.font()
        f.setPixelSize(13)
        for i, lab in enumerate(self.labels):
            cx = seg * (i + 0.5)
            rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            if i < self.current:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(t.accent))
                p.drawEllipse(rect)
                icons.draw(p, "check", rect.adjusted(5, 5, -5, -5), t.on_accent, 3.0)
            elif i == self.current:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(t.accent_soft))
                p.drawEllipse(rect.adjusted(-4, -4, 4, 4))
                p.setBrush(QColor(t.accent))
                p.drawEllipse(rect.adjusted(5, 5, -5, -5))
            else:
                p.setPen(QPen(QColor(t.border_strong), 2))
                p.setBrush(QColor(t.surface))
                p.drawEllipse(rect.adjusted(1, 1, -1, -1))
            f.setBold(i == self.current)
            p.setFont(f)
            p.setPen(QColor(t.text if i <= self.current else t.text_faint))
            p.drawText(QRectF(cx - seg / 2, cy + r + 6, seg, 20), Qt.AlignHCenter | Qt.AlignTop, lab)


class ScanningPage(QWidget):
    cancelRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self._t0 = time.monotonic()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 0, 24, 40)
        outer.addStretch(2)
        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(720)
        card.setMinimumWidth(460)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(40, 36, 40, 32)
        lay.setSpacing(10)
        self.glyph = make_label("")
        self.glyph.setFixedSize(64, 64)
        self.glyph.setAlignment(Qt.AlignCenter)
        self.title = make_label("Looking through your photos", "h1")
        self.title.setAlignment(Qt.AlignCenter)
        self.sub = make_label("This can take a few minutes for big libraries. You can keep using your computer.", "muted", wrap=True)
        self.sub.setAlignment(Qt.AlignCenter)
        self.steps = StepDots(STAGES)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.stage_lab = make_label("Finding photos", "h3")
        self.count_lab = make_label("", "muted")
        self.current_lab = ElidedLabel("", Qt.ElideMiddle)
        self.current_lab.setProperty("role", "faint")
        self.elapsed_lab = make_label("", "faint")
        self.cancel_btn = make_button("Cancel", None)
        self.cancel_btn.clicked.connect(self.cancelRequested)

        lay.addWidget(self.glyph, 0, Qt.AlignHCenter)
        lay.addSpacing(4)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addSpacing(18)
        lay.addWidget(self.steps)
        lay.addSpacing(10)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addWidget(self.stage_lab)
        row.addStretch(1)
        row.addWidget(self.count_lab)
        lay.addLayout(row)
        lay.addWidget(self.current_lab)
        lay.addSpacing(18)
        foot = QHBoxLayout()
        foot.addWidget(self.elapsed_lab)
        foot.addStretch(1)
        foot.addWidget(self.cancel_btn)
        lay.addLayout(foot)

        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(card, 100)
        wrap.addStretch(1)
        outer.addLayout(wrap)
        outer.addStretch(3)

        self._tick = QTimer(self)
        self._tick.setInterval(500)
        self._tick.timeout.connect(self._update_elapsed)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = theme.tokens()
        self.glyph.setStyleSheet(f"background: {t.accent_soft}; border-radius: 32px;")
        self.glyph.setPixmap(icons.pixmap("search", 30, t.accent_text, 2.0, 1.9))

    # -- lifecycle ---------------------------------------------------------
    def begin(self, title: str = "Looking through your photos", sub: str | None = None, steps: bool = True,
              cancellable: bool = True) -> None:
        self._t0 = time.monotonic()
        self.title.setText(title)
        if sub is not None:
            self.sub.setText(sub)
        self.steps.setVisible(steps)
        self.steps.set_current(0)
        self.bar.setRange(0, 0)
        self.stage_lab.setText(STAGE_TEXT["Finding photos"] if steps else "Working")
        self.count_lab.setText("")
        self.current_lab.set_full_text("")
        self.cancel_btn.setVisible(cancellable)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel")
        self._update_elapsed()
        self._tick.start()

    def end(self) -> None:
        self._tick.stop()

    def mark_cancelling(self) -> None:
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Stopping...")
        self.stage_lab.setText("Stopping safely")

    def _update_elapsed(self) -> None:
        self.elapsed_lab.setText(f"Time so far: {fmt_duration(time.monotonic() - self._t0)}")

    # -- progress ---------------------------------------------------------------
    def set_progress(self, p) -> None:
        """``p`` has .stage, .done, .total and optionally .current (core.finder.Progress)."""
        stage = getattr(p, "stage", "") or ""
        done = int(getattr(p, "done", 0) or 0)
        total = int(getattr(p, "total", 0) or 0)
        cur = getattr(p, "current", None)
        if not self.steps.isHidden() and stage in STAGES:
            self.steps.set_current(STAGES.index(stage))
        elif stage == "Done":
            self.steps.set_current(len(STAGES))
        if stage:
            self.stage_lab.setText(STAGE_TEXT.get(stage, stage))
        if total > 0:
            if self.bar.maximum() != 1000:
                self.bar.setRange(0, 1000)
            self.bar.setValue(min(1000, int(1000 * done / total)))
            self.count_lab.setText(f"{done:,} of {total:,}")
        else:
            self.bar.setRange(0, 0)
            self.count_lab.setText(plural(done, "photo") + " so far" if done else "")
        if cur:
            self.current_lab.set_full_text(str(cur))
        elif not total:
            self.current_lab.set_full_text("")


_ = icons
