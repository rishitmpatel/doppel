"""Group list model + delegate. One QListView paints thousands of groups without a widget per row."""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from doppel.core.models import DuplicateGroup, MatchKind

from . import icons, theme
from .state import SelectionState
from .thumbs import ThumbnailLoader
from .util import human_size, plural

GroupIndexRole = Qt.UserRole + 1
GroupRole = Qt.UserRole + 2

ROW_H = 96
THUMB = 56
MAX_THUMBS = 3


class GroupListModel(QAbstractListModel):
    def __init__(self, state: SelectionState, parent=None):
        super().__init__(parent)
        self.state = state
        self._rows: list[int] = []          # indexes into state.groups
        self._kind: MatchKind | None = None
        self._hide_reviewed = False
        self.reviewed: set[int] = set()
        state.groupsChanged.connect(self._on_groups_changed)

    # -- data ---------------------------------------------------------------
    def reload(self) -> None:
        self.beginResetModel()
        self.reviewed = set()
        self._apply_filter()
        self.endResetModel()

    def _apply_filter(self) -> None:
        self._rows = [
            i for i, g in enumerate(self.state.groups)
            if (self._kind is None or g.kind == self._kind) and not (self._hide_reviewed and i in self.reviewed)
        ]

    def set_filter(self, kind: MatchKind | None = None, hide_reviewed: bool | None = None) -> None:
        self._kind = kind
        if hide_reviewed is not None:
            self._hide_reviewed = hide_reviewed
        self.beginResetModel()
        self._apply_filter()
        self.endResetModel()

    @property
    def hide_reviewed(self) -> bool:
        return self._hide_reviewed

    def mark_reviewed(self, gi: int) -> None:
        if gi in self.reviewed:
            return
        self.reviewed.add(gi)
        r = self.row_of(gi)
        if r >= 0:
            ix = self.index(r)
            self.dataChanged.emit(ix, ix)

    def group_index(self, row: int) -> int:
        return self._rows[row]

    def row_of(self, gi: int) -> int:
        try:
            return self._rows.index(gi)
        except ValueError:
            return -1

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        gi = self._rows[index.row()]
        if role == GroupIndexRole:
            return gi
        if role == GroupRole:
            return self.state.groups[gi]
        if role == Qt.DisplayRole:
            g = self.state.groups[gi]
            return f"{len(g.photos)} photos"
        return None

    def _on_groups_changed(self, gis) -> None:
        if len(gis) > 64 or len(gis) >= len(self._rows):
            if self._rows:
                self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1))
            return
        for gi in gis:
            r = self.row_of(gi)
            if r >= 0:
                ix = self.index(r)
                self.dataChanged.emit(ix, ix)


def group_title(g: DuplicateGroup) -> str:
    n = len(g.photos)
    if g.kind == MatchKind.EXACT:
        return f"{n} exact copies"
    return f"{n} look-alikes"


class GroupDelegate(QStyledItemDelegate):
    repaintNeeded = Signal()

    def __init__(self, model: GroupListModel, state: SelectionState, loader: ThumbnailLoader, parent=None):
        super().__init__(parent)
        self.model_ = model
        self.state = state
        self.loader = loader

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width() or 300, ROW_H)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        t = theme.tokens()
        gi = index.data(GroupIndexRole)
        g: DuplicateGroup = self.state.groups[gi]
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(option.rect).adjusted(6, 3, -6, -3)
        if selected:
            p.setPen(QPen(QColor(t.accent), 1.5))
            p.setBrush(QColor(t.accent_soft))
        elif hover:
            p.setPen(QPen(QColor(t.border), 1))
            p.setBrush(QColor(t.surface))
        else:
            p.setPen(QPen(QColor(t.border), 1))
            p.setBrush(QColor(t.surface))
        p.drawRoundedRect(card, 14, 14)

        # thumbnails
        dpr = max(1.0, p.device().devicePixelRatioF())
        x = card.left() + 12
        y = card.top() + (card.height() - THUMB) / 2
        shown = g.photos[:MAX_THUMBS]
        for k, ph in enumerate(shown):
            r = QRectF(x, y, THUMB, THUMB)
            removed = self.state.is_removed(ph.path)
            self._paint_thumb(p, r, ph.path, dpr, dim=removed, extra=(len(g.photos) - MAX_THUMBS) if (k == MAX_THUMBS - 1 and len(g.photos) > MAX_THUMBS) else 0)
            x += THUMB + 6
        x = card.left() + 12 + MAX_THUMBS * (THUMB + 6) + 6

        # text
        rm = self.state.group_removed(gi)
        tr = QRectF(x, card.top() + 14, card.right() - x - 12, card.height() - 22)
        f = QFont(p.font())
        f.setPixelSize(14)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(t.text))
        fm = QFontMetrics(f)
        p.drawText(QRectF(tr.left(), tr.top(), tr.width(), fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(group_title(g), Qt.ElideRight, int(tr.width())))
        f.setBold(False)
        f.setPixelSize(13)
        p.setFont(f)
        fm = QFontMetrics(f)
        if rm:
            sub = f"Remove {len(rm)} · {human_size(self.state.group_removed_bytes(gi))}"
            col = t.danger_text
        else:
            sub = "Keeping all"
            col = t.text_muted
        p.setPen(QColor(col))
        p.drawText(QRectF(tr.left(), tr.top() + 22, tr.width(), fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(sub, Qt.ElideRight, int(tr.width())))
        # kind pill
        exact = g.kind == MatchKind.EXACT
        label = "Exact" if exact else f"{round(g.similarity * 100)}% alike"
        fg, bg = (t.accent_text, t.accent_soft) if exact else (t.warn_text, t.warn_soft)
        if selected and exact:
            bg = t.surface
        f.setPixelSize(11)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        pw = fm.horizontalAdvance(label) + 14
        pill = QRectF(tr.left(), tr.top() + 46, pw, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(pill, 9, 9)
        p.setPen(QColor(fg))
        p.drawText(pill, Qt.AlignCenter, label)

        # "not looked at yet" dot
        if gi not in self.model_.reviewed:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.accent))
            p.drawEllipse(QRectF(card.right() - 18, card.top() + 12, 7, 7))
        p.restore()

    def _paint_thumb(self, p: QPainter, r: QRectF, path, dpr: float, dim: bool, extra: int) -> None:
        t = theme.tokens()
        clip = QPainterPath()
        clip.addRoundedRect(r, 9, 9)
        p.save()
        p.setClipPath(clip)
        pm = self.loader.get(path, THUMB * dpr)
        if pm is None:
            pm = self.loader.best_available(path)
        if pm is None:
            p.fillRect(r, QColor(t.surface_alt))
            if self.loader.failed(path):
                icons.draw(p, "photo-off", r.adjusted(16, 16, -16, -16), t.text_faint, 1.8)
        else:
            sw, sh = pm.width(), pm.height()
            side = min(sw, sh)
            src = QRectF((sw - side) / 2, (sh - side) / 2, side, side)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawPixmap(r, pm, src)
        if dim:
            p.fillRect(r, theme.qcolor(t.surface, 0.70))
        if extra > 0:
            p.fillRect(r, QColor(10, 16, 22, 150))
            f = QFont(p.font())
            f.setPixelSize(15)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(r, Qt.AlignCenter, f"+{extra}")
        p.restore()
        if dim:
            # small "removing" marker in the corner
            p.save()
            p.setRenderHint(QPainter.Antialiasing)
            c = QRectF(r.right() - 17, r.top() + 3, 14, 14)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.danger))
            p.drawEllipse(c)
            icons.draw(p, "close", c.adjusted(3, 3, -3, -3), "#FFFFFF", 3.2)
            p.restore()


_ = (QPoint, QRect, plural)
