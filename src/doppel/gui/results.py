"""Results screen: summary, filters, group list, group detail and the removal action bar."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QListView, QMenu, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from doppel.core.actions import RemoveMode
from doppel.core.models import MatchKind
from doppel.core.selector import KeepRule

from . import icons, theme
from .cards import GroupDetail
from .models import GroupDelegate, GroupIndexRole, GroupListModel
from .state import SelectionState
from .thumbs import ThumbnailLoader
from .util import default_review_dir, fmt_duration, human_size, plural, short_path, trash_name
from .widgets import Segmented, make_button, make_label

RULES = [
    (KeepRule.BEST_QUALITY, "Keep the best quality (recommended)"),
    (KeepRule.OLDEST, "Keep the oldest"),
    (KeepRule.NEWEST, "Keep the newest"),
    (KeepRule.LARGEST_FILE, "Keep the largest file"),
    (KeepRule.SHORTEST_PATH, "Keep the one with the shortest path"),
]


class ResultsPage(QWidget):
    removeRequested = Signal()
    errorsRequested = Signal()
    previewRequested = Signal(object, object)
    compareRequested = Signal(object)

    def __init__(self, state: SelectionState, loader: ThumbnailLoader, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.state = state
        self.loader = loader
        self.result = None
        self._review_dir: Path = default_review_dir()
        self._current_gi = -1

        self.model = GroupListModel(state, self)
        self.delegate = GroupDelegate(self.model, state, loader, self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- header -------------------------------------------------------
        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(28, 4, 28, 10)
        hl.setSpacing(2)
        top = QHBoxLayout()
        self.summary = make_label("", None)
        self.summary.setTextFormat(Qt.RichText)
        self.errors_btn = make_button("", "link", "alert", theme.tokens().warn_text, 16)
        self.errors_btn.clicked.connect(self.errorsRequested)
        top.addWidget(self.summary, 1)
        top.addWidget(self.errors_btn, 0, Qt.AlignVCenter)
        hl.addLayout(top)
        self.sub = make_label("", "muted")
        hl.addWidget(self.sub)
        outer.addWidget(head)

        # ---- toolbar ------------------------------------------------------
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(28, 4, 28, 12)
        bl.setSpacing(10)
        self.filter = Segmented()
        self.filter.add("all", "All")
        self.filter.add("exact", "Exact copies")
        self.filter.add("similar", "Look-alikes")
        self.filter.currentChanged.connect(self._on_filter)
        bl.addWidget(self.filter)
        bl.addStretch(1)
        self.review_btn = make_button("Review mode", "ghost", "eye")
        self.review_btn.setCheckable(True)
        self.review_btn.setToolTip("Hide groups you've already looked at, so only the ones left to check remain.")
        self.review_btn.toggled.connect(self._on_review_mode)
        bl.addWidget(self.review_btn)
        self.recommend_btn = make_button("Select all recommended", None, "sparkle")
        self.recommend_btn.setToolTip("Go back to Doppel's suggestion in every group.")
        self.recommend_btn.clicked.connect(self._select_recommended)
        bl.addWidget(self.recommend_btn)
        self.auto_btn = QToolButton()
        self.auto_btn.setText("Auto-select")
        self.auto_btn.setToolTip("Choose which photo to keep in every group")
        self.auto_btn.setPopupMode(QToolButton.InstantPopup)
        self.auto_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.auto_btn.setCursor(Qt.PointingHandCursor)
        self.auto_menu = QMenu(self.auto_btn)
        self.rule_group = QActionGroup(self)
        self.rule_group.setExclusive(True)
        self.rule_actions: dict[KeepRule, QAction] = {}
        for rule, text in RULES:
            a = QAction(text, self.auto_menu)
            a.setCheckable(True)
            a.setChecked(rule == KeepRule.BEST_QUALITY)
            a.triggered.connect(lambda _=False, r=rule: self._apply_rule(r))
            self.rule_group.addAction(a)
            self.auto_menu.addAction(a)
            self.rule_actions[rule] = a
        self.auto_menu.addSeparator()
        self.keep_all_action = QAction("Keep everything (clear all marks)", self.auto_menu)
        self.keep_all_action.triggered.connect(self._keep_everything)
        self.auto_menu.addAction(self.keep_all_action)
        self.auto_btn.setMenu(self.auto_menu)
        bl.addWidget(self.auto_btn)
        outer.addWidget(bar)

        # ---- body -----------------------------------------------------------
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(16, 0, 4, 0)
        ll.setSpacing(0)
        self.list = QListView()
        self.list.setObjectName("groupList")
        self.list.setModel(self.model)
        self.list.setItemDelegate(self.delegate)
        self.list.setUniformItemSizes(True)
        self.list.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.list.setMouseTracking(True)
        self.list.setSelectionMode(QListView.SingleSelection)
        self.list.setEditTriggers(QListView.NoEditTriggers)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setAccessibleName("Groups of duplicate photos")
        ll.addWidget(self.list)
        left.setMinimumWidth(340)
        left.setMaximumWidth(460)
        self.detail = GroupDetail(state, loader)
        self.detail.previewRequested.connect(self.previewRequested)
        self.detail.compareRequested.connect(self.compareRequested)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([390, 800])
        outer.addWidget(self.splitter, 1)

        # ---- action bar -------------------------------------------------------
        outer.addWidget(self._build_action_bar())

        # ---- wiring --------------------------------------------------------------
        self.list.selectionModel().currentChanged.connect(self._on_current)
        state.changed.connect(self._update_action_bar)
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.setInterval(40)
        self._repaint_timer.timeout.connect(self.list.viewport().update)
        loader.loaded.connect(lambda *_: self._repaint_timer.start() if not self._repaint_timer.isActive() else None)

        for seq, fn in (
            (Qt.Key_Down, lambda: self.move_group(1)),
            (Qt.Key_Up, lambda: self.move_group(-1)),
            (Qt.Key_Right, lambda: self.detail.move_current(1)),
            (Qt.Key_Left, lambda: self.detail.move_current(-1)),
            (Qt.Key_K, self.detail.keep_current),
            (Qt.Key_R, self.detail.remove_current),
            (Qt.Key_Space, self.detail.preview_current),
            (Qt.Key_Return, self.detail.preview_current),
        ):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self.refresh_theme()
        self._update_action_bar()

    # ------------------------------------------------------------------ action bar
    def _build_action_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("actionbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(28, 14, 28, 14)
        lay.setSpacing(20)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.bar_title = make_label("", "h2")
        self.bar_sub = make_label("", "small")
        col.addWidget(self.bar_title)
        col.addWidget(self.bar_sub)
        lay.addLayout(col, 1)

        dest = QVBoxLayout()
        dest.setSpacing(4)
        drow = QHBoxLayout()
        drow.setSpacing(10)
        drow.addWidget(make_label("Send them to", "small"))
        self.dest = Segmented()
        self.dest.add("trash", trash_name(), f"Removed photos go to your {trash_name()}. You can restore them from there.")
        self.dest.add("move", "A review folder", "Removed photos are moved to a folder you choose, and can be put back with one click.")
        self.dest.currentChanged.connect(lambda _: self._update_action_bar())
        drow.addWidget(self.dest)
        dest.addLayout(drow)
        irow = QHBoxLayout()
        irow.setSpacing(6)
        self.dest_info = make_label("", "faint")
        self.change_btn = make_button("Change folder", "link")
        self.change_btn.clicked.connect(self.choose_review_dir)
        irow.addStretch(1)
        irow.addWidget(self.dest_info)
        irow.addWidget(self.change_btn)
        dest.addLayout(irow)
        lay.addLayout(dest)

        self.remove_btn = make_button("Remove photos", "primary", "trash", theme.tokens().on_accent, 18)
        self.remove_btn.setMinimumHeight(48)
        self.remove_btn.setMinimumWidth(220)
        self.remove_btn.clicked.connect(self.removeRequested)
        lay.addWidget(self.remove_btn)
        return bar

    def destination(self) -> RemoveMode:
        return RemoveMode.MOVE if self.dest.current() == "move" else RemoveMode.TRASH

    def set_destination(self, mode: RemoveMode) -> None:
        self.dest.set_current("move" if mode == RemoveMode.MOVE else "trash")

    def review_dir(self) -> Path:
        return self._review_dir

    def set_review_dir(self, p: Path) -> None:
        self._review_dir = Path(p)
        self._update_action_bar()

    def choose_review_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose where removed photos should be moved",
                                             str(self._review_dir.parent if self._review_dir.parent.exists() else Path.home()))
        if d:
            self._review_dir = Path(d) if Path(d).name.lower().startswith("doppel") else Path(d) / "Doppel Review"
            self._update_action_bar()

    def _update_action_bar(self) -> None:
        n, size = self.state.total_count, self.state.total_bytes
        move = self.destination() == RemoveMode.MOVE
        self.change_btn.setVisible(move)
        if move:
            self.dest_info.setText(f"Folder: {short_path(self._review_dir)}")
            self.dest_info.setToolTip(str(self._review_dir))
        else:
            self.dest_info.setText(f"You can restore them from the {trash_name()}.")
            self.dest_info.setToolTip("")
        if n == 0:
            self.bar_title.setText("Nothing marked for removal")
            self.bar_sub.setText("Mark photos with Remove, or let Auto-select choose for you.")
            self.remove_btn.setText("Remove photos")
            self.remove_btn.setEnabled(False)
        else:
            self.bar_title.setText(f"{plural(n, 'photo')} marked for removal")
            self.bar_sub.setText(f"Frees {human_size(size)}. At least one photo from every group always stays.")
            self.remove_btn.setText(f"Remove {plural(n, 'photo')} ({human_size(size)})")
            self.remove_btn.setEnabled(True)

    # ------------------------------------------------------------------ data
    def set_result(self, result) -> None:
        self.result = result
        self.state.set_groups(result.groups)
        self.rule_actions[KeepRule.BEST_QUALITY].setChecked(True)
        self.model.reload()
        self.review_btn.blockSignals(True)
        self.review_btn.setChecked(False)
        self.review_btn.blockSignals(False)
        self.model.set_filter(None, False)
        self.filter.blockSignals(True)
        self.filter.set_current("all")
        self.filter.blockSignals(False)
        self._update_summary()
        self._select_row(0)
        self._update_action_bar()

    def _update_summary(self) -> None:
        t = theme.tokens()
        groups = self.state.groups
        total = sum(g.reclaimable_bytes for g in groups)
        counts = self.state.counts_by_kind()
        n = len(groups)
        self.summary.setText(
            f"<span style='font-size:24px; font-weight:700; color:{t.text}'>Found {plural(n, 'group')}</span>"
            f"<span style='font-size:24px; color:{t.text_faint}'>&nbsp; · &nbsp;</span>"
            f"<span style='font-size:24px; font-weight:700; color:{t.accent_text}'>{human_size(total)} can be freed</span>")
        bits = []
        if counts[MatchKind.EXACT]:
            bits.append(plural(counts[MatchKind.EXACT], "group") + " of exact copies")
        if counts[MatchKind.SIMILAR]:
            bits.append(plural(counts[MatchKind.SIMILAR], "group") + " of look-alikes")
        r = self.result
        if r is not None and getattr(r, "scanned", 0):
            bits.append(f"checked {plural(r.scanned, 'photo')} in {fmt_duration(getattr(r, 'elapsed', 0) or 0)}")
        self.sub.setText("  ·  ".join(bits))
        self.filter.set_text("all", f"All  {n}")
        self.filter.set_text("exact", f"Exact copies  {counts[MatchKind.EXACT]}")
        self.filter.set_text("similar", f"Look-alikes  {counts[MatchKind.SIMILAR]}")
        errs = list(getattr(r, "errors", []) or [])
        self.errors_btn.setVisible(bool(errs))
        if errs:
            self.errors_btn.setText(f"{plural(len(errs), 'file')} couldn't be read")

    # ------------------------------------------------------------------ interaction
    def _on_filter(self, key: str) -> None:
        kind = {"exact": MatchKind.EXACT, "similar": MatchKind.SIMILAR}.get(key)
        self.model.set_filter(kind)
        self._select_row(0)

    def _on_review_mode(self, on: bool) -> None:
        kind = {"exact": MatchKind.EXACT, "similar": MatchKind.SIMILAR}.get(self.filter.current())
        self.model.set_filter(kind, on)
        self._select_row(0)

    def _select_row(self, row: int) -> None:
        if self.model.rowCount() == 0:
            self._current_gi = -1
            self.detail.show_group(-1)
            return
        row = max(0, min(row, self.model.rowCount() - 1))
        ix = self.model.index(row)
        self.list.selectionModel().setCurrentIndex(ix, QItemSelectionModel.ClearAndSelect)
        self.list.scrollTo(ix)
        # selection signal may not fire when the row index is unchanged after a reset
        gi = ix.data(GroupIndexRole)
        if gi != self._current_gi or self.detail.gi != gi:
            self._show(gi)

    def _on_current(self, cur, prev) -> None:
        if cur.isValid():
            self._show(cur.data(GroupIndexRole))

    def _show(self, gi: int) -> None:
        if self._current_gi >= 0 and self._current_gi != gi:
            self.model.mark_reviewed(self._current_gi)
        self._current_gi = gi
        self.detail.show_group(gi)

    def move_group(self, delta: int) -> None:
        cur = self.list.currentIndex()
        row = cur.row() if cur.isValid() else -1
        self._select_row(row + delta if row >= 0 else 0)

    def current_group_index(self) -> int:
        return self._current_gi

    def _apply_rule(self, rule: KeepRule) -> None:
        self.state.apply_rule(rule)

    def _select_recommended(self) -> None:
        self.state.reset_to_recommended()
        self.rule_actions[KeepRule.BEST_QUALITY].setChecked(True)

    def _keep_everything(self) -> None:
        self.state.keep_everything()

    # ------------------------------------------------------------------ theme / settings
    def refresh_theme(self) -> None:
        t = theme.tokens()
        self.errors_btn.setIcon(icons.icon("alert", t.warn_text, 16))
        self.review_btn.setIcon(icons.icon("eye", t.text_muted, 18))
        self.recommend_btn.setIcon(icons.icon("sparkle", t.text, 18))
        self.auto_btn.setIcon(icons.icon("wand", t.text, 18))
        self.remove_btn.setIcon(icons.icon("trash", t.on_accent, 18))
        if self.state.groups:
            self._update_summary()
        self.list.viewport().update()

    def load_settings(self, s: QSettings) -> None:
        mode = s.value("results/dest", "trash")
        self.set_destination(RemoveMode.MOVE if mode == "move" else RemoveMode.TRASH)
        d = s.value("results/review_dir", "")
        if d:
            self._review_dir = Path(str(d))
        self._update_action_bar()

    def save_settings(self, s: QSettings) -> None:
        s.setValue("results/dest", self.destination().value)
        s.setValue("results/review_dir", str(self._review_dir))
