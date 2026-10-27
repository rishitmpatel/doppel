# PyInstaller spec for Doppel.
# Build from the repo root:  pyinstaller packaging/doppel.spec --noconfirm
# Windows / Linux -> single-file executable in dist/
# macOS           -> dist/Doppel.app

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
ASSETS = ROOT / "src" / "doppel" / "gui" / "assets"

if sys.platform == "win32":
    icon = str(ASSETS / "icon.ico")
else:
    icon = str(ASSETS / "icon_1024.png")  # PyInstaller converts PNG -> icns via Pillow on macOS

# Qt modules Doppel never uses; dropping them keeps the download small.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuick3D", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGLWidgets", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer",
    "tkinter", "matplotlib", "scipy", "pytest", "IPython",
]

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ASSETS), "doppel/gui/assets")],
    hiddenimports=["pillow_heif", "send2trash"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True, name="Doppel",
        console=False, icon=icon, argv_emulation=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="Doppel")
    app = BUNDLE(
        coll,
        name="Doppel.app",
        icon=icon,
        bundle_identifier="io.github.rishitmpatel.doppel",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="Doppel",
        console=False,
        icon=icon,
        upx=False,
    )
