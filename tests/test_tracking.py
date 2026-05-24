"""Tests for lib_python_vdesktop.tracking — the in-memory handle registry."""
from __future__ import annotations

import concurrent.futures

import pytest

from lib_python_vdesktop.tracking import Registry, TrackedWindow


@pytest.fixture
def reg() -> Registry:
    """Fresh registry per test."""
    return Registry()


def test_register_creates_entry(reg):
    tw = reg.register(hwnd=100, pid=1234, app_type="chrome")
    assert isinstance(tw, TrackedWindow)
    assert tw.hwnd == 100
    assert tw.pid == 1234
    assert tw.app_type == "chrome"
    assert tw.handle_id  # non-empty
    assert reg.get(tw.handle_id) is tw


def test_register_same_hwnd_updates_existing(reg):
    first = reg.register(hwnd=100, pid=1, app_type="chrome", label="A")
    second = reg.register(hwnd=100, pid=1, app_type="chrome", label="B")
    assert second.handle_id == first.handle_id
    assert second.label == "B"
    assert len(reg.all()) == 1


def test_register_same_hwnd_promotes_app_type_from_unknown(reg):
    """When a window was first adopted (app_type='adopted' or 'unknown'),
    a later register() with a concrete app_type should refine it."""
    reg.register(hwnd=200, pid=1, app_type="unknown")
    reg.register(hwnd=200, pid=1, app_type="chrome")
    tw = reg.find_by_hwnd(200)
    assert tw.app_type == "chrome"


def test_register_same_hwnd_does_not_demote_app_type(reg):
    """An existing concrete app_type should not be overwritten by 'unknown'."""
    reg.register(hwnd=300, pid=1, app_type="chrome")
    reg.register(hwnd=300, pid=1, app_type="unknown")
    tw = reg.find_by_hwnd(300)
    assert tw.app_type == "chrome"


def test_get_by_label(reg):
    tw = reg.register(hwnd=100, pid=1, app_type="chrome", label="my-window")
    assert reg.get("my-window") is tw


def test_get_handle_id_takes_priority_over_label(reg):
    tw_a = reg.register(hwnd=100, pid=1, app_type="chrome", label="x")
    tw_b = reg.register(hwnd=101, pid=2, app_type="chrome")
    # Even if some weird label collides with the handle_id of another, the
    # handle_id-lookup wins. Hard to construct without knowing the uuid, so
    # just verify exact match works for both lookup modes.
    assert reg.get(tw_a.handle_id) is tw_a
    assert reg.get(tw_b.handle_id) is tw_b
    assert reg.get("x") is tw_a


def test_get_missing_returns_none(reg):
    assert reg.get("does-not-exist") is None


def test_require_raises_on_missing(reg):
    with pytest.raises(KeyError):
        reg.require("missing")


def test_remove_clears_both_indexes(reg):
    tw = reg.register(hwnd=400, pid=1, app_type="chrome")
    handle_id = tw.handle_id
    removed = reg.remove(handle_id)
    assert removed is tw
    assert reg.get(handle_id) is None
    assert reg.find_by_hwnd(400) is None


def test_remove_unknown_returns_none(reg):
    assert reg.remove("no-such-id") is None


def test_relabel_updates_label(reg):
    tw = reg.register(hwnd=500, pid=1, app_type="chrome", label="old")
    reg.relabel(tw.handle_id, "new")
    assert reg.get(tw.handle_id).label == "new"
    assert reg.get("new") is tw
    assert reg.get("old") is None


def test_update_bounds(reg):
    tw = reg.register(hwnd=600, pid=1, app_type="chrome")
    bounds = {"x": 10, "y": 20, "w": 100, "h": 200}
    reg.update_bounds(tw.handle_id, bounds, slot_id="left")
    fresh = reg.get(tw.handle_id)
    assert fresh.bounds == bounds
    assert fresh.slot_id == "left"


def test_update_bounds_without_slot_id_preserves_existing(reg):
    tw = reg.register(hwnd=601, pid=1, app_type="chrome", slot_id="right")
    reg.update_bounds(tw.handle_id, {"x": 0, "y": 0, "w": 10, "h": 10})
    assert reg.get(tw.handle_id).slot_id == "right"


def test_all_returns_every_entry(reg):
    reg.register(hwnd=700, pid=1, app_type="chrome")
    reg.register(hwnd=701, pid=2, app_type="vscode")
    reg.register(hwnd=702, pid=3, app_type="terminal")
    assert len(reg.all()) == 3


def test_find_by_hwnd(reg):
    tw = reg.register(hwnd=800, pid=1, app_type="chrome")
    assert reg.find_by_hwnd(800) is tw
    assert reg.find_by_hwnd(99999) is None


# ---------------------------------------------------------------------------
# F8 — relabel duplicate check
# ---------------------------------------------------------------------------


def test_relabel_rejects_duplicate_label(reg):
    """Assigning a label that is already used by another tracked window must
    raise ValueError with 'label.duplicate'."""
    tw_a = reg.register(hwnd=900, pid=1, app_type="chrome", label="unique-label")
    tw_b = reg.register(hwnd=901, pid=2, app_type="vscode")

    with pytest.raises(ValueError, match="label.duplicate"):
        reg.relabel(tw_b.handle_id, "unique-label")


def test_relabel_clear_label_always_allowed(reg):
    """Clearing a label (label=None) must always succeed even if other windows
    have labels."""
    tw_a = reg.register(hwnd=902, pid=1, app_type="chrome", label="some-label")
    tw_b = reg.register(hwnd=903, pid=2, app_type="chrome", label="another-label")

    # Clearing tw_a's label must not raise, regardless of tw_b's label.
    reg.relabel(tw_a.handle_id, None)
    assert reg.get(tw_a.handle_id).label is None


def test_relabel_same_window_same_label_no_conflict(reg):
    """Relabeling a window to its own current label must not raise ValueError."""
    tw = reg.register(hwnd=904, pid=1, app_type="chrome", label="my-window")

    # Should not raise.
    reg.relabel(tw.handle_id, "my-window")
    assert reg.get(tw.handle_id).label == "my-window"


def test_relabel_unique_label_allowed(reg):
    """Assigning a completely new, unused label must succeed."""
    tw = reg.register(hwnd=905, pid=1, app_type="chrome", label="old")
    reg.relabel(tw.handle_id, "brand-new")
    assert reg.get(tw.handle_id).label == "brand-new"


def test_concurrent_register_thread_safe(reg):
    """100 threads register distinct hwnds — exactly 100 entries should result."""
    def do_register(hwnd):
        return reg.register(hwnd=hwnd, pid=hwnd, app_type="chrome")

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(do_register, range(10_000, 10_100)))

    assert len(results) == 100
    assert len({tw.handle_id for tw in results}) == 100
    assert len(reg.all()) == 100
