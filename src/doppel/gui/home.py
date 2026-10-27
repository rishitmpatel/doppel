"""Home screen: choose folders, choose what to look for, start the scan."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from . import icons, theme
from .util import short_path
from .widgets import CheckBox, ElidedLabel, OptionCard, make_button, make_icon_button, make_label, repolish

# (max Hamming distance on pHash, short name, explanation)
STRICTNESS = [
    (2, "Strictest", "Only photos that are practically identical. You will see the fewest matches and almost no mistakes."),
    (5, "Strict", "Photos that are clearly the same picture, such as a copy saved again or shrunk a little."),
    (8, "Balanced", "Finds resized, re-saved and lightly edited copies. A good choice for most people."),
    (12, "Loose", "Also finds photos with bigger edits or crops. Check the results, a few may just be similar."),
    (16, "Loosest", "Finds anything that looks alike, including burst shots. Review each group carefully."),
]
DEFAULT_STRICTNESS = 2


def normalize_roots(folders: list[Path], include_subfolders: bool) -> list[Path]:
    """Drop duplicates, and (when subfolders are included) folders already inside another chosen one."""
    out: list[Path] = []
    seen = set()
    for f in folders:
        try:
            r = f.resolve()
        except OSError:
            r = f
        if r in seen:
            continue
        seen.add(r)
        out.append(f)
    if not include_subfolders:
        return out
    resolved = []
    for f in out:
        try:
            resolved.append((f, f.resolve()))
        except OSError:
            resolved.append((f, f))
    keep = []
    for f, r in resolved:
        if any(o != r and o in r.parents for _, o in resolved):
            continue
        keep.append(f)
    return keep


class DropZone(QFrame):
    foldersDropped = Signal(list)
    browseRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.setAcceptDrops(True)
        self.setProperty("active", False)
        self.setMinimumHeight(150)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignCenter)
        self.glyph = QLabel()
        self.glyph.setFixedSize(52, 52)
        self.glyph.setAlignment(Qt.AlignCenter)
        self.glyph.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.title = make_label("Drag folders here", "h2")
        self.title.setAlignment(Qt.AlignCenter)
        self.sub = make_label("Camera uploads, old backups, downloads: anything you want to tidy up.", "muted", wrap=True)
        self.sub.setAlignment(Qt.AlignCenter)
        self.btn = make_button("Choose a folder", "primary", "folder-plus", theme.tokens().on_accent)
        self.btn.setProperty("compact", True)
        self.btn.clicked.connect(self.browseRequested)
        lay.addWidget(self.glyph, 0, Qt.AlignHCenter)
        lay.addSpacing(4)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addSpacing(8)
        lay.addWidget(self.btn, 0, Qt.AlignHCenter)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = theme.tokens()
        self.glyph.setStyleSheet(f"background: {t.accent_soft}; border-radius: 26px;")
        self.glyph.setPixmap(icons.pixmap("folder-plus", 26, t.accent_text, 2.0))
        self.btn.setIcon(icons.icon("folder-plus", t.on_accent, 18))

    def set_active(self, on: bool) -> None:
        self.setProperty("active", on)
        repolish(self)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.set_active(True)

    def dragMoveEvent(self, e) -> None:
        e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:
        self.set_active(False)

    def dropEvent(self, e) -> None:
        self.set_active(False)
        self.foldersDropped.emit(paths_from_mime(e.mimeData()))
        e.acceptProposedAction()


def paths_from_mime(mime) -> list[str]:
    out = []
    for u in mime.urls():
        if u.isLocalFile():
            p = Path(u.toLocalFile())
            out.append(str(p if p.is_dir() else p.parent))
    return out


class FolderRow(QFrame):
    removeClicked = Signal(object)

    def __init__(self, path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = path
        self.setObjectName("folderRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 8)
        lay.setSpacing(12)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("folder", 22, theme.tokens().accent_text, 2.0))
        ic.setFixedSize(24, 24)
        lay.addWidget(ic)
        lab = ElidedLabel(short_path(path), Qt.ElideMiddle)
        lab.setToolTip(str(path))
        lay.addWidget(lab, 1)
        self.rm = make_icon_button("close", "Remove this folder from the list", 16)
        self.rm.clicked.connect(lambda: self.removeClicked.emit(self.path))
        lay.addWidget(self.rm)


class HomePage(QWidget):
    scanRequested = Signal()
    foldersChanged = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAcceptDrops(True)
        self._folders: list[Path] = []
        self._notice_text = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        inner = QWidget()
        inner.setObjectName("scrollInner")
        scroll.setWidget(inner)
        row = QHBoxLayout(inner)
        row.setContentsMargins(24, 8, 24, 32)
        row.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(18)
        holder = QWidget()
        holder.setMaximumWidth(1060)
        holder.setMinimumWidth(820)
        holder.setLayout(col)
        row.addWidget(holder, 100)
        row.addStretch(1)

        # -- heading
        title = make_label("Find duplicate photos", "title")
        lead = make_label(
            "Pick the folders you'd like to tidy up. Doppel finds photos you have more than once, "
            "and you decide what goes. Nothing leaves your computer.", "lead", wrap=True)
        col.addSpacing(6)
        col.addWidget(title)
        col.addWidget(lead)
        col.addSpacing(4)

        # -- folders card
        card1 = QFrame()
        card1.setObjectName("card")
        c1 = QVBoxLayout(card1)
        c1.setContentsMargins(22, 20, 22, 20)
        c1.setSpacing(14)
        c1.addWidget(make_label("1. Where should we look?", "h2"))
        self.drop = DropZone()
        self.drop.foldersDropped.connect(self.add_folders)
        self.drop.browseRequested.connect(self.browse)
        c1.addWidget(self.drop)

        self.rows_scroll = QScrollArea()
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setFrameShape(QFrame.NoFrame)
        self.rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rows_host = QWidget()
        self.rows_host.setObjectName("scrollInner")
        self.rows_host.setStyleSheet("background: transparent;")
        self.rows_lay = QVBoxLayout(self.rows_host)
        self.rows_lay.setContentsMargins(0, 0, 0, 0)
        self.rows_lay.setSpacing(8)
        self.rows_scroll.setWidget(self.rows_host)
        self.rows_scroll.setStyleSheet("background: transparent;")
        self.rows_scroll.viewport().setStyleSheet("background: transparent;")
        c1.addWidget(self.rows_scroll)

        self.notice = make_label("", "hint", wrap=True)
        self.notice.hide()
        c1.addWidget(self.notice)

        self.chk_sub = CheckBox("Include photos in subfolders")
        self.chk_sub.setChecked(True)
        c1.addWidget(self.chk_sub)
        c1.addStretch(1)
        cols = QHBoxLayout()
        cols.setSpacing(18)
        cols.addWidget(card1, 1)

        # -- what to look for
        card2 = QFrame()
        card2.setObjectName("card")
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(22, 20, 22, 20)
        c2.setSpacing(12)
        c2.addWidget(make_label("2. What should we look for?", "h2"))
        self.opt_exact = OptionCard(
            "Exact copies", "The very same file saved in more than one place, even if the names are different.")
        self.opt_similar = OptionCard(
            "Look-alikes", "The same photo resized, edited, re-saved or taken twice in a row.")
        self.opt_exact.setChecked(True)
        self.opt_similar.setChecked(True)
        c2.addWidget(self.opt_exact)
        c2.addWidget(self.opt_similar)

        self.sens_box = QWidget()
        sb = QVBoxLayout(self.sens_box)
        sb.setContentsMargins(4, 8, 4, 0)
        sb.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(make_label("How alike should look-alikes be?", "h3"))
        head.addStretch(1)
        self.sens_name = make_label("Balanced", "accent")
        head.addWidget(self.sens_name)
        sb.addLayout(head)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, len(STRICTNESS) - 1)
        self.slider.setPageStep(1)
        self.slider.setMinimumHeight(30)
        self.slider.setValue(DEFAULT_STRICTNESS)
        self.slider.setTickPosition(QSlider.NoTicks)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setAccessibleName("Match strictness")
        sb.addWidget(self.slider)
        ends = QHBoxLayout()
        ends.addWidget(make_label("Strict", "faint"))
        ends.addStretch(1)
        ends.addWidget(make_label("Loose", "faint"))
        sb.addLayout(ends)
        self.sens_text = make_label("", "small", wrap=True)
        sb.addWidget(self.sens_text)
        c2.addWidget(self.sens_box)
        c2.addStretch(1)
        cols.addWidget(card2, 1)
        col.addLayout(cols)

        # -- go
        go = QHBoxLayout()
        go.setSpacing(16)
        self.scan_btn = make_button("Scan for duplicates", "primary", "search", theme.tokens().on_accent, 20)
        self.scan_btn.setMinimumHeight(50)
        self.scan_btn.setMinimumWidth(240)
        self.go_hint = make_label("", "small", wrap=True)
        go.addWidget(self.scan_btn)
        go.addWidget(self.go_hint, 1)
        col.addLayout(go)
        priv = QHBoxLayout()
        priv.setSpacing(8)
        self._priv_icon = QLabel()
        priv.addWidget(self._priv_icon, 0, Qt.AlignVCenter)
        priv.addWidget(make_label("Private by design. Doppel only reads your photos and never changes them.", "faint"), 1)
        col.addSpacing(2)
        col.addLayout(priv)
        col.addStretch(1)

        # -- wiring
        self.slider.valueChanged.connect(self._on_strictness)
        self.opt_exact.toggled.connect(self._refresh)
        self.opt_similar.toggled.connect(self._refresh)
        self.chk_sub.toggled.connect(self._refresh)
        self.scan_btn.clicked.connect(self._on_scan)
        self._on_strictness(self.slider.value())
        self._rebuild_rows()
        self._refresh()
        self.refresh_theme()

    # -- theme -------------------------------------------------------------
    def refresh_theme(self) -> None:
        t = theme.tokens()
        self._priv_icon.setPixmap(icons.pixmap("shield", 16, t.text_faint, 2.0))
        self.scan_btn.setIcon(icons.icon("search", t.on_accent, 20))
        self.drop.refresh_theme()
        self._rebuild_rows()

    # -- folders -------------------------------------------------------------
    def folders(self) -> list[Path]:
        return list(self._folders)

    def set_folders(self, folders) -> None:
        self._folders = []
        for f in folders:
            p = Path(f)
            if p.is_dir() and p not in self._folders:
                self._folders.append(p)
        self._rebuild_rows()
        self._refresh()
        self.foldersChanged.emit()

    def add_folders(self, paths) -> None:
        notes = []
        for raw in paths:
            p = Path(raw)
            if not p.is_dir():
                continue
            try:
                rp = p.resolve()
            except OSError:
                rp = p
            if any(self._same(rp, f) for f in self._folders):
                continue
            inside = next((f for f in self._folders if self._inside(rp, f)), None)
            if inside is not None and self.chk_sub.isChecked():
                notes.append(f"\"{p.name or p}\" is already included in \"{inside.name or inside}\".")
                continue
            if self.chk_sub.isChecked():
                contained = [f for f in self._folders if self._inside(f, rp)]
                for f in contained:
                    self._folders.remove(f)
                if contained:
                    notes.append(f"\"{p.name or p}\" replaces {len(contained)} folder(s) that were inside it.")
            self._folders.append(p)
        self._notice(" ".join(notes))
        self._rebuild_rows()
        self._refresh()
        self.foldersChanged.emit()

    @staticmethod
    def _same(a: Path, b: Path) -> bool:
        try:
            return a.resolve() == b.resolve()
        except OSError:
            return a == b

    @staticmethod
    def _inside(child: Path, parent: Path) -> bool:
        try:
            c, p = child.resolve(), parent.resolve()
        except OSError:
            return False
        return c != p and p in c.parents

    def remove_folder(self, path: Path) -> None:
        if path in self._folders:
            self._folders.remove(path)
        self._notice("")
        self._rebuild_rows()
        self._refresh()
        self.foldersChanged.emit()

    def browse(self) -> None:
        start = str(self._folders[-1].parent) if self._folders else str(Path.home() / "Pictures" if (Path.home() / "Pictures").exists() else Path.home())
        d = QFileDialog.getExistingDirectory(self, "Choose a folder with photos", start)
        if d:
            self.add_folders([d])

    def _notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def _rebuild_rows(self) -> None:
        while self.rows_lay.count():
            it = self.rows_lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for p in self._folders:
            r = FolderRow(p)
            r.removeClicked.connect(self.remove_folder)
            self.rows_lay.addWidget(r)
        self.rows_lay.addStretch(1)
        n = len(self._folders)
        self.rows_scroll.setVisible(n > 0)
        self.rows_scroll.setFixedHeight(min(n, 4) * 54 - 6 if n else 0)
        self.drop.title.setText("Drop more folders here" if n else "Drag folders here")
        self.drop.setMinimumHeight(110 if n else 168)
        self.drop.sub.setVisible(n == 0)
        self.drop.btn.setText(" Add another folder" if n else " Choose a folder")

    # -- options ---------------------------------------------------------------
    def _on_strictness(self, idx: int) -> None:
        _, name, text = STRICTNESS[idx]
        self.sens_name.setText(name)
        self.sens_text.setText(text)

    def similarity(self) -> int:
        return STRICTNESS[self.slider.value()][0]

    def options(self):
        from doppel.core.finder import ScanOptions

        return ScanOptions(
            roots=normalize_roots(self._folders, self.chk_sub.isChecked()),
            include_subfolders=self.chk_sub.isChecked(),
            find_exact=self.opt_exact.isChecked(),
            find_similar=self.opt_similar.isChecked(),
            similarity=self.similarity(),
        )

    def can_scan(self) -> bool:
        return bool(self._folders) and (self.opt_exact.isChecked() or self.opt_similar.isChecked())

    def _refresh(self) -> None:
        sim = self.opt_similar.isChecked()
        self.sens_box.setEnabled(sim)
        self.sens_box.setVisible(True)
        ok = self.can_scan()
        self.scan_btn.setEnabled(ok)
        if not self._folders:
            self.go_hint.setText("Add at least one folder to get started.")
        elif not (self.opt_exact.isChecked() or self.opt_similar.isChecked()):
            self.go_hint.setText("Tick at least one thing to look for.")
        else:
            n = len(self._folders)
            self.go_hint.setText(f"Ready to scan {n} folder{'s' if n != 1 else ''}. This is safe: nothing is changed or removed yet.")

    def _on_scan(self) -> None:
        if self.can_scan():
            self.scanRequested.emit()

    # -- drag and drop anywhere on the page ---------------------------------------
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.drop.set_active(True)

    def dragLeaveEvent(self, e) -> None:
        self.drop.set_active(False)

    def dropEvent(self, e) -> None:
        self.drop.set_active(False)
        self.add_folders(paths_from_mime(e.mimeData()))
        e.acceptProposedAction()

    # -- persistence -----------------------------------------------------------------
    def load_settings(self, s: QSettings) -> None:
        folders = s.value("home/folders", [], type=list) or []
        if isinstance(folders, str):
            folders = [folders]
        self.chk_sub.setChecked(s.value("home/subfolders", True, type=bool))
        self.opt_exact.setChecked(s.value("home/exact", True, type=bool))
        self.opt_similar.setChecked(s.value("home/similar", True, type=bool))
        try:
            self.slider.setValue(int(s.value("home/strictness", DEFAULT_STRICTNESS)))
        except (TypeError, ValueError):
            pass
        self.set_folders([f for f in folders if f])

    def save_settings(self, s: QSettings) -> None:
        s.setValue("home/folders", [str(f) for f in self._folders])
        s.setValue("home/subfolders", self.chk_sub.isChecked())
        s.setValue("home/exact", self.opt_exact.isChecked())
        s.setValue("home/similar", self.opt_similar.isChecked())
        s.setValue("home/strictness", self.slider.value())


_ = (QSize,)
