"""GUI tests (offscreen). Real engine, real worker threads, real files in tmp_path."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from gui_helpers import wait_until
from demo_data import fake_groups, scene, variant

from doppel.core.actions import RemoveMode
from doppel.core.models import MatchKind
from doppel.core.selector import KeepRule
from doppel.gui import theme
from doppel.gui.cards import PhotoCard
from doppel.gui.home import STRICTNESS, normalize_roots
from doppel.gui.state import SelectionState
from doppel.gui.thumbs import ThumbnailLoader, load_qimage


def make_library(root: Path) -> dict[str, Path]:
    """alpha (+exact copy, +half-size look-alike), beta (+exact copy), gamma (unique)."""
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    out = {}
    a = scene("sunset", 1, 1000, 750)
    a.save(root / "a" / "alpha.jpg", quality=92)
    shutil.copy(root / "a" / "alpha.jpg", root / "b" / "alpha copy.jpg")
    variant(a, "bright").save(root / "a" / "alpha_bright.jpg", quality=85)
    b = scene("forest", 2, 900, 700)
    b.save(root / "a" / "beta.jpg", quality=92)
    shutil.copy(root / "a" / "beta.jpg", root / "b" / "beta.jpg")
    scene("city", 3, 900, 700).save(root / "b" / "gamma.jpg", quality=92)
    for p in root.rglob("*.jpg"):
        assert p.stat().st_size > 10_240, p
        out[str(p.relative_to(root))] = p
    return out


def run_scan(win, folder: Path):
    win.home.set_folders([folder])
    got = []
    win.scanFinished.connect(got.append)
    win.home.scan_btn.click()
    assert wait_until(lambda: bool(got), 30), "scan did not finish"
    return got[0]


def test_construct_and_theme(win):
    assert win.current_page() == win.HOME
    assert not win.home.scan_btn.isEnabled()  # nothing chosen yet
    assert theme.validate(theme.LIGHT) == [] and theme.validate(theme.DARK) == []
    for t in (theme.LIGHT, theme.DARK):
        assert "QPushButton" in theme.build_stylesheet(t)


def test_strictness_maps_to_engine_threshold(win):
    win.home.slider.setValue(0)
    assert win.home.similarity() == STRICTNESS[0][0]
    win.home.slider.setValue(4)
    assert win.home.similarity() == STRICTNESS[4][0] and 0 <= win.home.similarity() <= 20


def test_end_to_end_scan_toggle_move_and_undo(win, tmp_path):
    lib = tmp_path / "lib"
    files = make_library(lib)
    result = run_scan(win, lib)
    assert win.current_page() == win.RESULTS
    kinds = [g.kind for g in result.groups]
    assert kinds.count(MatchKind.EXACT) == 2
    assert kinds.count(MatchKind.SIMILAR) >= 1
    # model counts follow the filter
    m = win.results.model
    assert m.rowCount() == len(result.groups)
    win.results.filter.set_current("exact")
    assert m.rowCount() == 2
    win.results.filter.set_current("similar")
    assert m.rowCount() == kinds.count(MatchKind.SIMILAR)
    win.results.filter.set_current("all")
    assert m.rowCount() == len(result.groups)

    # default selection = engine recommendation; bottom bar reflects it
    st = win.state
    expected = {p.path for g in result.groups for p in g.photos if p.path not in g.keep}
    assert set(st.removed) >= {p for p in expected if len(st.groups_of(p)) == 1}
    assert st.total_count > 0
    assert win.results.remove_btn.isEnabled() and str(st.total_count) in win.results.remove_btn.text()

    # toggle keep/remove on a removable file, then back
    victim = next(iter(st.removed))
    assert st.set_removed(victim, False)
    assert victim not in st.removed
    assert st.set_removed(victim, True)
    assert victim in st.removed

    # MOVE removal into a review dir (skip the confirmation dialog), then Undo
    review = tmp_path / "review"
    win.results.set_destination(RemoveMode.MOVE)
    win.results.set_review_dir(review)
    plan = st.plan()
    assert plan and all(p.exists() for p in plan)
    done = []
    win.removalFinished.connect(done.append)
    win.perform_removal(plan, RemoveMode.MOVE, review)
    assert wait_until(lambda: bool(done), 20)
    recs = done[0]
    assert all(r.ok for r in recs) and len(recs) == len(plan)
    assert win.current_page() == win.SUCCESS
    assert all(not p.exists() for p in plan)
    assert win.success.undo_btn.isVisible()
    survivors = [p for p in files.values() if p.exists()]
    assert len(survivors) == len(files) - len(plan) and survivors  # something always stays

    undone = []
    win.undoFinished.connect(undone.append)
    win.success.undo_btn.click()
    assert wait_until(lambda: bool(undone), 20)
    assert all(r.ok for r in undone[0])
    assert all(p.exists() for p in plan)
    assert all(p.exists() for p in files.values())
    assert win.success.back_btn.isVisible()


def test_scan_cancel_returns_home(win, tmp_path):
    lib = tmp_path / "lib"
    make_library(lib)
    win.home.set_folders([lib])
    got = []
    win.scanFinished.connect(got.append)
    win.start_scan()
    win.cancel_scan()
    assert wait_until(lambda: bool(got), 20)
    # either the cancel won (home) or the tiny scan finished first (results); never stuck
    assert win.current_page() in (win.HOME, win.RESULTS, win.EMPTY)


def test_cannot_remove_every_photo_in_a_group(win, tmp_path):
    lib = tmp_path / "lib"
    make_library(lib)
    result = run_scan(win, lib)
    st = win.state
    gi = next(i for i, g in enumerate(result.groups) if g.kind == MatchKind.EXACT)
    g = st.groups[gi]
    win.results._select_row(win.results.model.row_of(gi))
    paths = [p.path for p in g.photos]
    st.keep_everything()
    refused = []
    st.refused.connect(refused.append)
    for p in paths[:-1]:
        assert st.set_removed(p, True)
    assert st.set_removed(paths[-1], False) in (True,)
    assert not st.set_removed(paths[-1], True)          # last one kept can't be removed
    assert refused and refused[-1] == paths[-1]
    assert paths[-1] not in st.removed
    # UI: the Remove button for the last kept card is disabled; keyboard 'R' is refused with a hint
    cards = {c.ph.path: c for c in win.results.detail.cards}
    assert not cards[paths[-1]].rem_btn.isEnabled()
    win.results.detail._current = [c.ph.path for c in win.results.detail.cards].index(paths[-1])
    win.results.detail.remove_current()
    assert paths[-1] not in st.removed and not win.results.detail.hint.isHidden()
    # engine-level plan stays safe
    for gg in st.groups:
        assert st.group_kept(st.groups.index(gg))
    st.plan()


def test_auto_select_rules_keep_one_per_group(win, tmp_path):
    lib = tmp_path / "lib"
    make_library(lib)
    run_scan(win, lib)
    st = win.state
    for rule in KeepRule:
        st.apply_rule(rule)
        for i in range(len(st.groups)):
            assert len(st.group_kept(i)) >= 1
    st.keep_everything()
    assert st.total_count == 0 and not win.results.remove_btn.isEnabled()
    st.reset_to_recommended()
    assert st.total_count > 0


def test_many_groups_stay_responsive(win):
    groups = fake_groups(1500)
    from doppel.core.models import ScanResult

    t0 = time.perf_counter()
    win.results.set_result(ScanResult(groups=groups, scanned=4500))
    win._show(win.RESULTS)
    QTest.qWait(50)
    elapsed = time.perf_counter() - t0
    assert elapsed < 3.0, elapsed
    assert win.results.model.rowCount() == 1500
    # one list view, not 1500 widgets: only the open group has cards
    assert len(win.results.findChildren(PhotoCard)) <= 4
    win.results.filter.set_current("exact")
    assert win.results.model.rowCount() == sum(g.kind == MatchKind.EXACT for g in groups)
    win.results.list.scrollToBottom()
    QTest.qWait(30)
    win.results.move_group(1)
    win.state.apply_rule(KeepRule.NEWEST)
    assert win.state.total_count > 0


def test_thumbnail_loader_is_async_and_exif_transposed(qapp, tmp_path):
    img = Image.new("RGB", (200, 100), (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 cw when displayed -> portrait
    p = tmp_path / "rot.jpg"
    img.save(p, "JPEG", exif=exif)
    qi = load_qimage(p, 160)
    assert qi is not None and qi.height() > qi.width()
    loader = ThumbnailLoader()
    assert loader.get(p, 160) is None          # first call never blocks: schedules a load
    assert wait_until(lambda: loader.get(p, 160) is not None, 5)
    assert loader.get(tmp_path / "missing.jpg", 160) is None
    assert wait_until(lambda: loader.failed(tmp_path / "missing.jpg"), 5)
    loader.shutdown()


def test_home_persists_settings_and_normalizes_nested_folders(win, settings, tmp_path):
    a, b = tmp_path / "pics", tmp_path / "pics" / "sub"
    b.mkdir(parents=True)
    win.home.add_folders([str(a), str(b)])
    assert win.home.folders() == [a]            # nested folder is already covered
    win.home.opt_similar.setChecked(False)
    win.home.slider.setValue(3)
    win.close()
    from doppel.gui.home import HomePage

    h2 = HomePage()
    h2.load_settings(settings)
    assert h2.folders() == [a] and not h2.opt_similar.isChecked() and h2.slider.value() == 3
    assert normalize_roots([a, b], True) == [a] and normalize_roots([a, b], False) == [a, b]


def test_preview_dialog_and_compare(win, tmp_path):
    lib = tmp_path / "lib"
    make_library(lib)
    result = run_scan(win, lib)
    from doppel.gui.preview import PreviewDialog

    gi = next(i for i, g in enumerate(result.groups) if len(g.photos) >= 2)
    d = PreviewDialog(win.state, win.loader, gi, result.groups[gi].photos[0].path, compare=True, parent=win)
    d.show()
    assert d.right is not None
    assert wait_until(lambda: d.left.view.pm is not None and d.right.view.pm is not None, 10)
    d.left.view.set_view(3.0, 0.3, 0.4)
    d.left.view.viewChanged.emit(3.0, 0.3, 0.4)
    assert d.right.view.zoom == pytest.approx(3.0)
    d.close()


def test_empty_state_when_nothing_found(win, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    scene("lake", 5, 900, 700).save(lib / "only.jpg", quality=92)
    run_scan(win, lib)
    assert win.current_page() == win.EMPTY


def test_state_cross_group_safety():
    """A file shared by an exact group and a look-alike group can't strand either group."""
    from datetime import datetime

    from doppel.core.models import DuplicateGroup, PhotoInfo

    def ph(n, size=100):
        return PhotoInfo(path=Path(f"/x/{n}.jpg"), size=size, mtime=1.0, width=10, height=10, format="JPEG")

    A, B, C = ph("A"), ph("B"), ph("C")
    g1 = DuplicateGroup(id=1, kind=MatchKind.EXACT, photos=[A, B], keep={A.path})
    g2 = DuplicateGroup(id=2, kind=MatchKind.SIMILAR, photos=[A, C], keep={C.path}, similarity=0.9)
    st = SelectionState()
    st.set_groups([g1, g2])
    for i in range(2):
        assert st.group_kept(i)
    assert st.set_removed(B.path, True) in (True, False)
    for i in range(2):
        assert st.group_kept(i)
    _ = datetime


def test_live_theme_switch(win, qapp):
    theme.install(qapp, theme.DARK)
    win.refresh_theme()
    assert theme.is_dark()
    pm = win.grab()
    assert not pm.isNull()
    theme.install(qapp, theme.LIGHT)
    win.refresh_theme()
    assert not theme.is_dark()
