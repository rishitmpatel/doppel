"""Application entry point: ``doppel`` (gui-script) and ``python -m doppel``."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    argv = list(sys.argv if argv is None else argv)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("Doppel")
    app.setOrganizationName("Doppel")
    app.setDesktopFileName("doppel")

    if sys.platform.startswith("win"):  # own taskbar identity + icon instead of python.exe's
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Doppel.DuplicatePhotoFinder")
        except Exception:
            pass

    from doppel.gui import icons, theme
    from doppel.gui.mainwindow import MainWindow

    app.setWindowIcon(icons.app_icon())
    theme.install(app)
    win = MainWindow()
    theme.follow_system(app, on_change=win.refresh_theme)

    # Folders passed on the command line pre-fill the home screen.
    extra = [a for a in argv[1:] if not a.startswith("-")]
    if extra:
        win.home.add_folders(extra)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
