"""Photo cards and the group detail pane (right side of the results screen)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from doppel.core.models import DuplicateGroup, MatchKind, PhotoInfo

from . import icons, theme
from .state import SelectionState
from .thumbs import ThumbnailLoader
from .util import fmt_date, fmt_mtime, human_size, plural, reveal_in_file_manager
from .widgets import ElidedLabel, FlowLayout, make_button, make_icon_button, make_label, repolish

CARD_W = 252
THUMB_W = CARD_W - 24
THUMB_H = 176


def photo_meta_lines(ph: PhotoInfo) -> tuple[str, str]:
    res = f"{ph.width:,} × {ph.height:,}" if ph.width and ph.height else "Unknown size"
    line1 = f"{res}  ·  {human_size(ph.size)}"
    if ph.taken:
        line2 = f"Taken {fmt_date(ph.taken)}"
    else:
        line2 = f"Modified {fmt_mtime(ph.mtime)}"
    return line1, line2


class ThumbView(QWidget):
    """The photo preview inside a card: fits the whole picture, shows badges, dims when removing."""

    clicked = Signal()

    def __init__(self, loader: ThumbnailLoader, path: Path, w: int = THUMB_W, h: int = THUMB_H, parent=None):
        super().__init__(parent)
        self.loader = loader
        self.path = path
        self.setFixedSize(w, h)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.badge: str = ""
        self.removed = False
        self._hover = False
        self.setToolTip("Click to see it bigger")

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _e) -> None:
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, 11, 11)
        p.setClipPath(clip)
        p.fillRect(r, QColor(t.surface_sunken if t.name == "light" else "#0E1317"))
        dpr = max(1.0, self.devicePixelRatioF())
        pm = self.loader.get(self.path, max(self.width(), self.height()) * dpr)
        if pm is None:
            pm = self.loader.best_available(self.path)
        if pm is None:
            if self.loader.failed(self.path):
                icons.draw(p, "photo-off", QRectF(r.center().x() - 18, r.center().y() - 18, 36, 36), t.text_faint, 1.6)
            else:
                icons.draw(p, "photo", QRectF(r.center().x() - 18, r.center().y() - 18, 36, 36), t.border_strong, 1.6)
        else:
            s = min(r.width() / pm.width(), r.height() / pm.height())
            w, h = pm.width() * s, pm.height() * s
            p.drawPixmap(QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h), pm, QRectF(pm.rect()))
        if self.removed:
            p.fillRect(r, theme.qcolor(t.surface, 0.55))
        p.setClipping(False)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(p.font())
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        if self.badge:
            label = self.badge
            pw = fm.horizontalAdvance(label) + 30
            pill = QRectF(8, 8, pw, 24)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.accent))
            p.drawRoundedRect(pill, 12, 12)
            icons.draw(p, "star", QRectF(pill.left() + 8, pill.top() + 6, 12, 12), t.on_accent, 2.4)
            p.setPen(QColor(t.on_accent))
            p.drawText(QRectF(pill.left() + 22, pill.top(), pill.width() - 22, pill.height()), Qt.AlignVCenter | Qt.AlignLeft, label)
        if self.removed:
            label = "Will be removed"
            pw = fm.horizontalAdvance(label) + 24
            pill = QRectF((r.width() - pw) / 2, r.height() - 34, pw, 24)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.danger))
            p.drawRoundedRect(pill, 12, 12)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(pill, Qt.AlignCenter, label)
        if self._hover:
            c = QRectF(r.right() - 38, 8, 30, 30)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawEllipse(c)
            icons.draw(p, "expand", c.adjusted(7, 7, -7, -7), "#FFFFFF", 2.0)


class PhotoCard(QFrame):
    previewRequested = Signal(object)   # Path
    focusRequested = Signal(object)     # Path

    def __init__(self, ph: PhotoInfo, group_index: int, state: SelectionState, loader: ThumbnailLoader, parent=None):
        super().__init__(parent)
        self.ph = ph
        self.gi = group_index
        self.state = state
        self.setObjectName("photoCard")
        self.setFixedWidth(CARD_W)
        self.setProperty("state", "keep")
        self.setProperty("current", False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(4)
        self.thumb = ThumbView(loader, ph.path)
        self.thumb.clicked.connect(lambda: self.previewRequested.emit(self.ph.path))
        lay.addWidget(self.thumb)
        lay.addSpacing(6)
        self.name = ElidedLabel(ph.path.name, Qt.ElideMiddle)
        self.name.setProperty("role", "h3")
        lay.addWidget(self.name)
        l1, l2 = photo_meta_lines(ph)
        self.meta1 = make_label(l1, "muted")
        self.meta2 = make_label(l2, "small")
        lay.addWidget(self.meta1)
        lay.addWidget(self.meta2)
        self.folder = ElidedLabel(str(ph.path.parent), Qt.ElideLeft)
        self.folder.setProperty("role", "faint")
        self.folder.setToolTip(str(ph.path))
        lay.addWidget(self.folder)
        lay.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.keep_btn = QPushButton("Keep")
        self.rem_btn = QPushButton("Remove")
        self.keep_btn.setProperty("keepbtn", "keep")
        self.rem_btn.setProperty("keepbtn", "remove")
        for b in (self.keep_btn, self.rem_btn):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(self.keep_btn)
        grp.addButton(self.rem_btn)
        self.keep_btn.clicked.connect(lambda: self._set(False))
        self.rem_btn.clicked.connect(lambda: self._set(True))
        row.addWidget(self.keep_btn, 1)
        row.addWidget(self.rem_btn, 1)
        self.reveal_btn = make_icon_button("reveal", "Show this file in its folder", 18, theme.tokens().text_muted)
        self.reveal_btn.setFixedSize(34, 34)
        self.reveal_btn.clicked.connect(lambda: reveal_in_file_manager(self.ph.path))
        row.addWidget(self.reveal_btn)
        lay.addLayout(row)
        self.refresh()

    def mousePressEvent(self, e) -> None:
        self.focusRequested.emit(self.ph.path)
        super().mousePressEvent(e)

    def _set(self, remove: bool) -> None:
        self.focusRequested.emit(self.ph.path)
        ok = self.state.set_removed(self.ph.path, remove)
        if not ok:
            self.refresh()

    def set_badge(self, text: str) -> None:
        self.thumb.badge = text
        self.thumb.update()

    def set_current(self, on: bool) -> None:
        if bool(self.property("current")) != on:
            self.setProperty("current", on)
            repolish(self)

    def refresh(self) -> None:
        removed = self.state.is_removed(self.ph.path)
        can_remove = self.state.can_remove(self.ph.path)
        self.keep_btn.setChecked(not removed)
        self.rem_btn.setChecked(removed)
        # The only photo left to keep in its group can't be switched to Remove.
        self.rem_btn.setEnabled(removed or can_remove)
        self.rem_btn.setToolTip("" if (removed or can_remove) else "At least one photo in every group is always kept.")
        self.thumb.removed = removed
        self.thumb.update()
        st = "remove" if removed else "keep"
        if self.property("state") != st:
            self.setProperty("state", st)
            repolish(self)


class GroupDetail(QWidget):
    previewRequested = Signal(object, object)   # group index, Path
    compareRequested = Signal(object)

    def __init__(self, state: SelectionState, loader: ThumbnailLoader, parent=None):
        super().__init__(parent)
        self.state = state
        self.loader = loader
        self.gi = -1
        self.cards: list[PhotoCard] = []
        self._current = 0
        self.setObjectName("page")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 24, 0)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        self.title = make_label("", "h1")
        self.subtitle = make_label("", "muted", wrap=True)
        tcol.addWidget(self.title)
        tcol.addWidget(self.subtitle)
        head.addLayout(tcol, 1)
        self.keep_all_btn = make_button("Keep all", "ghost")
        self.keep_all_btn.setToolTip("Keep every photo in this group")
        self.keep_all_btn.clicked.connect(self._keep_all)
        self.compare_btn = make_button("Compare side by side", None, "compare")
        self.compare_btn.clicked.connect(lambda: self.compareRequested.emit(self.gi))
        head.addWidget(self.keep_all_btn, 0, Qt.AlignTop)
        head.addWidget(self.compare_btn, 0, Qt.AlignTop)
        lay.addLayout(head)

        self.status = make_label("", "small")
        lay.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.host.setObjectName("scrollInner")
        self.flow = FlowLayout(self.host, spacing=16)
        self.flow.setContentsMargins(2, 6, 2, 12)
        self.scroll.setWidget(self.host)
        lay.addWidget(self.scroll, 1)

        self.hint = make_label("", "hint")
        self.hint.setVisible(False)
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(3500)
        self._hint_timer.timeout.connect(lambda: self.hint.setVisible(False))
        lay.addWidget(self.hint)

        state.groupsChanged.connect(self._on_state_changed)
        state.refused.connect(self._on_refused)

    # -- showing a group --------------------------------------------------------
    def show_group(self, gi: int) -> None:
        self.gi = gi
        for c in self.cards:
            c.setParent(None)
            c.deleteLater()
        self.cards = []
        while self.flow.count():
            self.flow.takeAt(0)
        if gi < 0 or gi >= len(self.state.groups):
            self.title.setText("")
            self.subtitle.setText("")
            self.status.setText("")
            return
        g = self.state.groups[gi]
        n = len(g.photos)
        if g.kind == MatchKind.EXACT:
            self.title.setText(f"{n} exact copies")
            self.subtitle.setText("These files are identical, byte for byte. Keep one and the rest can go.")
        else:
            self.title.setText(f"{n} look-alikes")
            self.subtitle.setText(f"These photos are {round(g.similarity * 100)}% alike. Compare them and keep the one you like best.")
        for ph in g.photos:
            c = PhotoCard(ph, gi, self.state, self.loader)
            c.previewRequested.connect(lambda path, gi=gi: self.previewRequested.emit(gi, path))
            c.focusRequested.connect(self._focus_path)
            self.cards.append(c)
            self.flow.addWidget(c)
        self.compare_btn.setVisible(n >= 2)
        self._current = 0
        self._update_badges()
        self._update_status()
        self._mark_current()
        self.scroll.verticalScrollBar().setValue(0)
        self.host.updateGeometry()

    def _update_badges(self) -> None:
        label = "Best" if (self.gi >= 0 and self.state.groups[self.gi].kind == MatchKind.SIMILAR) else "Suggested"
        for c in self.cards:
            c.set_badge(label if self.state.is_suggested(self.gi, c.ph.path) else "")

    def _update_status(self) -> None:
        if self.gi < 0:
            return
        n = len(self.cards)
        kept = len(self.state.group_kept(self.gi))
        rem = n - kept
        txt = f"Keeping {kept} of {n}"
        if rem:
            txt += f"  ·  {plural(rem, 'photo')} will be removed ({human_size(self.state.group_removed_bytes(self.gi))})"
        self.status.setText(txt)

    def _on_state_changed(self, gis) -> None:
        if self.gi < 0:
            return
        # A change elsewhere can affect a card here if the file lives in several groups.
        for c in self.cards:
            c.refresh()
        self._update_badges()
        self._update_status()

    def _on_refused(self, path) -> None:
        if any(c.ph.path == path for c in self.cards):
            self.show_hint("Doppel always keeps at least one photo from every group, so this one has to stay.")

    def show_hint(self, text: str) -> None:
        self.hint.setText(text)
        self.hint.setVisible(True)
        self._hint_timer.start()

    def _keep_all(self) -> None:
        for c in self.cards:
            self.state.set_removed(c.ph.path, False)

    # -- focus + keyboard -----------------------------------------------------------
    def _focus_path(self, path) -> None:
        for i, c in enumerate(self.cards):
            if c.ph.path == path:
                self._current = i
        self._mark_current()

    def _mark_current(self) -> None:
        for i, c in enumerate(self.cards):
            c.set_current(i == self._current)

    def move_current(self, delta: int) -> None:
        if not self.cards:
            return
        self._current = max(0, min(len(self.cards) - 1, self._current + delta))
        self._mark_current()
        self.scroll.ensureWidgetVisible(self.cards[self._current], 20, 20)

    def current_path(self) -> Path | None:
        if not self.cards:
            return None
        return self.cards[self._current].ph.path

    def keep_current(self) -> None:
        p = self.current_path()
        if p is not None:
            self.state.set_removed(p, False)

    def remove_current(self) -> None:
        p = self.current_path()
        if p is not None:
            self.state.set_removed(p, True)

    def preview_current(self) -> None:
        p = self.current_path()
        if p is not None and self.gi >= 0:
            self.previewRequested.emit(self.gi, p)


_ = (QPointF, QPen, QSize, QSizePolicy, DuplicateGroup)
