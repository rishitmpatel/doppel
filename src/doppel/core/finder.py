"""The scan pipeline: enumerate -> exact duplicates -> perceptual hashes -> clusters."""

from __future__ import annotations

import os
import random
import threading
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

from . import hashing
from .cache import HashCache
from .errors import describe_oserror
from .models import DuplicateGroup, MatchKind, PhotoInfo, ScanCancelled, ScanResult
from .scanner import iter_entries
from .selector import KeepRule, name_penalty, recommend
from . import cluster

__all__ = ["ScanOptions", "Progress", "ScanCancelled", "ScanResult", "scan"]

# Hashing/decoding runs in a thread pool: Pillow releases the GIL while decoding and
# resizing, and on the 2-core benchmark box a process pool was no faster (0.89 s vs
# 0.94 s per 400 images) while adding start-up, pickling and frozen-app (spawn) hazards.
_CACHE_FLUSH = 256
_MIN_PROGRESS_INTERVAL = 0.025  # => at most ~40 progress callbacks per second


@dataclass
class ScanOptions:
    roots: list[Path]
    include_subfolders: bool = True
    find_exact: bool = True
    find_similar: bool = True
    similarity: int = 8  # max Hamming distance on pHash (0..20)
    min_size_bytes: int = 10_240
    workers: int = field(default_factory=lambda: os.cpu_count() or 4)


@dataclass
class Progress:
    stage: str  # "Finding photos" | "Checking files" | "Comparing photos" | "Grouping" | "Done"
    done: int
    total: int  # 0 while unknown
    current: str | None = None


@dataclass
class _File:
    path: Path
    size: int
    mtime: float
    mtime_ns: int


class _Reporter:
    """Throttled, per-stage-monotonic progress emitter (called from the scan thread only)."""

    def __init__(self, callback: Callable[[Progress], None] | None):
        self._cb = callback
        self._last_time = 0.0
        self._stage: str | None = None
        self._max_done: dict[str, int] = {}
        self._emitted: tuple[str, int, int] | None = None

    def __call__(self, stage: str, done: int, total: int, current: str | None = None, force: bool = False) -> None:
        if self._cb is None:
            return
        done = max(done, self._max_done.get(stage, 0))
        self._max_done[stage] = done
        now = time.monotonic()
        if not (force or stage != self._stage or now - self._last_time >= _MIN_PROGRESS_INTERVAL):
            return
        if self._emitted == (stage, done, total) and not force:
            return
        self._stage = stage
        self._last_time = now
        self._emitted = (stage, done, total)
        self._cb(Progress(stage, done, total, current))


def _map_unordered(
    fn: Callable[[Any], Any],
    items: Sequence[Any],
    workers: int,
    cancel: threading.Event | None,
) -> Iterator[tuple[Any, Any, BaseException | None]]:
    """Run ``fn`` over ``items`` in a pool; yield ``(item, result, exception)`` as they finish.

    Keeps a bounded window in flight, polls ``cancel`` every 50 ms and, when cancelled,
    returns immediately (running tasks finish in the background) raising ScanCancelled.
    """
    if not items:
        return
    workers = max(1, min(int(workers), len(items)))
    ex = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="doppel")
    it = iter(items)
    pending: dict[Future, Any] = {}

    def top_up() -> None:
        while len(pending) < workers * 4:
            try:
                item = next(it)
            except StopIteration:
                return
            pending[ex.submit(fn, item)] = item

    try:
        top_up()
        while pending:
            done, _ = wait(list(pending), timeout=0.05, return_when=FIRST_COMPLETED)
            if cancel is not None and cancel.is_set():
                raise ScanCancelled()
            for fut in done:
                item = pending.pop(fut)
                try:
                    res = fut.result()
                except ScanCancelled:
                    raise
                except Exception as exc:  # per-file failure, reported by the caller
                    yield item, None, exc
                else:
                    yield item, res, None
            top_up()
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ScanCancelled()


# --------------------------------------------------------------------------- exact duplicates
def _exact_sets(
    files: list[_File],
    cache: HashCache | None,
    workers: int,
    cancel: threading.Event | None,
    rep: _Reporter,
    errors: dict[Path, str],
) -> list[tuple[str, list[_File]]]:
    """Byte-identical sets. Only files sharing size AND partial hash are fully hashed."""
    by_size: dict[int, list[_File]] = defaultdict(list)
    for f in files:
        by_size[f.size].append(f)
    cands = [f for g in by_size.values() if len(g) > 1 for f in g]
    n1 = len(cands)
    total = 2 * n1
    stage = "Checking files"
    rep(stage, 0, total, force=True)
    if not cands:
        rep(stage, 0, 0, force=True)
        return []

    done = 0
    psha: dict[Path, str] = {}
    todo: list[_File] = []
    for i, f in enumerate(cands):
        p = cache.get_partial(f.path, f.size, f.mtime_ns) if cache else None
        if p is None:
            todo.append(f)
        else:
            psha[f.path] = p
            done += 1
            if i % 128 == 0:
                _check(cancel)
            rep(stage, done, total, str(f.path))
    new_partials: list[tuple[Path, int, int, str]] = []
    try:
        for f, res, exc in _map_unordered(lambda f: hashing.partial_sha(f.path, cancel=cancel), todo, workers, cancel):
            done += 1
            if exc is not None:
                errors.setdefault(f.path, describe_oserror(exc))
            else:
                psha[f.path] = res
                new_partials.append((f.path, f.size, f.mtime_ns, res))
            rep(stage, done, total, str(f.path))
    finally:
        if cache and new_partials:
            cache.put_partials(new_partials)

    by_partial: dict[tuple[int, str], list[_File]] = defaultdict(list)
    for f in cands:
        if f.path in psha:
            by_partial[(f.size, psha[f.path])].append(f)
    sets: list[tuple[str, list[_File]]] = []
    need_full: list[_File] = []
    for (size, ph), g in by_partial.items():
        if len(g) < 2:
            continue
        if size <= 2 * hashing.PARTIAL_BYTES:
            sets.append((ph, g))  # partial hash of a small file *is* its full hash
        else:
            need_full.extend(g)
    done = n1 + (n1 - len(need_full))  # files that need no full hash are finished
    rep(stage, done, total, force=True)

    shas: dict[Path, str] = {}
    to_hash: list[_File] = []
    for f in need_full:
        c = cache.get(f.path, f.size, f.mtime_ns) if cache else None
        if c is not None and c.sha:
            shas[f.path] = c.sha
            done += 1
            rep(stage, done, total, str(f.path))
        else:
            to_hash.append(f)
    new_rows: list[tuple[PhotoInfo, int]] = []
    try:
        for f, res, exc in _map_unordered(lambda f: hashing.file_sha(f.path, cancel=cancel), to_hash, workers, cancel):
            done += 1
            if exc is not None:
                errors.setdefault(f.path, describe_oserror(exc))
            else:
                shas[f.path] = res
                new_rows.append((PhotoInfo(f.path, f.size, f.mtime, 0, 0, "", sha=res), f.mtime_ns))
                if len(new_rows) >= _CACHE_FLUSH and cache:
                    cache.put_many(new_rows)
                    new_rows = []
            rep(stage, done, total, str(f.path))
    finally:
        if cache and new_rows:
            cache.put_many(new_rows)

    by_sha: dict[tuple[int, str], list[_File]] = defaultdict(list)
    for f in need_full:
        if f.path in shas:
            by_sha[(f.size, shas[f.path])].append(f)
    sets.extend((sha, g) for (_size, sha), g in by_sha.items() if len(g) > 1)
    rep(stage, total, total, force=True)
    return sets


# --------------------------------------------------------------------------- analysis
def _info_from(f: _File, an: hashing.ImageAnalysis, sha: str | None) -> PhotoInfo:
    return PhotoInfo(
        path=f.path, size=f.size, mtime=f.mtime, width=an.width, height=an.height, format=an.format,
        taken=an.taken, camera=an.camera, sha=sha,
        phash=None if an.flat else an.phash, dhash=None if an.flat else an.dhash, sharpness=an.sharpness,
    )


_Thumbs = dict[Path, tuple[float, bytes]]  # path -> (graphic share, 64x64 gray thumbnail)


def _analyze_all(
    targets: list[_File],
    sha_of: dict[Path, str],
    cache: HashCache | None,
    workers: int,
    cancel: threading.Event | None,
    rep: _Reporter,
    errors: dict[Path, str],
) -> tuple[dict[Path, PhotoInfo], _Thumbs]:
    stage = "Comparing photos"
    total = len(targets)
    rep(stage, 0, total, force=True)
    infos: dict[Path, PhotoInfo] = {}
    thumbs: _Thumbs = {}
    todo: list[_File] = []
    done = 0
    for i, f in enumerate(targets):
        if cache is not None:
            c = cache.get(f.path, f.size, f.mtime_ns)
            th = cache.get_thumb(f.path, f.size, f.mtime_ns) if c is not None and c.width > 0 else None
            if th is not None:
                thumbs[f.path] = th
                infos[f.path] = replace(c, path=f.path, mtime=f.mtime, sha=sha_of.get(f.path) or c.sha)
                done += 1
                if i % 128 == 0:
                    _check(cancel)
                rep(stage, done, total, str(f.path))
                continue
            msg = cache.get_error(f.path, f.size, f.mtime_ns)
            if msg is not None:
                errors.setdefault(f.path, msg)
                done += 1
                rep(stage, done, total, str(f.path))
                continue
        todo.append(f)

    rows: list[tuple[PhotoInfo, int]] = []
    err_rows: list[tuple[Path, int, int, str]] = []
    thumb_rows: list[tuple[Path, int, int, float, bytes]] = []

    def flush() -> None:
        nonlocal rows, err_rows, thumb_rows
        if cache is not None:
            cache.put_many(rows)
            cache.put_errors(err_rows)
            cache.put_thumbs(thumb_rows)
        rows, err_rows, thumb_rows = [], [], []

    try:
        for f, an, exc in _map_unordered(lambda f: hashing.analyze_image(f.path), todo, workers, cancel):
            done += 1
            if exc is not None:
                msg = hashing.describe_error(exc, f.path)
                errors.setdefault(f.path, msg)
                if hashing.is_permanent_error(exc) and "pillow-heif" not in msg:
                    err_rows.append((f.path, f.size, f.mtime_ns, msg))
            else:
                info = _info_from(f, an, sha_of.get(f.path))
                infos[f.path] = info
                thumbs[f.path] = (an.graphic, an.thumb)
                rows.append((info, f.mtime_ns))
                thumb_rows.append((f.path, f.size, f.mtime_ns, an.graphic, an.thumb))
                if len(rows) >= _CACHE_FLUSH:
                    flush()
            rep(stage, done, total, str(f.path))
    finally:
        flush()
    rep(stage, total, total, force=True)
    return infos, thumbs


# --------------------------------------------------------------------------- grouping
def _mean_similarity(photos: list[PhotoInfo]) -> float:
    hs = [p.phash for p in photos if p.phash is not None]
    n = len(hs)
    if n < 2:
        return 1.0
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    if len(pairs) > 1000:
        pairs = random.Random(0).sample(pairs, 1000)
    mean = sum(hashing.hamming(hs[i], hs[j]) for i, j in pairs) / len(pairs)
    return max(0.0, min(1.0, 1.0 - mean / 64.0))


def _make_group(kind: MatchKind, photos: list[PhotoInfo], similarity: float) -> DuplicateGroup:
    g = DuplicateGroup(id=0, kind=kind, photos=photos, keep=set(), similarity=similarity)
    g.keep = recommend(g, KeepRule.BEST_QUALITY)
    g.photos = sorted(photos, key=lambda p: (p.path not in g.keep, str(p.path)))
    return g


def _store_members(cache: HashCache | None, infos: Iterable[PhotoInfo], f_of: dict[Path, _File]) -> None:
    """Persist analysis + sha for exact-set members that the cache does not have yet."""
    if cache is None:
        return
    rows = []
    for info in infos:
        f = f_of[info.path]
        c = cache.get(f.path, f.size, f.mtime_ns)
        if c is None or c.width == 0 or c.sha != info.sha:
            rows.append((info, f.mtime_ns))
    cache.put_many(rows)


def scan(
    opts: ScanOptions,
    progress: Callable[[Progress], None] | None = None,
    cancel: threading.Event | None = None,
    cache: HashCache | None = None,
) -> ScanResult:
    """Find duplicate photos.

    Pipeline: enumerate + stat -> exact duplicates (group by size, then by partial hash,
    full hash only for survivors) -> decode each distinct image once (thread pool, JPEG
    draft mode) for pHash/dHash/sharpness/EXIF -> cluster look-alikes.

    * EXACT groups are byte-identical sets (2+ files, ``similarity == 1.0``).
    * SIMILAR groups are clusters of 2+ *distinct-content* photos: an exact-copy set takes
      part in look-alike matching through one representative (its recommended copy), so
      exact copies are never repeated inside a SIMILAR group - even with
      ``find_exact=False`` the copies are collapsed, they just are not reported.
    * Pairs match when pHash distance <= ``similarity`` and dHash distance <=
      ``similarity + 4`` *and* a structural check on 64x64 thumbnails passes (strict for
      screenshots/documents, see ``cluster.confirm_pairs``); clusters are connected
      components of matching pairs.
    * Uniform images (flat colour) are only compared byte-for-byte, never by look.
    * Unreadable files (corrupt, empty, wrong type, too large, permission denied ...) are
      listed in ``ScanResult.errors`` instead of aborting the scan.

    ``progress`` and all other callbacks run on the calling thread. ``cancel`` is polled
    at least every 50 ms; the scan then raises :class:`ScanCancelled` (hashes computed so
    far stay cached). ``cache=None`` disables caching. Groups are sorted by reclaimable
    bytes, largest first.
    """
    t0 = time.perf_counter()
    with hashing.bomb_guard():
        return _scan(opts, progress, cancel, cache, t0)


def _scan(
    opts: ScanOptions,
    progress: Callable[[Progress], None] | None,
    cancel: threading.Event | None,
    cache: HashCache | None,
    t0: float,
) -> ScanResult:
    rep = _Reporter(progress)
    errors: dict[Path, str] = {}
    workers = max(1, int(opts.workers or 1))
    max_dist = max(0, min(64, int(opts.similarity)))
    _check(cancel)

    # ---- 1. find photos
    roots = [Path(r) for r in opts.roots]
    files: list[_File] = []
    found: list[Path] = []
    rep("Finding photos", 0, 0, force=True)
    for path, st in iter_entries(roots, opts.include_subfolders, True, lambda p, m: errors.setdefault(p, m), cancel):
        found.append(path)
        rep("Finding photos", len(found), 0, str(path))
        if st.st_size == 0:
            if opts.min_size_bytes <= 0:
                errors.setdefault(path, "Empty file (0 bytes)")
            continue
        if st.st_size >= opts.min_size_bytes:
            files.append(_File(path, st.st_size, st.st_mtime, st.st_mtime_ns))
    rep("Finding photos", len(found), len(found), force=True)
    if cache is not None and opts.include_subfolders:
        cache.prune(found, under=roots)

    def finish(groups: list[DuplicateGroup]) -> ScanResult:
        groups.sort(key=lambda g: (-g.reclaimable_bytes, -g.total_bytes, str(g.photos[0].path)))
        for i, g in enumerate(groups, 1):
            g.id = i
        rep("Done", len(groups), len(groups), force=True)
        return ScanResult(groups, sorted(errors.items(), key=lambda kv: str(kv[0])), len(files), time.perf_counter() - t0)

    if not (opts.find_exact or opts.find_similar) or not files:
        return finish([])

    # ---- 2. exact duplicates (also needed to collapse copies before look-alike matching)
    sets = _exact_sets(files, cache, workers, cancel, rep, errors)
    in_set: set[Path] = {f.path for _sha, g in sets for f in g}
    sha_of: dict[Path, str] = {f.path: sha for sha, g in sets for f in g}
    f_of = {f.path: f for f in files}
    reps: dict[str, _File] = {
        sha: min(g, key=lambda f: (name_penalty(f.path), f.mtime, len(str(f.path)), str(f.path))) for sha, g in sets
    }

    # ---- 3. decode each distinct image once
    singles = [f for f in files if f.path not in in_set and f.path not in errors] if opts.find_similar else []
    targets = [f for f in (*reps.values(), *singles) if f.path not in errors]
    infos, thumbs = _analyze_all(targets, sha_of, cache, workers, cancel, rep, errors)

    # ---- 4. assemble groups
    groups: list[DuplicateGroup] = []
    candidates: list[PhotoInfo] = []
    for sha, members in sets:
        r = reps[sha]
        ri = infos.get(r.path)
        if ri is None:
            msg = errors.get(r.path, "Image file is damaged or unreadable")
            for m in members:
                errors.setdefault(m.path, msg)
            continue
        member_infos = [replace(ri, path=m.path, size=m.size, mtime=m.mtime, sha=sha) for m in members]
        _store_members(cache, member_infos, f_of)
        by_path = {p.path: p for p in member_infos}
        if opts.find_exact:
            groups.append(_make_group(MatchKind.EXACT, member_infos, 1.0))
        candidates.append(by_path[r.path])
    if opts.find_similar:
        candidates += [infos[f.path] for f in singles if f.path in infos]
    candidates = [p for p in candidates if p.phash is not None and p.dhash is not None]

    # ---- 5. look-alikes
    if opts.find_similar and len(candidates) >= 2:
        stage = "Grouping"
        n = len(candidates)
        rep(stage, 0, n, force=True)
        pi, pj = cluster.find_pairs(
            [p.phash for p in candidates], [p.dhash for p in candidates], max_dist,  # type: ignore[misc]
            cancel=cancel, on_progress=lambda d, t: rep(stage, d, t),
        )
        if len(pi):
            ok = cluster.confirm_pairs(
                pi, pj, [thumbs[p.path][1] for p in candidates], [thumbs[p.path][0] for p in candidates], cancel
            )
            pi, pj = pi[ok], pj[ok]
        for comp in cluster.clusters(n, pi, pj):
            photos = [candidates[i] for i in comp]
            groups.append(_make_group(MatchKind.SIMILAR, photos, _mean_similarity(photos)))
        rep(stage, n, n, force=True)
    return finish(groups)
