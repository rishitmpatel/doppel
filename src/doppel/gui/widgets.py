"""Reusable, lightly styled widgets."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QLayout, QLayoutItem, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from . import icons, theme


# ---------------------------------------------------------------------------
# factories
def make_label(text: str = "", role: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    lab.setWordWrap(wrap)
    if selectable:
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def make_button(text: str = "", variant: str | None = None, icon: str | None = None, icon_color: str | None = None,
                icon_size: int = 18, cursor: bool = True) -> QPushButton:
    b = QPushButton((" " + text) if (icon and text) else text)
    if variant:
        b.setProperty("variant", variant)
    if icon:
        col = icon_color or theme.tokens().text
        b.setIcon(icons.icon(icon, col, icon_size))
        b.setIconSize(QSize(icon_size, icon_size))
    if cursor:
        b.setCursor(Qt.PointingHandCursor)
    return b


def make_icon_button(icon_name: str, tooltip: str = "", size: int = 20, color: str | None = None) -> QPushButton:
    b = QPushButton()
    b.setProperty("variant", "icon")
    b.setIcon(icons.icon(icon_name, color or theme.tokens().text_muted, size))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tooltip)
    b.setAccessibleName(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedSize(size + 16, size + 16)
    return b


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("sep")
    f.setFrameShape(QFrame.NoFrame)
    return f


def vline() -> QFrame:
    f = QFrame()
    f.setObjectName("vsep")
    f.setFrameShape(QFrame.NoFrame)
    return f


# ---------------------------------------------------------------------------
class ElidedLabel(QLabel):
    """Single line label that elides (middle by default) and shows the full text as a tooltip."""

    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.ElideMiddle, parent: QWidget | None = None):
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(10)
        self.set_full_text(text)

    def set_full_text(self, text: str, tooltip: str | None = None) -> None:
        self._full = text
        self.setToolTip(tooltip if tooltip is not None else text)
        self._apply()

    def full_text(self) -> str:
        return self._full

    def _apply(self) -> None:
        fm = QFontMetrics(self.font())
        w = max(10, self.width() - self.contentsMargins().left() - self.contentsMargins().right())
        super().setText(fm.elidedText(self._full, self._mode, w))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._apply()

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._apply()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(min(fm.horizontalAdvance(self._full) + 4, 600), fm.height() + 4)


# ---------------------------------------------------------------------------
class CheckBox(QCheckBox):
    """A crisp custom-painted checkbox (consistent across Windows / macOS / Linux)."""

    BOX = 20

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(self.BOX + 10 + fm.horizontalAdvance(self.text()) + 4, max(self.BOX + 8, fm.height() + 8))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _e) -> None:
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(1, (self.height() - self.BOX) / 2, self.BOX - 2, self.BOX - 2)
        on = self.isChecked()
        enabled = self.isEnabled()
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.accent if enabled else t.border_strong))
            p.drawRoundedRect(box, 6, 6)
            icons.draw(p, "check", box.adjusted(2.5, 2.5, -2.5, -2.5), t.on_accent, 2.6)
        else:
            p.setPen(QPen(QColor(t.border_strong), 1.6))
            p.setBrush(QColor(t.surface))
            p.drawRoundedRect(box, 6, 6)
        if self.hasFocus():
            p.setPen(QPen(QColor(t.accent), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(-2, -2, 2, 2), 8, 8)
        p.setPen(QColor(t.text if enabled else t.text_faint))
        p.drawText(QRect(self.BOX + 10, 0, self.width() - self.BOX - 10, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())


class _CheckDot(QWidget):
    """Round check indicator used inside OptionCard."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.on = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _e) -> None:
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1.5, 1.5, 21, 21)
        if self.on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.accent))
            p.drawEllipse(r)
            icons.draw(p, "check", r.adjusted(4.5, 4.5, -4.5, -4.5), t.on_accent, 2.8)
        else:
            p.setPen(QPen(QColor(t.border_strong), 1.8))
            p.setBrush(QColor(t.surface))
            p.drawEllipse(r)


class OptionCard(QFrame):
    """A big clickable checkbox with a title and a one-line description."""

    toggled = Signal(bool)

    def __init__(self, title: str, description: str, icon_name: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("optionCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._checked = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)
        self._dot = _CheckDot()
        lay.addWidget(self._dot, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = make_label(title, "h3")
        self.desc = make_label(description, "small", wrap=True)
        for w in (self.title, self.desc):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        col.addWidget(self.title)
        col.addWidget(self.desc)
        lay.addLayout(col, 1)
        self.setProperty("checked", False)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool) -> None:
        on = bool(on)
        if on == self._checked:
            return
        self._checked = on
        self._dot.on = on
        self._dot.update()
        self.setProperty("checked", on)
        repolish(self)
        self.toggled.emit(on)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.setChecked(not self._checked)
            return
        super().keyPressEvent(e)


# ---------------------------------------------------------------------------
class Segmented(QFrame):
    """Pill-shaped exclusive button group: All | Exact copies | Look-alikes."""

    currentChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._lay = lay
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._group.buttonToggled.connect(self._on_toggled)

    def add(self, key: str, text: str, tooltip: str = "") -> QPushButton:
        b = QPushButton(text)
        b.setProperty("segment", True)
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tooltip)
        self._group.addButton(b)
        self._buttons[key] = b
        self._lay.addWidget(b)
        if len(self._buttons) == 1:
            b.setChecked(True)
        return b

    def button(self, key: str) -> QPushButton:
        return self._buttons[key]

    def set_text(self, key: str, text: str) -> None:
        self._buttons[key].setText(text)

    def set_current(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def current(self) -> str:
        for k, b in self._buttons.items():
            if b.isChecked():
                return k
        return ""

    def _on_toggled(self, btn: QPushButton, on: bool) -> None:
        if on:
            for k, b in self._buttons.items():
                if b is btn:
                    self.currentChanged.emit(k)
                    break


# ---------------------------------------------------------------------------
class FlowLayout(QLayout):
    """Left-to-right layout that wraps to new rows (cards grid that adapts to window width)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 16):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def spacing(self) -> int:
        return self._spacing

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            sz = it.sizeHint()
            nx = x + sz.width()
            if nx > r.right() + 1 and line_h > 0:
                x = r.x()
                y += line_h + self._spacing
                nx = x + sz.width()
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x = nx + self._spacing
            line_h = max(line_h, sz.height())
        return y + line_h - rect.y() + m.bottom()


_ = (QToolButton,)
