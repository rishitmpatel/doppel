"""Persistent SQLite hash cache (WAL, thread- and process-safe).

One connection guarded by a re-entrant lock serves all threads of a process;
``busy_timeout`` + WAL let several processes share the same file. The cache is
disposable: a schema/hash-version mismatch or a corrupt file simply resets it.

Four tables, all keyed by path and validated against ``(size, mtime_ns)``:
``photos`` (a :class:`PhotoInfo`; ``width == 0`` means "only the sha is known"),
``partials`` (first+last-64KB hash) and ``errors`` (permanently unreadable files) and ``thumbs`` (64x64 structural thumbnails).
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .hashing import HASH_VERSION
from .models import PhotoInfo
from .paths import user_cache_dir

SCHEMA_VERSION = 2


def default_cache_dir() -> Path:
    return user_cache_dir()


def default_db_path() -> Path:
    return default_cache_dir() / "hashes.sqlite3"


def _s64(v: int | None) -> int | None:
    if v is None:
        return None
    return v - (1 << 64) if v >= (1 << 63) else v


def _u64(v: int | None) -> int | None:
    if v is None:
        return None
    return v + (1 << 64) if v < 0 else v


def mtime_ns_of(info: PhotoInfo) -> int:
    return int(round(info.mtime * 1e9))


_PHOTO_COLS = "width, height, format, taken, camera, sha, phash, dhash, sharpness"


class HashCache:
    """``HashCache(db_path)``; ``db_path=None`` uses the per-user default location."""

    def __init__(self, db_path: str | Path | None = None):
        self._lock = threading.RLock()
        self._closed = False
        if db_path is None:
            db_path = default_db_path()
        self.path: Path | None = None if str(db_path) == ":memory:" else Path(db_path)
        self._conn = self._open()

    # ------------------------------------------------------------------ setup
    def _connect(self) -> sqlite3.Connection:
        target = ":memory:" if self.path is None else str(self.path)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target, timeout=30.0, check_same_thread=False, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            if self.path is not None:
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except BaseException:
            conn.close()
            raise
        return conn

    def _open(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._connect()
            self._init_schema(conn)
            return conn
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                with contextlib.suppress(Exception):
                    conn.close()
            if self.path is None or "locked" in str(exc).lower():
                raise
            # corrupt / not a database: start over
            for suffix in ("", "-wal", "-shm"):
                with contextlib.suppress(OSError):
                    Path(str(self.path) + suffix).unlink()
            conn = self._connect()
            self._init_schema(conn)
            return conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            ok = rows.get("schema_version") == str(SCHEMA_VERSION) and rows.get("hash_version") == str(HASH_VERSION)
            if not ok:
                for t in ("photos", "partials", "errors", "thumbs"):
                    conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS photos ("
                "path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,"
                "width INTEGER NOT NULL DEFAULT 0, height INTEGER NOT NULL DEFAULT 0,"
                "format TEXT NOT NULL DEFAULT '', taken TEXT, camera TEXT, sha TEXT,"
                "phash INTEGER, dhash INTEGER, sharpness REAL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS partials ("
                "path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, psha TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS errors ("
                "path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, message TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS thumbs ("
                "path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,"
                "graphic REAL NOT NULL, thumb BLOB NOT NULL)"
            )
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('hash_version', ?)", (str(HASH_VERSION),))
            conn.execute("COMMIT")
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise

    @contextlib.contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # ------------------------------------------------------------------ photos
    def get(self, path: str | Path, size: int, mtime_ns: int) -> PhotoInfo | None:
        """Cached info if ``path`` still has this size and mtime, else None."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT size, mtime_ns, {_PHOTO_COLS} FROM photos WHERE path = ?", (str(path),)
            ).fetchone()
        if row is None or row[0] != size or row[1] != mtime_ns:
            return None
        return self._to_info(Path(path), size, mtime_ns, row[2:])

    @staticmethod
    def _to_info(path: Path, size: int, mtime_ns: int, r: tuple) -> PhotoInfo:
        width, height, fmt, taken, camera, sha, phash, dhash, sharp = r
        try:
            taken_dt = datetime.fromisoformat(taken) if taken else None
        except ValueError:
            taken_dt = None
        return PhotoInfo(
            path=path, size=size, mtime=mtime_ns / 1e9, width=width, height=height, format=fmt,
            taken=taken_dt, camera=camera, sha=sha, phash=_u64(phash), dhash=_u64(dhash), sharpness=sharp,
        )

    def put(self, info: PhotoInfo, mtime_ns: int | None = None) -> None:
        self.put_many([(info, mtime_ns_of(info) if mtime_ns is None else mtime_ns)])

    def put_many(self, rows: Iterable[tuple[PhotoInfo, int]]) -> None:
        """Store ``(info, mtime_ns)`` pairs in one transaction.

        Known values are merged into an existing row for the same file version
        (a new ``sha`` does not erase old hashes); a changed size/mtime replaces it.
        """
        rows = list(rows)
        if not rows:
            return
        with self._tx() as c:
            for info, ns in rows:
                key = str(info.path)
                old = c.execute(
                    f"SELECT size, mtime_ns, {_PHOTO_COLS} FROM photos WHERE path = ?", (key,)
                ).fetchone()
                new = (
                    info.width, info.height, info.format,
                    info.taken.isoformat() if info.taken else None, info.camera, info.sha,
                    _s64(info.phash), _s64(info.dhash), info.sharpness,
                )
                if old is not None and old[0] == info.size and old[1] == ns:
                    merged = list(old[2:])
                    for i, v in enumerate(new):
                        if v is None or (i < 2 and v == 0) or (i == 2 and v == ""):
                            continue
                        merged[i] = v
                    new = tuple(merged)  # type: ignore[assignment]
                c.execute(
                    f"INSERT OR REPLACE INTO photos (path, size, mtime_ns, {_PHOTO_COLS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (key, info.size, ns, *new),
                )

    # ------------------------------------------------------------------ partial hashes
    def get_partial(self, path: str | Path, size: int, mtime_ns: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT size, mtime_ns, psha FROM partials WHERE path = ?", (str(path),)
            ).fetchone()
        return row[2] if row and row[0] == size and row[1] == mtime_ns else None

    def put_partials(self, rows: Iterable[tuple[str | Path, int, int, str]]) -> None:
        """Store ``(path, size, mtime_ns, partial_sha)`` rows."""
        data = [(str(p), s, ns, h) for p, s, ns, h in rows]
        if data:
            with self._tx() as c:
                c.executemany("INSERT OR REPLACE INTO partials VALUES (?, ?, ?, ?)", data)

    # ------------------------------------------------------------------ structural thumbnails
    def get_thumb(self, path: str | Path, size: int, mtime_ns: int) -> tuple[float, bytes] | None:
        """``(graphic_share, 64x64 gray thumbnail)`` stored for this file version, if any."""
        with self._lock:
            row = self._conn.execute(
                "SELECT size, mtime_ns, graphic, thumb FROM thumbs WHERE path = ?", (str(path),)
            ).fetchone()
        return (row[2], bytes(row[3])) if row and row[0] == size and row[1] == mtime_ns else None

    def put_thumbs(self, rows: Iterable[tuple[str | Path, int, int, float, bytes]]) -> None:
        """Store ``(path, size, mtime_ns, graphic_share, thumb)`` rows."""
        data = [(str(p), s, ns, g, sqlite3.Binary(t)) for p, s, ns, g, t in rows]
        if data:
            with self._tx() as c:
                c.executemany("INSERT OR REPLACE INTO thumbs VALUES (?, ?, ?, ?, ?)", data)

    # ------------------------------------------------------------------ errors
    def get_error(self, path: str | Path, size: int, mtime_ns: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT size, mtime_ns, message FROM errors WHERE path = ?", (str(path),)
            ).fetchone()
        return row[2] if row and row[0] == size and row[1] == mtime_ns else None

    def put_errors(self, rows: Iterable[tuple[str | Path, int, int, str]]) -> None:
        data = [(str(p), s, ns, m) for p, s, ns, m in rows]
        if data:
            with self._tx() as c:
                c.executemany("INSERT OR REPLACE INTO errors VALUES (?, ?, ?, ?)", data)

    # ------------------------------------------------------------------ maintenance
    def prune(self, existing_paths: Iterable[str | Path], under: Iterable[str | Path] | None = None) -> int:
        """Delete rows whose path is not in ``existing_paths``; return how many.

        With ``under`` only rows located inside one of those folders are candidates,
        so scanning one folder never forgets another folder's hashes.
        """
        keep = {str(p) for p in existing_paths}
        prefixes: list[str] | None = None
        if under is not None:
            prefixes = [str(u).rstrip("/\\") + os.sep for u in under]
        removed = 0
        with self._tx() as c:
            for table in ("photos", "partials", "errors", "thumbs"):
                stale = [
                    (p,)
                    for (p,) in c.execute(f"SELECT path FROM {table}").fetchall()
                    if p not in keep and (prefixes is None or any(p.startswith(x) for x in prefixes))
                ]
                c.executemany(f"DELETE FROM {table} WHERE path = ?", stale)
                if table == "photos":
                    removed = len(stale)
        return removed

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0])

    def clear(self) -> None:
        with self._tx() as c:
            for t in ("photos", "partials", "errors", "thumbs"):
                c.execute(f"DELETE FROM {t}")

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                with contextlib.suppress(sqlite3.Error):
                    self._conn.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

    def __enter__(self) -> "HashCache":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = ["HashCache", "default_cache_dir", "default_db_path", "mtime_ns_of"]
