# Doppel — build spec (internal, for agents)

Cross-platform desktop app (Windows first, also macOS/Linux) that finds duplicate and
near-duplicate photos and lets a normal, non-technical person safely clean them up.
Python 3.10+, PySide6 GUI, Pillow, numpy, send2trash, pillow-heif (optional, HEIC from iPhones).
Package: `src/doppel/` (src layout). Entry: `doppel = "doppel.app:main"` (gui-scripts).

## Product principles
- Never permanently delete. Removals go to the OS Recycle Bin/Trash (send2trash) or, if the
  user chooses, are MOVED to a "Doppel Review" folder. Every action is logged so it can be undone (move back).
- Never modify originals. Read-only scanning.
- Offline, no telemetry, no network.
- Fast on 20k+ photos: cheap checks first, parallel hashing, persistent cache.
- Plain language in the UI ("Exact copies", "Look-alikes", "Keep", "Remove"), no jargon.

## Package layout & ownership

### Engine — `src/doppel/core/` (agent "engine") — NO Qt imports anywhere in core.
`models.py`
```python
@dataclass(frozen=True) class PhotoInfo:
    path: Path; size: int; mtime: float; width: int; height: int
    format: str            # "JPEG","PNG","HEIC",...
    taken: datetime | None # EXIF DateTimeOriginal if available
    camera: str | None     # EXIF Make+Model
    sha: str | None        # full-content blake2b hex (only computed when needed)
    phash: int | None      # 64-bit perceptual hash (DCT pHash)
    dhash: int | None      # 64-bit difference hash
    sharpness: float | None  # variance of Laplacian on a downscaled grayscale (higher = sharper)
    @property megapixels -> float

class MatchKind(Enum): EXACT = "exact"; SIMILAR = "similar"

@dataclass class DuplicateGroup:
    id: int; kind: MatchKind; photos: list[PhotoInfo]
    keep: set[Path]          # recommended to keep (at least one)
    similarity: float        # 1.0 for exact; else 1 - mean_hamming/64 across members
    @property reclaimable_bytes -> int  # sum sizes of photos NOT in keep
```

`scanner.py`
- `IMAGE_EXTS` = jpg jpeg png gif bmp tif tiff webp heic heif (case-insensitive).
- `iter_images(roots: list[Path], include_subfolders=True, skip_hidden=True) -> Iterator[Path]`
  (os.scandir, follow no symlink loops, skip system folders like $RECYCLE.BIN, .Trash, AppData caches).

`hashing.py`
- `file_sha(path, chunk=1<<20) -> str` blake2b.
- `partial_sha(path, nbytes=64*1024) -> str` hash of first+last 64KB (fast pre-filter).
- `image_hashes(path) -> tuple[phash:int, dhash:int, sharpness:float, width, height, format]`
  Implement pHash (32x32 grayscale, 2D DCT via numpy/scipy-free implementation — write a small
  DCT matrix with numpy; top-left 8x8 excluding DC, median threshold) and dHash (9x8) yourself; respect EXIF
  orientation (ImageOps.exif_transpose) so rotated copies match. Use Image.draft() for fast JPEG decode.
- `hamming(a:int,b:int)->int` (int.bit_count).

`metadata.py` — `read_exif(img) -> (taken, camera)` robust to missing/corrupt EXIF.

`cache.py` — `HashCache(db_path)` sqlite (WAL). Key: (path, size, mtime_ns). Stores PhotoInfo fields.
  `get(path, size, mtime_ns) -> PhotoInfo|None`, `put(info)`, `prune(existing_paths)`. Thread-safe.
  Default location: platformdirs-like user cache dir (implement small helper: %LOCALAPPDATA%\Doppel on Windows,
  ~/Library/Caches/Doppel on macOS, $XDG_CACHE_HOME/doppel else).

`finder.py`
```python
@dataclass class ScanOptions:
    roots: list[Path]; include_subfolders: bool = True
    find_exact: bool = True; find_similar: bool = True
    similarity: int = 8      # max Hamming distance on pHash (0..20). UI slider maps "Strict..Loose".
    min_size_bytes: int = 10_240
    workers: int = os.cpu_count()

@dataclass class Progress:
    stage: str               # "Finding photos" | "Checking files" | "Comparing photos" | "Grouping" | "Done"
    done: int; total: int; current: str | None = None

class ScanCancelled(Exception): ...

def scan(opts: ScanOptions, progress: Callable[[Progress], None] | None = None,
         cancel: threading.Event | None = None, cache: HashCache | None = None
         ) -> list[DuplicateGroup]
```
Pipeline: enumerate -> stat -> exact: group by size, then partial_sha, then full sha ->
similar: compute hashes (ThreadPoolExecutor / ProcessPool if faster; Pillow releases GIL in decode) ->
cluster with a BK-tree over pHash (threshold = opts.similarity) confirmed by dHash distance <= threshold+4 ->
union-find to form groups; groups of exact copies are reported as EXACT and NOT duplicated inside SIMILAR groups
(an exact-copy set appears in a similar group only as its single best representative... simpler rule: run exact
first; for similar clustering use one representative per exact set; a similar group lists all members incl. exact copies;
then drop exact groups fully contained in a similar group? NO — keep it simple & documented:
EXACT groups = byte-identical sets. SIMILAR groups = clusters of 2+ *distinct content* items (representatives);
the UI shows exact copies separately). Corrupt/unreadable images are skipped and counted.
Groups sorted by reclaimable_bytes desc. Unreadable files collected in `scan.last_errors` (or return them via a
`ScanResult` dataclass: groups, errors: list[tuple[Path,str]], scanned:int, elapsed:float) — USE ScanResult.

`selector.py` — recommend which to keep:
```python
class KeepRule(Enum): BEST_QUALITY="best"; OLDEST="oldest"; NEWEST="newest"; LARGEST_FILE="largest"; SHORTEST_PATH="path"
def recommend(group: DuplicateGroup, rule: KeepRule = KeepRule.BEST_QUALITY) -> set[Path]
```
BEST_QUALITY: max megapixels, then sharpness, then file size, then has EXIF, then shortest path. Exactly one kept.
Exact groups: prefer oldest taken/mtime, then shortest path (so "IMG_001 (1).jpg" / "Copy of" lose).

`actions.py`
```python
class RemoveMode(Enum): TRASH="trash"; MOVE="move"
@dataclass class ActionRecord: original: Path; destination: Path | None; mode: RemoveMode; ok: bool; error: str|None
def remove(paths, mode, review_dir: Path|None=None, progress=None) -> list[ActionRecord]
def undo(records) -> list[ActionRecord]  # only MOVE mode is undoable; trash -> tell user to restore from Recycle Bin
```
Action log appended as JSON lines in the app data dir (`actions.jsonl`). MOVE preserves relative structure
under review_dir/<YYYY-MM-DD_HHMM>/<drive-or-root-name>/...; never overwrite (add suffix).
Safety: refuse to remove ALL photos of a group (at least one must be kept) — enforce in a helper
`plan_removal(groups) -> list[Path]` that raises if a group would lose every member.

`__init__.py` re-export.

Tests: `tests/core/` generate images with Pillow+numpy in tmp_path (gradients/noise/shapes), create
exact copies, resized (50%), re-saved JPEG q=70, rotated with EXIF orientation tag, slightly cropped (2%),
brightness +10%, and DIFFERENT images that must NOT match. Test cache hit path, cancel, progress monotonic,
selector rules, removal MOVE + undo, plan_removal safety, unreadable file handling, HEIC skipped gracefully if
pillow-heif missing. Fast (<20s).

### GUI — `src/doppel/gui/` + `src/doppel/app.py` (agent "gui")
PySide6 Widgets (not QML). Modern, calm, friendly design; light & dark following the OS
(QApplication.styleHints().colorScheme()), one stylesheet with palette tokens. No emoji; use simple
QPainter-drawn or SVG icons embedded as strings.

Screens (QStackedWidget):
1. **Home**: big friendly title "Find duplicate photos", drop zone (drag folders in) + "Add folder" button,
   list of chosen folders (removable), checkbox "Include subfolders", "What to look for": Exact copies / Look-alikes,
   similarity slider (Strict ↔ Loose with a one-line explanation), big primary "Scan" button. Remember last folders (QSettings).
2. **Scanning**: stage text, progress bar, current file (elided), count found so far, Cancel. Runs scan in a QThread
   worker; progress via signals (throttle to ~20 Hz).
3. **Results**: header summary ("Found 132 groups · 1.8 GB can be freed"), tabs or filter: All / Exact copies / Look-alikes;
   left: group list (thumbnail strip + "3 photos · 12 MB"); right: group detail showing photos side by side as cards
   (thumbnail via background QThreadPool loader + LRU cache, EXIF-rotated), each card: Keep/Remove toggle, resolution,
   size, date taken, folder path (elided, tooltip full), "Best" badge on recommended. Click to open large preview dialog
   (zoom to fit, side-by-side compare of two). "Open file location" (reveal in Explorer/Finder).
   Toolbar: "Auto-select" dropdown (KeepRule), "Select all recommended", review mode toggle.
   Bottom bar: "Remove 248 photos (1.6 GB)" primary button + destination choice (Recycle Bin / Move to review folder).
   Confirmation dialog in plain language. After removal: success screen with "Undo" (if MOVE) and "Open review folder".
   Keyboard: arrows to move between groups, K keep, R remove, Space preview.
4. Empty state ("No duplicates found — your library is tidy") and error list ("12 files couldn't be read" expandable).

Also: About dialog (version, privacy statement), app icon (generate a simple PNG/ICO with Pillow into
`src/doppel/gui/assets/`), window state persistence, High-DPI.

GUI must not freeze: all scanning, thumbnailing, removal in background threads.
Tests: `tests/gui/` with QT_QPA_PLATFORM=offscreen — construct windows, run a scan on generated images
end-to-end through the worker (QSignalSpy / event loop wait), toggle keep/remove, perform MOVE removal + undo.
Screenshots: write a script `scripts/screenshots.py` rendering each screen offscreen with demo data to
`docs/img/*.png` (used in README).

### Packaging (orchestrator)
PyInstaller spec, GitHub Actions building Windows .exe (zip), macOS .app (zip), Linux; release on tag.
