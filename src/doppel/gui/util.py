"""Small helpers shared by the GUI (formatting, platform glue). No Qt widgets here."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def human_size(n: int | float) -> str:
    n = float(max(0, n))
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if n >= 100 else f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


def plural(n: int, singular: str, plural_: str | None = None) -> str:
    return f"{n:,} {singular if n == 1 else (plural_ or singular + 's')}"


def fmt_date(dt: datetime | None, with_time: bool = True) -> str:
    if dt is None:
        return ""
    try:
        fmt = "%d %b %Y, %H:%M" if with_time else "%d %b %Y"
        return dt.strftime(fmt).lstrip("0")
    except Exception:
        return ""


def fmt_mtime(ts: float) -> str:
    try:
        return fmt_date(datetime.fromtimestamp(ts))
    except Exception:
        return ""


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} sec"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s:02d} sec"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"


def trash_name() -> str:
    """What this OS calls the place deleted files go."""
    return "Recycle Bin" if sys.platform.startswith("win") else "Trash"


def default_review_dir() -> Path:
    home = Path.home()
    pics = home / "Pictures"
    base = pics if pics.exists() else home
    return base / "Doppel Review"


def short_path(p: Path | str) -> str:
    """Display a path with ~ for the home directory."""
    s = str(p)
    home = str(Path.home())
    if s == home:
        return "~"
    if s.startswith(home + ("\\" if "\\" in s else "/")):
        return "~" + s[len(home):]
    return s


def reveal_in_file_manager(path: Path | str) -> bool:
    """Show the file in Explorer / Finder / the default Linux file manager."""
    p = Path(path)
    try:
        if sys.platform.startswith("win"):
            target = p if p.exists() else p.parent
            if p.exists():
                subprocess.Popen(["explorer", f"/select,{target}"])
            else:
                subprocess.Popen(["explorer", str(target)])
            return True
        if sys.platform == "darwin":
            if p.exists():
                subprocess.Popen(["open", "-R", str(p)])
            else:
                subprocess.Popen(["open", str(p.parent)])
            return True
    except Exception:
        pass
    folder = p if p.is_dir() else p.parent
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def open_folder(path: Path | str) -> bool:
    p = Path(path)
    folder = p if p.is_dir() else p.parent
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def app_version() -> str:
    try:
        from doppel import __version__
        return __version__
    except Exception:
        return "0.1.0"
