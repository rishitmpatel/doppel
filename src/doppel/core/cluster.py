"""Near-duplicate clustering: all-pairs Hamming search over 64-bit hashes + union-find.

A blocked numpy brute force replaces a BK-tree: for the radii we use (up to ~20 of
64 bits) a BK-tree degenerates to visiting most nodes in pure Python, while the
vectorised XOR + popcount does ~1e9 pair tests/second, i.e. 20k photos in ~1 s.
"""

from __future__ import annotations

import threading
from typing import Callable, Sequence

import numpy as np

from .models import ScanCancelled

_TARGET_ELEMS = 4_000_000  # pairs per block (~32 MB of uint64 temporaries)

if hasattr(np, "bitwise_count"):  # numpy >= 2.0

    def popcount(x: np.ndarray) -> np.ndarray:
        return np.bitwise_count(x)

else:  # pragma: no cover - old numpy
    _POP16 = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.uint8)

    def popcount(x: np.ndarray) -> np.ndarray:
        x = np.ascontiguousarray(x)
        parts = _POP16[x.view(np.uint16).reshape(*x.shape, 4)]
        return parts.sum(axis=-1, dtype=np.uint8)


def find_pairs(
    phashes: Sequence[int],
    dhashes: Sequence[int],
    max_dist: int,
    dhash_slack: int = 4,
    cancel: threading.Event | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Indices ``(i, j)``, ``i < j``, with pHash distance <= ``max_dist`` and
    dHash distance <= ``max_dist + dhash_slack``."""
    n = len(phashes)
    ph = np.array(phashes, dtype=np.uint64)
    dh = np.array(dhashes, dtype=np.uint64)
    out_i: list[np.ndarray] = []
    out_j: list[np.ndarray] = []
    block = max(1, min(n, _TARGET_ELEMS // max(n, 1)))
    for i0 in range(0, n, block):
        if cancel is not None and cancel.is_set():
            raise ScanCancelled()
        i1 = min(n, i0 + block)
        d = popcount(ph[i0:i1, None] ^ ph[None, i0:])
        r, c = np.nonzero(d <= max_dist)
        r = r + i0
        c = c + i0
        m = c > r
        r, c = r[m], c[m]
        if r.size:
            dd = popcount(dh[r] ^ dh[c])
            ok = dd <= max_dist + dhash_slack
            out_i.append(r[ok])
            out_j.append(c[ok])
        if on_progress is not None:
            on_progress(i1, n)
    if not out_i:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    return np.concatenate(out_i), np.concatenate(out_j)


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        p = self.parent
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def clusters(n: int, pairs_i: np.ndarray, pairs_j: np.ndarray) -> list[list[int]]:
    """Connected components (size >= 2) of the graph given by the pair arrays."""
    uf = UnionFind(n)
    for a, b in zip(pairs_i.tolist(), pairs_j.tolist()):
        uf.union(a, b)
    comps: dict[int, list[int]] = {}
    for idx in set(pairs_i.tolist()) | set(pairs_j.tolist()):
        comps.setdefault(uf.find(idx), []).append(idx)
    return [sorted(v) for v in comps.values() if len(v) >= 2]


# --------------------------------------------------------------------------- confirmation
STRICT_MEAN = 0.06   # mean |z-score difference| allowed between graphic thumbnails
STRICT_P99 = 0.28    # 99th percentile of the same
GRAPHIC_SHARE = 0.30  # dominant-gray-band share from which an image counts as "graphic" ...
GRAPHIC_STD = 10.0    # ... provided its thumbnail has real contrast (gray-level std)
LOOSE_NCC = 0.6      # sanity floor for photographs
CROP_TRIES = (0.02, 0.04, 0.06)  # per-side crops tolerated for graphic images
LOW_CONTRAST = 3.0    # thumbnails flatter than this (gray-level std) skip the correlation check
STD_FLOOR = 4.0      # gray levels; stops near-uniform images being amplified by the z-score

_CHUNK = 1024


def _blur(x: np.ndarray, passes: int = 2) -> np.ndarray:
    """Separable [1 4 6 4 1]/16 blur of a (n, h, w) stack, edge-replicated."""
    for _ in range(passes):
        for ax in (1, 2):
            p = [(0, 0)] * 3
            p[ax] = (2, 2)
            y = np.pad(x, p, mode="edge")
            sl = lambda a, b: tuple(slice(a, y.shape[k] - b) if k == ax else slice(None) for k in range(3))  # noqa: E731
            x = (y[sl(0, 4)] + 4 * y[sl(1, 3)] + 6 * y[sl(2, 2)] + 4 * y[sl(3, 1)] + y[sl(4, 0)]) / 16
    return x


def _z(x: np.ndarray) -> np.ndarray:
    """Per-image brightness/contrast normalisation of an (n, h, w) stack."""
    flat = x.reshape(len(x), -1)
    mu = flat.mean(axis=1)[:, None, None]
    sd = np.maximum(flat.std(axis=1), STD_FLOOR)[:, None, None]
    return (x - mu) / sd


def _strict_ok(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = np.abs(a - b).reshape(len(a), -1)
    return (d.mean(axis=1) <= STRICT_MEAN) & (np.percentile(d, 99, axis=1) <= STRICT_P99)


def _zoomed(x: np.ndarray, frac: float) -> np.ndarray:
    """Centre crop of a blurred thumbnail (``frac`` per side) scaled back to full size."""
    from PIL import Image

    h, w = x.shape
    box = (frac * w, frac * h, w - frac * w, h - frac * h)
    return np.asarray(Image.fromarray(x.astype(np.float32), "F").resize((w, h), Image.Resampling.BICUBIC, box=box))


def confirm_pairs(
    pi: np.ndarray,
    pj: np.ndarray,
    thumbs: Sequence[bytes],
    graphic: Sequence[float],
    cancel: threading.Event | None = None,
) -> np.ndarray:
    """Boolean mask over the candidate pairs: do the pictures really look the same?

    Coarse 64-bit hashes cannot tell apart screenshots and documents (white page, same
    layout, different text). Each candidate pair is therefore compared on lightly blurred
    64x64 grayscale thumbnails after normalising brightness/contrast (z-score):

    * if either image is *graphic* (>= 30% of pixels in one gray band and a contrasty
      thumbnail) the thumbnails must agree almost pixel for pixel: mean difference <= 0.06
      sigma and 99th percentile <= 0.28 (measured on 480 screenshot/document re-saves:
      <= 0.045 / 0.23; on 6600 look-alike-layout but different screens: >= 0.015 / 0.34, the
      p99 test being the one that catches a few different words). A centre crop of up to 6%
      per side is also tried (on blurred thumbnails), so cropped copies still match;
    * otherwise (photographs, where small crops legitimately shift things) the 32x32
      thumbnails must correlate with NCC >= 0.6, which only rejects gross mismatches.
    """
    n = len(pi)
    keep = np.zeros(n, dtype=bool)
    if n == 0:
        return keep
    side = int(round(len(thumbs[0]) ** 0.5))
    half = side // 2
    gr = np.asarray(graphic, dtype=np.float32)
    raws: dict[int, np.ndarray] = {}
    sds: dict[int, float] = {}

    def stack(idx: np.ndarray) -> np.ndarray:
        for i in idx.tolist():
            if i not in raws:
                raws[i] = np.frombuffer(thumbs[i], dtype=np.uint8).reshape(side, side).astype(np.float32)
                sds[i] = float(raws[i].std())
        return np.stack([raws[i] for i in idx.tolist()])

    for s in range(0, n, _CHUNK):
        if cancel is not None and cancel.is_set():
            raise ScanCancelled()
        ia, ib = pi[s:s + _CHUNK], pj[s:s + _CHUNK]
        xa, xb = stack(ia), stack(ib)
        sa = np.array([sds[i] for i in ia.tolist()])
        sb = np.array([sds[i] for i in ib.tolist()])
        strict = ((gr[ia] >= GRAPHIC_SHARE) & (sa >= GRAPHIC_STD)) | ((gr[ib] >= GRAPHIC_SHARE) & (sb >= GRAPHIC_STD))
        ok = _strict_ok(_z(xa), _z(xb))
        for k in np.nonzero(strict & ~ok)[0]:  # crop-compensated retry on blurred thumbnails (rare)
            ba, bb = _blur(xa[k:k + 1], 1)[0], _blur(xb[k:k + 1], 1)[0]
            for frac in CROP_TRIES:
                if _strict_ok(_z(_zoomed(ba, frac)[None]), _z(bb[None]))[0] or \
                        _strict_ok(_z(ba[None]), _z(_zoomed(bb, frac)[None]))[0]:
                    ok[k] = True
                    break

        def small(x: np.ndarray) -> np.ndarray:
            g = x.reshape(-1, half, 2, half, 2).mean(axis=(2, 4))
            return (g - g.mean(axis=(1, 2), keepdims=True)) / np.maximum(g.std(axis=(1, 2), keepdims=True), 1e-3)

        ncc = (small(_blur(xa)) * small(_blur(xb))).mean(axis=(1, 2))
        flat_pair = np.minimum(sa, sb) < LOW_CONTRAST  # nothing meaningful to correlate
        keep[s:s + _CHUNK] = np.where(strict, ok, (ncc >= LOOSE_NCC) | flat_pair)
    return keep
