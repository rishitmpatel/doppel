"""What the user has decided to keep or remove. Pure logic + Qt signals, no widgets.

Removal is tracked per *file path* (not per group): a photo can appear in more than
one group (an exact-copy set is represented by one member inside a look-alike group),
so "can I remove this?" is answered across every group the file belongs to.

Invariant (the safety rule): every group always has at least one member that is NOT
marked for removal.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from doppel.core.models import DuplicateGroup, MatchKind
from doppel.core.selector import KeepRule, recommend


class SelectionState(QObject):
    changed = Signal()                 # anything changed (counts, selection)
    groupsChanged = Signal(object)     # set[int] of group indexes whose rows need repainting
    refused = Signal(object)           # Path that could not be removed (it is the last one kept)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.groups: list[DuplicateGroup] = []
        self._removed: set[Path] = set()
        self._size: dict[Path, int] = {}
        self._member_of: dict[Path, list[int]] = {}
        self._suggested: dict[int, set[Path]] = {}
        self.rule: KeepRule = KeepRule.BEST_QUALITY

    # -- loading ----------------------------------------------------------
    def set_groups(self, groups: list[DuplicateGroup]) -> None:
        self.groups = list(groups)
        self._size.clear()
        self._member_of.clear()
        for i, g in enumerate(self.groups):
            for ph in g.photos:
                self._size[ph.path] = ph.size
                self._member_of.setdefault(ph.path, []).append(i)
        self.rule = KeepRule.BEST_QUALITY
        self.reset_to_recommended()

    # -- queries ----------------------------------------------------------
    def is_removed(self, path: Path) -> bool:
        return path in self._removed

    @property
    def removed(self) -> frozenset[Path]:
        return frozenset(self._removed)

    @property
    def total_count(self) -> int:
        return len(self._removed)

    @property
    def total_bytes(self) -> int:
        return sum(self._size.get(p, 0) for p in self._removed)

    def kept_count(self) -> int:
        """Photos in review that will stay (every file that appears in a group and is not removed)."""
        return len(self._size) - len(self._removed)

    def group_removed(self, idx: int) -> list[Path]:
        return [p.path for p in self.groups[idx].photos if p.path in self._removed]

    def group_removed_bytes(self, idx: int) -> int:
        return sum(p.size for p in self.groups[idx].photos if p.path in self._removed)

    def group_kept(self, idx: int) -> list[Path]:
        return [p.path for p in self.groups[idx].photos if p.path not in self._removed]

    def is_suggested(self, idx: int, path: Path) -> bool:
        return path in self._suggested.get(idx, ())

    def groups_of(self, path: Path) -> list[int]:
        return self._member_of.get(path, [])

    def can_remove(self, path: Path) -> bool:
        """True if marking ``path`` for removal leaves every group with a kept photo."""
        if path in self._removed:
            return True
        for gi in self._member_of.get(path, ()):
            others = [p for p in self.groups[gi].photos if p.path != path and p.path not in self._removed]
            if not others:
                return False
        return True

    # -- mutations --------------------------------------------------------
    def set_removed(self, path: Path, remove: bool) -> bool:
        """Mark/unmark. Returns False (and emits ``refused``) if that would remove a group's last photo."""
        if remove:
            if path in self._removed:
                return True
            if not self.can_remove(path):
                self.refused.emit(path)
                return False
            self._removed.add(path)
        else:
            if path not in self._removed:
                return True
            self._removed.discard(path)
        self.groupsChanged.emit(set(self._member_of.get(path, [])))
        self.changed.emit()
        return True

    def toggle(self, path: Path) -> bool:
        return self.set_removed(path, path not in self._removed)

    def apply_rule(self, rule: KeepRule) -> None:
        """Re-pick which photo to keep in every group using ``rule``."""
        self.rule = rule
        self._suggested = {}
        removed: set[Path] = set()
        for i, g in enumerate(self.groups):
            try:
                keep = set(recommend(g, rule))
            except Exception:
                keep = set(g.keep)
            if not keep:
                keep = set(g.keep) or {g.photos[0].path}
            self._suggested[i] = keep
            removed.update(p.path for p in g.photos if p.path not in keep)
        self._set_all(removed)

    def reset_to_recommended(self) -> None:
        """The engine's own recommendation (``group.keep``) for every group."""
        self.rule = KeepRule.BEST_QUALITY
        self._suggested = {}
        removed: set[Path] = set()
        for i, g in enumerate(self.groups):
            keep = set(g.keep) or {g.photos[0].path}
            self._suggested[i] = keep
            removed.update(p.path for p in g.photos if p.path not in keep)
        self._set_all(removed)

    def keep_everything(self) -> None:
        self._set_all(set())

    def _set_all(self, removed: set[Path]) -> None:
        self._removed = removed
        self._enforce_safety()
        self.groupsChanged.emit(set(range(len(self.groups))))
        self.changed.emit()

    def _enforce_safety(self) -> None:
        """If overlapping groups left some group with nothing kept, un-remove its suggested/first photo."""
        for i, g in enumerate(self.groups):
            if all(p.path in self._removed for p in g.photos):
                sug = self._suggested.get(i) or set(g.keep)
                restore = [p.path for p in g.photos if p.path in sug] or [g.photos[0].path]
                self._removed.discard(restore[0])

    # -- hand-off to the engine ------------------------------------------
    def plan(self) -> list[Path]:
        """Paths to remove, validated by the engine's ``plan_removal`` safety check.

        Raises ValueError (``UnsafeRemovalError``) if any group would lose every photo.
        """
        for i in range(len(self.groups)):
            if not self.group_kept(i):
                raise ValueError("Every photo in a group was marked for removal; at least one must be kept.")
        from doppel.core.actions import plan_removal

        planned = plan_removal(self.groups, remove=set(self._removed))
        return sorted((Path(p) for p in planned), key=lambda p: str(p).lower())

    def counts_by_kind(self) -> dict[MatchKind, int]:
        out: dict[MatchKind, int] = {k: 0 for k in MatchKind}
        for g in self.groups:
            out[g.kind] += 1
        return out
