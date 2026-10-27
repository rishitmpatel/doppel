"""Large preview dialog with zoom / pan and side-by-side comparison."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget,
)

from . import icons, theme
from .cards import photo_meta_lines
from .state import SelectionState
from .thumbs import ThumbnailLoader, bucket_for
from .util import fmt_date, reveal_in_file_manager
from .widgets import ElidedLabel, make_button, make_icon_button, make_label


class ImageView(QWidget):
    """Shows one picture fitted to the view; wheel zooms, drag pans, double-click resets."""

    viewChanged = Signal(float, float, float)   # zoom, cx, cy (user-initiated)

    MAX_ZOOM = 12.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pm: QPixmap | None = None
        self.full_size: tuple[int, int] | None = None
        self.zoom = 1.0
        self.cx = 0.5
        self.cy = 0.5
        self.loading = False
        self.failed = False
        self._drag: QPointF | None = None
        self.setMinimumSize(240, 200)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())

    def set_pixmap(self, pm: QPixmap | None) -> None:
        self.pm = pm
        self.update()

    def set_view(self, zoom: float, cx: float, cy: float) -> None:
        self.zoom, self.cx, self.cy = zoom, cx, cy
        self._clamp()
        self.update()

    def _fit_scale(self) -> float:
        if not self.pm or self.pm.isNull():
            return 1.0
        return min(self.width() / self.pm.width(), self.height() / self.pm.height())

    def _scale(self) -> float:
        return self._fit_scale() * self.zoom

    def _clamp(self) -> None:
        if not self.pm or self.pm.isNull():
            return
        s = self._scale()
        vw = self.width() / (s * self.pm.width())
        vh = self.height() / (s * self.pm.height())
        self.cx = 0.5 if vw >= 1 else min(max(self.cx, vw / 2), 1 - vw / 2)
        self.cy = 0.5 if vh >= 1 else min(max(self.cy, vh / 2), 1 - vh / 2)

    def _target(self) -> QRectF:
        s = self._scale()
        w, h = self.pm.width() * s, self.pm.height() * s
        return QRectF(self.width() / 2 - self.cx * w, self.height() / 2 - self.cy * h, w, h)

    def paintEvent(self, _e) -> None:
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t.scrim))
        p.drawRoundedRect(r, 14, 14)
        if self.pm and not self.pm.isNull():
            from PySide6.QtGui import QPainterPath
            clip = QPainterPath()
            clip.addRoundedRect(r, 14, 14)
            p.setClipPath(clip)
            self._clamp()
            p.drawPixmap(self._target(), self.pm, QRectF(self.pm.rect()))
        else:
            name = "photo-off" if self.failed else "photo"
            icons.draw(p, name, QRectF(r.center().x() - 24, r.center().y() - 24, 48, 48), "#5B6B78", 1.5)
            p.setPen(QColor("#7C8B97"))
            p.drawText(r.adjusted(0, 70, 0, 0), Qt.AlignHCenter | Qt.AlignVCenter,
                       "This photo can't be shown." if self.failed else "Loading...")

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._clamp()

    def wheelEvent(self, e) -> None:
        if not self.pm:
            return
        dy = e.angleDelta().y()
        if dy == 0:
            return
        factor = 1.0015 ** dy
        new = min(self.MAX_ZOOM, max(1.0, self.zoom * factor))
        if new == self.zoom:
            return
        # keep the point under the cursor fixed
        pos = e.position()
        s_old = self._scale()
        ix = self.cx + (pos.x() - self.width() / 2) / (s_old * self.pm.width())
        iy = self.cy + (pos.y() - self.height() / 2) / (s_old * self.pm.height())
        self.zoom = new
        s_new = self._scale()
        self.cx = ix - (pos.x() - self.width() / 2) / (s_new * self.pm.width())
        self.cy = iy - (pos.y() - self.height() / 2) / (s_new * self.pm.height())
        self._clamp()
        self.update()
        self.viewChanged.emit(self.zoom, self.cx, self.cy)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._drag = e.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None and self.pm:
            d = e.position() - self._drag
            self._drag = e.position()
            s = self._scale()
            self.cx -= d.x() / (s * self.pm.width())
            self.cy -= d.y() / (s * self.pm.height())
            self._clamp()
            self.update()
            self.viewChanged.emit(self.zoom, self.cx, self.cy)

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, e) -> None:
        self.zoom, self.cx, self.cy = 1.0, 0.5, 0.5
        self.update()
        self.viewChanged.emit(self.zoom, self.cx, self.cy)


class PreviewPane(QFrame):
    """One picture with its details and a Keep / Remove choice."""

    changed = Signal()
    viewChanged = Signal(float, float, float)

    def __init__(self, state: SelectionState, loader: ThumbnailLoader, gi: int, index: int, parent=None):
        super().__init__(parent)
        self.setObjectName("plain")
        self.state, self.loader, self.gi = state, loader, gi
        self.index = index
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.prev_btn = make_icon_button("arrow-left", "Previous photo", 18)
        self.next_btn = make_icon_button("arrow-right", "Next photo", 18)
        self.prev_btn.clicked.connect(lambda: self.cycle(-1))
        self.next_btn.clicked.connect(lambda: self.cycle(1))
        self.name = ElidedLabel("", Qt.ElideMiddle)
        self.name.setProperty("role", "h2")
        self.counter = make_label("", "faint")
        top.addWidget(self.prev_btn)
        top.addWidget(self.name, 1)
        top.addWidget(self.counter)
        top.addWidget(self.next_btn)
        lay.addLayout(top)

        self.view = ImageView()
        self.view.viewChanged.connect(self.viewChanged)
        lay.addWidget(self.view, 1)

        self.meta = make_label("", "muted")
        self.meta2 = make_label("", "small")
        self.folder = ElidedLabel("", Qt.ElideLeft)
        self.folder.setProperty("role", "faint")
        lay.addWidget(self.meta)
        lay.addWidget(self.meta2)
        lay.addWidget(self.folder)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.keep_btn = QPushButton("Keep")
        self.rem_btn = QPushButton("Remove")
        self.keep_btn.setProperty("keepbtn", "keep")
        self.rem_btn.setProperty("keepbtn", "remove")
        grp = QButtonGroup(self)
        for b in (self.keep_btn, self.rem_btn):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setMinimumWidth(110)
            grp.addButton(b)
        self.keep_btn.clicked.connect(lambda: self._set(False))
        self.rem_btn.clicked.connect(lambda: self._set(True))
        self.reveal = make_button("Show in folder", "ghost", "reveal", theme.tokens().text_muted, 16)
        self.reveal.clicked.connect(lambda: reveal_in_file_manager(self.path))
        row.addWidget(self.keep_btn)
        row.addWidget(self.rem_btn)
        row.addStretch(1)
        row.addWidget(self.reveal)
        lay.addLayout(row)

        self.set_index(index)
        loader.loaded.connect(self._on_loaded)

    @property
    def group(self):
        return self.state.groups[self.gi]

    @property
    def path(self) -> Path:
        return self.group.photos[self.index].path

    def set_index(self, i: int) -> None:
        n = len(self.group.photos)
        self.index = i % n
        ph = self.group.photos[self.index]
        self.name.set_full_text(ph.path.name)
        l1, l2 = photo_meta_lines(ph)
        self.meta.setText(l1)
        extra = ""
        if ph.camera:
            extra = f"  ·  {ph.camera}"
        self.meta2.setText(l2 + extra)
        self.folder.set_full_text(str(ph.path.parent), str(ph.path))
        self.counter.setText(f"{self.index + 1} of {n}")
        self.prev_btn.setVisible(n > 1)
        self.next_btn.setVisible(n > 1)
        self.counter.setVisible(n > 1)
        self.view.failed = False
        self.view.set_pixmap(None)
        self._load()
        self.refresh()

    def cycle(self, d: int) -> None:
        self.set_index(self.index + d)
        self.changed.emit()

    def _want_px(self) -> int:
        dpr = max(1.0, self.devicePixelRatioF())
        v = self.view
        return bucket_for(max(v.width(), v.height(), 600) * dpr * max(1.0, v.zoom))

    def _load(self) -> None:
        pm = self.loader.get(self.path, self._want_px())
        if pm is None:
            pm = self.loader.best_available(self.path)
        self.view.failed = self.loader.failed(self.path)
        self.view.set_pixmap(pm)

    def _on_loaded(self, path: str, bucket: int) -> None:
        if path == str(self.path):
            self._load()

    def _set(self, remove: bool) -> None:
        self.state.set_removed(self.path, remove)
        self.refresh()
        self.changed.emit()

    def refresh(self) -> None:
        p = self.path
        removed = self.state.is_removed(p)
        can = self.state.can_remove(p)
        self.keep_btn.setChecked(not removed)
        self.rem_btn.setChecked(removed)
        self.rem_btn.setEnabled(removed or can)
        self.rem_btn.setToolTip("" if (removed or can) else "At least one photo in every group is always kept.")


class PreviewDialog(QDialog):
    def __init__(self, state: SelectionState, loader: ThumbnailLoader, gi: int, path: Path | None = None,
                 compare: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview")
        self.setModal(True)
        self.resize(1180, 780)
        self.state, self.loader, self.gi = state, loader, gi
        n = len(state.groups[gi].photos)
        start = 0
        if path is not None:
            for i, ph in enumerate(state.groups[gi].photos):
                if ph.path == path:
                    start = i
        self._syncing = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)

        top = QHBoxLayout()
        g = state.groups[gi]
        top.addWidget(make_label("Preview", "h1"))
        top.addSpacing(10)
        top.addWidget(make_label("Scroll to zoom, drag to move, double-click to fit.", "faint"))
        top.addStretch(1)
        self.compare_btn = make_button("Compare side by side", None, "compare")
        self.compare_btn.setCheckable(True)
        self.compare_btn.setVisible(n >= 2)
        self.compare_btn.toggled.connect(self._set_compare)
        self.done_btn = make_button("Done", "primary")
        self.done_btn.setStyleSheet("padding: 8px 22px;")
        self.done_btn.clicked.connect(self.accept)
        top.addWidget(self.compare_btn)
        top.addWidget(self.done_btn)
        lay.addLayout(top)

        self.panes_lay = QHBoxLayout()
        self.panes_lay.setSpacing(18)
        lay.addLayout(self.panes_lay, 1)
        self.left = PreviewPane(state, loader, gi, start)
        self.right: PreviewPane | None = None
        self.panes_lay.addWidget(self.left, 1)
        self.left.viewChanged.connect(self._sync_from_left)

        foot = make_label("Keys:  ← → switch photo   K keep   R remove   C compare   Esc close", "faint")
        lay.addWidget(foot)

        for key, fn in (
            (Qt.Key_Left, lambda: self.left.cycle(-1)),
            (Qt.Key_Right, lambda: self.left.cycle(1)),
            (Qt.Key_Up, lambda: self.right and self.right.cycle(-1)),
            (Qt.Key_Down, lambda: self.right and self.right.cycle(1)),
            (Qt.Key_K, lambda: self.left._set(False)),
            (Qt.Key_R, lambda: self.left._set(True)),
            (Qt.Key_C, lambda: self.compare_btn.isVisible() and self.compare_btn.toggle()),
            (Qt.Key_Space, self.accept),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(fn)
        state.changed.connect(self._refresh_panes)
        if compare and n >= 2:
            self.compare_btn.setChecked(True)

    def _refresh_panes(self) -> None:
        self.left.refresh()
        if self.right:
            self.right.refresh()

    def _set_compare(self, on: bool) -> None:
        if on and self.right is None:
            n = len(self.state.groups[self.gi].photos)
            self.right = PreviewPane(self.state, self.loader, self.gi, (self.left.index + 1) % n)
            self.right.viewChanged.connect(self._sync_from_right)
            self.panes_lay.addWidget(self.right, 1)
        elif not on and self.right is not None:
            self.panes_lay.removeWidget(self.right)
            self.right.setParent(None)
            self.right.deleteLater()
            self.right = None
        self.compare_btn.setText("Single photo" if on else "Compare side by side")

    def _sync_from_left(self, z, cx, cy) -> None:
        if self.right is not None and not self._syncing:
            self._syncing = True
            self.right.view.set_view(z, cx, cy)
            self._syncing = False
        self._maybe_upgrade(self.left)

    def _sync_from_right(self, z, cx, cy) -> None:
        if not self._syncing:
            self._syncing = True
            self.left.view.set_view(z, cx, cy)
            self._syncing = False
        self._maybe_upgrade(self.right)

    def _maybe_upgrade(self, pane) -> None:
        if pane is not None:
            pane._load()
        if pane is self.left and self.right is not None:
            self.right._load()


_ = (fmt_date,)
