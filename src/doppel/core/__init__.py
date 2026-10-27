"""Doppel engine: duplicate / look-alike photo detection and safe removal (no Qt)."""

from .actions import (
    ActionRecord,
    RemoveMode,
    UnsafeRemovalError,
    default_log_path,
    plan_removal,
    read_log,
    remove,
    undo,
)
from .cache import HashCache, default_cache_dir, default_db_path
from .finder import Progress, ScanOptions, scan
from .hashing import file_sha, hamming, image_hashes, partial_sha
from .metadata import read_exif
from .models import DuplicateGroup, MatchKind, PhotoInfo, ScanCancelled, ScanResult
from .scanner import IMAGE_EXTS, iter_images
from .selector import KeepRule, name_penalty, recommend

__all__ = [
    "ActionRecord", "DuplicateGroup", "HashCache", "IMAGE_EXTS", "KeepRule", "MatchKind",
    "PhotoInfo", "Progress", "RemoveMode", "ScanCancelled", "ScanOptions", "ScanResult",
    "UnsafeRemovalError", "default_cache_dir", "default_db_path", "default_log_path",
    "file_sha", "hamming", "image_hashes", "iter_images", "name_penalty", "partial_sha",
    "plan_removal", "read_exif", "read_log", "recommend", "remove", "scan", "undo",
]
