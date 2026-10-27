"""Render the app's screens (offscreen) to docs/img/*.png in light and dark, 1280x800 @2x.

Usage:  QT_QPA_PLATFORM=offscreen python scripts/screenshots.py [--out docs/img] [--scale 2]
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "img"))
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--only", default="", help="comma separated screen names")
    args = ap.parse_args()
    os.environ["QT_SCALE_FACTOR"] = str(args.scale)

    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Doppel")

    from demo_data import build_demo
    from doppel.core.actions import ActionRecord, RemoveMode
    from doppel.core.finder import Progress
    from doppel.core.models import MatchKind
    from doppel.gui import theme
    from doppel.gui.mainwindow import MainWindow
    from doppel.gui.preview import PreviewDialog

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="doppel-demo-"))
    print("building demo photos in", work)
    import demo_data

    demo_data.INFLATE = 2.4
    result = build_demo(work)
    pics = work / "Pictures"
    only = {s for s in args.only.split(",") if s}

    settings = QSettings(str(work / "settings.ini"), QSettings.IniFormat)
    theme.install(app, theme.LIGHT)
    win = MainWindow(settings, use_cache=False)
    win.resize(1280, 800)
    win.show()

    def settle(ms: int = 150) -> None:
        for _ in range(3):
            QTest.qWait(ms)
            app.processEvents()

    def wait_thumbs(timeout: int = 8000) -> None:
        waited = 0
        while waited < timeout:
            QTest.qWait(60)
            waited += 60
            if not win.loader._pending:
                break
        settle(120)

    def save(widget, name: str, scheme: str) -> None:
        if only and name not in only:
            return
        pm = widget.grab()
        path = out / f"{name}-{scheme}.png"
        pm.save(str(path))
        print("wrote", path.relative_to(ROOT) if path.is_relative_to(ROOT) else path, f"{pm.width()}x{pm.height()}")

    for scheme_name, tokens in (("light", theme.LIGHT), ("dark", theme.DARK)):
        theme.install(app, tokens)
        win.refresh_theme()

        # 1. Home (with folders chosen)
        win.home.set_folders([pics / "Family Photos", pics / "Camera Uploads", pics / "Backup 2023"])
        win._show(win.HOME)
        settle()
        save(win, "home", scheme_name)

        # 2. Scanning
        win.scanning.begin()
        win.scanning.set_progress(Progress("Checking files", 3184, 5320, str(pics / "Family Photos" / "Summer in Lisbon" / "IMG_4021.jpg")))
        win._show(win.SCANNING)
        win.scanning.end()
        win.scanning._t0 -= 47
        win.scanning._update_elapsed()
        settle()
        save(win, "scanning", scheme_name)

        # 3. Results
        win.results.set_result(result)
        win._show(win.RESULTS)
        # pick a look-alike group with several photos so the detail pane is full
        best_row = 0
        for row in range(win.results.model.rowCount()):
            g = win.state.groups[win.results.model.group_index(row)]
            if g.kind == MatchKind.SIMILAR and len(g.photos) == 4:
                best_row = row
                break
        win.results._select_row(best_row)
        wait_thumbs()
        save(win, "results", scheme_name)
        gi = win.results.current_group_index()
        group = win.state.groups[gi]

        # 4. Preview / compare
        dlg = PreviewDialog(win.state, win.loader, gi, group.photos[0].path, compare=True, parent=win)
        dlg.resize(1280, 800)
        dlg.show()
        QTest.qWait(200)
        wait_thumbs()
        # zoom a little to show the synced zoom
        save(dlg, "preview", scheme_name)
        dlg.close()
        dlg.deleteLater()

        # 5. Success (move to review folder, undo available)
        removed = sorted(win.state.removed, key=str)
        review = Path.home() / "Pictures" / "Doppel Review"
        recs = [ActionRecord(p, review / "2026-10-27_1432" / p.name, RemoveMode.MOVE, True) for p in removed]
        win._last_mode, win._last_review_dir = RemoveMode.MOVE, review
        win.success.show_removed(recs, RemoveMode.MOVE, review, win.state.total_bytes)
        win._show(win.SUCCESS)
        settle()
        save(win, "success", scheme_name)

        # 6. Empty state
        from doppel.core.models import ScanResult

        empty = ScanResult(groups=[], errors=[], scanned=2418, elapsed=12.0)
        win.empty.show_result(empty)
        win._show(win.EMPTY)
        settle()
        save(win, "empty", scheme_name)

    win.close()
    print("done")


if __name__ == "__main__":
    main()
