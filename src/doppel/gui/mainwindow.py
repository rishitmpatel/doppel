"""The main window: top bar + stack of screens, and the glue between them."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget,
)

from doppel.core.actions import RemoveMode

from . import icons, theme
from .dialogs import AboutDialog, ConfirmDialog, ErrorsDialog
from .home import HomePage
from .pages import EmptyPage, SuccessPage
from .preview import PreviewDialog
from .results import ResultsPage
from .scanning import ScanningPage
from .state import SelectionState
from .thumbs import ThumbnailLoader
from .util import human_size, open_folder, plural, trash_name
from .widgets import make_button, make_icon_button, make_label
from .workers import make_remove_job, make_scan_job, make_undo_job


def _default_cache():
    """Persistent hash cache so re-scans are fast. Best effort: None if the engine can't provide one."""
    try:
        from doppel.core.cache import HashCache

        try:
            return HashCache()
        except TypeError:
            from doppel.core import cache as _c

            for name in ("default_db_path", "default_cache_path", "default_path"):
                fn = getattr(_c, name, None)
                if fn:
                    return HashCache(fn())
    except Exception:
        pass
    return None


class TopBar(QFrame):
    newScan = Signal()
    about = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("topbar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 14, 20, 10)
        lay.setSpacing(10)
        self.logo = QLabel()
        self.logo.setFixedSize(30, 30)
        self.name = make_label("Doppel", "h2")
        lay.addWidget(self.logo)
        lay.addWidget(self.name)
        lay.addStretch(1)
        self.new_btn = make_button("New scan", "ghost", "refresh")
        self.new_btn.clicked.connect(self.newScan)
        self.about_btn = make_icon_button("info", "About Doppel", 20)
        self.about_btn.clicked.connect(self.about)
        lay.addWidget(self.new_btn)
        lay.addWidget(self.about_btn)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = theme.tokens()
        self.logo.setPixmap(icons.logo_pixmap(30, 2.0))
        self.new_btn.setIcon(icons.icon("refresh", t.text_muted, 18))
        self.about_btn.setIcon(icons.icon("info", t.text_muted, 20))


class MainWindow(QMainWindow):
    # Test / automation hooks
    scanFinished = Signal(object)
    removalFinished = Signal(object)
    undoFinished = Signal(object)

    HOME, SCANNING, RESULTS, EMPTY, SUCCESS = range(5)

    def __init__(self, settings: QSettings | None = None, use_cache: bool = True):
        super().__init__()
        self.setWindowTitle("Doppel")
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(960, 640)
        self.settings = settings or QSettings(QSettings.IniFormat, QSettings.UserScope, "Doppel", "Doppel")
        self._use_cache = use_cache
        self.loader = ThumbnailLoader(self)
        self.state = SelectionState(self)
        self._job = None
        self._undo_records: list = []
        self._last_mode = RemoveMode.TRASH
        self._last_review_dir: Path | None = None
        self._busy = False
        self._jobs: list = []

        central = QWidget()
        central.setObjectName("page")
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.topbar = TopBar()
        self.topbar.newScan.connect(self.go_home)
        self.topbar.about.connect(self.show_about)
        v.addWidget(self.topbar)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.home = HomePage()
        self.scanning = ScanningPage()
        self.results = ResultsPage(self.state, self.loader)
        self.empty = EmptyPage()
        self.success = SuccessPage()
        for w in (self.home, self.scanning, self.results, self.empty, self.success):
            self.stack.addWidget(w)

        self.home.scanRequested.connect(self.start_scan)
        self.scanning.cancelRequested.connect(self.cancel_scan)
        self.results.removeRequested.connect(self.request_removal)
        self.results.errorsRequested.connect(self.show_errors)
        self.results.previewRequested.connect(self.show_preview)
        self.results.compareRequested.connect(lambda gi: self.show_preview(gi, None, compare=True))
        self.empty.newScanRequested.connect(self.go_home)
        self.empty.errorsRequested.connect(self.show_errors)
        self.success.undoRequested.connect(self.undo_last)
        self.success.openReviewRequested.connect(self._open_review)
        self.success.newScanRequested.connect(self.go_home)
        self.success.backToResultsRequested.connect(lambda: self._show(self.RESULTS))

        self.home.load_settings(self.settings)
        self.results.load_settings(self.settings)
        geo = self.settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1180, 780)
        self._show(self.HOME)

    # ------------------------------------------------------------------ navigation
    def _show(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        self.topbar.new_btn.setVisible(idx in (self.RESULTS, self.EMPTY, self.SUCCESS))
        self.topbar.about_btn.setEnabled(True)

    def go_home(self) -> None:
        if self._busy:
            return
        self._show(self.HOME)

    def current_page(self) -> int:
        return self.stack.currentIndex()

    def refresh_theme(self) -> None:
        self.topbar.refresh_theme()
        for w in (self.home, self.scanning, self.results, self.empty, self.success):
            if hasattr(w, "refresh_theme"):
                w.refresh_theme()

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def show_errors(self) -> None:
        errs = list(getattr(self.results.result, "errors", []) or [])
        if errs:
            ErrorsDialog(errs, self).exec()

    # ------------------------------------------------------------------ scanning
    def start_scan(self) -> None:
        if self._busy or not self.home.can_scan():
            return
        opts = self.home.options()
        self.home.save_settings(self.settings)
        self.settings.sync()
        self._busy = True
        self.scanning.begin()
        self._show(self.SCANNING)
        self.topbar.new_btn.setVisible(False)
        cache = _default_cache() if self._use_cache else None
        job = make_scan_job(opts, cache=cache, parent=self)
        job.progress.connect(self.scanning.set_progress)
        job.result.connect(self._on_scan_result)
        job.cancelled.connect(self._on_scan_cancelled)
        job.failed.connect(self._on_scan_failed)
        job.finished.connect(self._on_job_finished)
        self._job = job
        self._jobs.append(job)
        job.start()

    def cancel_scan(self) -> None:
        if self._job is not None and self._job.is_running():
            self.scanning.mark_cancelling()
            self._job.cancel()

    def _on_job_finished(self) -> None:
        self.scanning.end()
        self._jobs = [j for j in self._jobs if j.is_running()]

    def _on_scan_result(self, result) -> None:
        self._busy = False
        if not result.groups:
            self.empty.show_result(result)
            self.results.result = result
            self.state.set_groups([])
            self._show(self.EMPTY)
        else:
            self.results.set_result(result)
            self._show(self.RESULTS)
        self.scanFinished.emit(result)

    def _on_scan_cancelled(self) -> None:
        self._busy = False
        self._show(self.HOME)
        self.scanFinished.emit(None)

    def _on_scan_failed(self, msg: str) -> None:
        self._busy = False
        self._show(self.HOME)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Couldn't finish the scan")
        box.setText("Something went wrong while looking through your photos.")
        box.setInformativeText("Nothing was changed. You can try again, or pick different folders.")
        box.setDetailedText(msg)
        box.exec()
        self.scanFinished.emit(None)

    # ------------------------------------------------------------------ removal
    def request_removal(self, confirm: bool = True) -> None:
        if self._busy:
            return
        try:
            paths = self.state.plan()
        except ValueError as exc:
            QMessageBox.warning(self, "Can't remove these photos", str(exc))
            return
        if not paths:
            return
        mode = self.results.destination()
        review_dir = self.results.review_dir() if mode == RemoveMode.MOVE else None
        n, size = len(paths), self.state.total_bytes
        if confirm:
            if mode == RemoveMode.TRASH:
                title = f"Move {plural(n, 'photo')} to the {trash_name()}?"
                lines = [
                    f"{human_size(size)} will be freed. Doppel keeps at least one photo from every group.",
                    f"The photos are moved to your {trash_name()}. They are not deleted for good.",
                ]
                reassure = f"You can restore any of them from the {trash_name()} whenever you like."
                ok_text = f"Move to {trash_name()}"
            else:
                title = f"Move {plural(n, 'photo')} to a review folder?"
                lines = [
                    f"{human_size(size)} will be freed. Doppel keeps at least one photo from every group.",
                    f"The photos are moved to:\n{review_dir}",
                ]
                reassure = "Nothing is deleted. You can put everything back with one click right afterwards, or copy photos out of that folder any time."
                ok_text = "Move photos"
            dlg = ConfirmDialog(title, lines, ok_text, self, reassurance=reassure)
            if dlg.exec() != ConfirmDialog.Accepted:
                return
        self.perform_removal(paths, mode, review_dir)

    def perform_removal(self, paths: list[Path], mode: RemoveMode, review_dir: Path | None) -> None:
        self._busy = True
        self._last_mode = mode
        self._last_review_dir = review_dir
        self._removal_bytes = {p: self.state._size.get(p, 0) for p in paths}
        self.scanning.begin("Moving your photos", "Please wait a moment. Nothing is deleted for good.",
                            steps=False, cancellable=False)
        self._show(self.SCANNING)
        job = make_remove_job(paths, mode, review_dir, parent=self)
        job.progress.connect(self.scanning.set_progress)
        job.result.connect(self._on_removed)
        job.failed.connect(self._on_remove_failed)
        job.finished.connect(self._on_job_finished)
        self._job = job
        self._jobs.append(job)
        job.start()

    def _on_removed(self, records) -> None:
        self._busy = False
        records = list(records)
        self._undo_records = [r for r in records if r.ok]
        freed = sum(self._removal_bytes.get(Path(r.original), 0) for r in records if r.ok)
        self.success.show_removed(records, self._last_mode, self._last_review_dir, freed)
        self._show(self.SUCCESS)
        self.removalFinished.emit(records)

    def _on_remove_failed(self, msg: str) -> None:
        self._busy = False
        self._show(self.RESULTS)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Couldn't move the photos")
        box.setText("Something went wrong, so Doppel stopped.")
        box.setInformativeText("Some photos may already have been moved. Nothing was deleted for good.")
        box.setDetailedText(msg)
        box.exec()
        self.removalFinished.emit(None)

    def undo_last(self) -> None:
        if self._busy or not self._undo_records:
            return
        self._busy = True
        self.success.set_undoing(True)
        job = make_undo_job(self._undo_records, parent=self)
        job.result.connect(self._on_undone)
        job.failed.connect(self._on_undo_failed)
        job.finished.connect(self._on_job_finished)
        self._job = job
        self._jobs.append(job)
        job.start()

    def _on_undone(self, records) -> None:
        self._busy = False
        records = list(records)
        ok = [r for r in records if r.ok]
        bad = [r for r in records if not r.ok]
        self._undo_records = []
        self.success.set_undoing(False)
        self.success.show_undone(len(ok), bad)
        self.undoFinished.emit(records)

    def _on_undo_failed(self, msg: str) -> None:
        self._busy = False
        self.success.set_undoing(False)
        QMessageBox.warning(self, "Couldn't put the photos back", msg)
        self.undoFinished.emit(None)

    def _open_review(self) -> None:
        d = self._last_review_dir
        if d is not None:
            Path(d).mkdir(parents=True, exist_ok=True)
            open_folder(d)

    # ------------------------------------------------------------------ preview
    def show_preview(self, gi: int, path: Path | None, compare: bool = False) -> None:
        dlg = PreviewDialog(self.state, self.loader, gi, path, compare=compare, parent=self)
        dlg.exec()

    # ------------------------------------------------------------------ lifecycle
    def closeEvent(self, e) -> None:
        for j in self._jobs:
            if j.is_running():
                j.cancel()
                j.wait(4000)
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.home.save_settings(self.settings)
        self.results.save_settings(self.settings)
        self.settings.sync()
        self.loader.shutdown()
        super().closeEvent(e)
