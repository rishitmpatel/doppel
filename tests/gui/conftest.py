import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    from doppel.gui import theme

    app = QApplication.instance() or QApplication(["doppel-tests"])
    theme.install(app, theme.LIGHT)
    return app


@pytest.fixture
def settings(tmp_path):
    from PySide6.QtCore import QSettings

    return QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)


@pytest.fixture
def win(qapp, settings, tmp_path, monkeypatch):
    monkeypatch.setenv("DOPPEL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOPPEL_CACHE_DIR", str(tmp_path / "cache"))
    from doppel.gui.mainwindow import MainWindow

    w = MainWindow(settings, use_cache=False)
    w.resize(1280, 800)
    w.show()
    yield w
    w.close()
    qapp.processEvents()
