"""Tests for U6: fill_layout_impl — assign windows to layout slots in order.

All tests are pure Python / no Win32 / no COM.  apply_layout_impl and
windows.move_window_impl are monkeypatched so the test is deterministic.
"""
from __future__ import annotations

from typing import Optional

import pytest

import lib_python_vdesktop.layouts as layouts_mod
import lib_python_vdesktop.windows as windows_mod
from lib_python_vdesktop.tracking import Registry


# ---------------------------------------------------------------------------
# Fake slot helpers
# ---------------------------------------------------------------------------

def _slot(slot_id: str, x: int = 0, y: int = 0, w: int = 100, h: int = 100) -> dict:
    return {
        "slot_id": slot_id,
        "monitor": 0,
        "bounds": {"x": x, "y": y, "w": w, "h": h},
    }


_TWO_SLOTS = [
    _slot("left",  x=0,    w=960, h=1080),
    _slot("right", x=960,  w=960, h=1080),
]

_THREE_SLOTS = [
    _slot("left",   x=0,    w=640, h=1080),
    _slot("center", x=640,  w=640, h=1080),
    _slot("right",  x=1280, w=640, h=1080),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_registry(monkeypatch):
    r = Registry()
    monkeypatch.setattr(windows_mod, "REGISTRY", r)
    # Ensure layouts module's windows import also sees the same registry.
    # fill_layout_impl does `from . import windows as windows_mod` lazily;
    # monkeypatching windows_mod.REGISTRY is sufficient.
    return r


def _patch_apply_layout(monkeypatch, slots: list[dict]):
    """Replace apply_layout_impl with a function that returns fixed slots."""

    def fake_apply(spec, target_desktop=None):
        return list(slots)

    monkeypatch.setattr(layouts_mod, "apply_layout_impl", fake_apply)


def _patch_move_window(monkeypatch, registry: Registry) -> list[dict]:
    """Replace move_window_impl with a spy that records calls and returns
    the slot's bounds from the registry lookup.  Returns the call log."""
    call_log: list[dict] = []

    def fake_move(handle_id: str, target: dict) -> dict:
        slot_id = target.get("slot", "unknown")
        call_log.append({"handle_id": handle_id, "slot": slot_id})
        # Simulate the bounds that would be returned for that slot.
        bounds = {"x": 0, "y": 0, "w": 100, "h": 100}
        return {"handle_id": handle_id, "bounds": bounds, "desktop_guid": None}

    monkeypatch.setattr(windows_mod, "move_window_impl", fake_move)
    return call_log


# ---------------------------------------------------------------------------
# U6: happy path — slots assigned in order
# ---------------------------------------------------------------------------


def test_fill_layout_assigns_slots_in_order(monkeypatch, isolated_registry):
    """handle_ids[0] → left slot, handle_ids[1] → right slot."""
    tw0 = isolated_registry.register(hwnd=10, pid=1, app_type="test")
    tw1 = isolated_registry.register(hwnd=11, pid=2, app_type="test")

    _patch_apply_layout(monkeypatch, _TWO_SLOTS)
    call_log = _patch_move_window(monkeypatch, isolated_registry)

    result = layouts_mod.fill_layout_impl(
        [tw0.handle_id, tw1.handle_id],
        {"type": "preset", "name": "two-columns"},
    )

    assert len(result) == 2
    assert result[0]["handle_id"] == tw0.handle_id
    assert result[0]["slot_id"] == "left"
    assert result[1]["handle_id"] == tw1.handle_id
    assert result[1]["slot_id"] == "right"

    assert call_log[0] == {"handle_id": tw0.handle_id, "slot": "left"}
    assert call_log[1] == {"handle_id": tw1.handle_id, "slot": "right"}


# ---------------------------------------------------------------------------
# U6: excess handle_ids left unmoved
# ---------------------------------------------------------------------------


def test_fill_layout_excess_handle_ids_left_unmoved(monkeypatch, isolated_registry):
    """When more handle_ids than slots, excess windows are silently skipped."""
    tw0 = isolated_registry.register(hwnd=20, pid=1, app_type="test")
    tw1 = isolated_registry.register(hwnd=21, pid=2, app_type="test")
    tw2 = isolated_registry.register(hwnd=22, pid=3, app_type="test")

    # Only 2 slots, but 3 handle_ids.
    _patch_apply_layout(monkeypatch, _TWO_SLOTS)
    call_log = _patch_move_window(monkeypatch, isolated_registry)

    result = layouts_mod.fill_layout_impl(
        [tw0.handle_id, tw1.handle_id, tw2.handle_id],
        {"type": "preset", "name": "two-columns"},
    )

    # Only the first 2 windows are placed.
    assert len(result) == 2
    assert len(call_log) == 2
    moved_ids = {r["handle_id"] for r in result}
    assert tw2.handle_id not in moved_ids


# ---------------------------------------------------------------------------
# U6: fewer handle_ids than slots — excess slots silently skipped
# ---------------------------------------------------------------------------


def test_fill_layout_fewer_handle_ids_than_slots(monkeypatch, isolated_registry):
    """When more slots than handle_ids, only placed windows appear in result."""
    tw0 = isolated_registry.register(hwnd=30, pid=1, app_type="test")

    # 3 slots, but only 1 handle_id.
    _patch_apply_layout(monkeypatch, _THREE_SLOTS)
    call_log = _patch_move_window(monkeypatch, isolated_registry)

    result = layouts_mod.fill_layout_impl(
        [tw0.handle_id],
        {"type": "preset", "name": "three-columns"},
    )

    assert len(result) == 1
    assert result[0]["handle_id"] == tw0.handle_id
    assert result[0]["slot_id"] == "left"
    assert len(call_log) == 1


# ---------------------------------------------------------------------------
# U6: result contains 'bounds' from move_window_impl
# ---------------------------------------------------------------------------


def test_fill_layout_result_contains_bounds(monkeypatch, isolated_registry):
    """Each result entry must have 'handle_id', 'slot_id', and 'bounds' keys."""
    tw0 = isolated_registry.register(hwnd=40, pid=1, app_type="test")

    _patch_apply_layout(monkeypatch, [_slot("full")])
    _patch_move_window(monkeypatch, isolated_registry)

    result = layouts_mod.fill_layout_impl(
        [tw0.handle_id],
        {"type": "preset", "name": "fullscreen"},
    )

    assert len(result) == 1
    entry = result[0]
    assert "handle_id" in entry
    assert "slot_id" in entry
    assert "bounds" in entry


# ---------------------------------------------------------------------------
# U6: empty handle_ids list
# ---------------------------------------------------------------------------


def test_fill_layout_empty_handle_ids(monkeypatch, isolated_registry):
    """An empty handle_ids list must return an empty result without errors."""
    _patch_apply_layout(monkeypatch, _TWO_SLOTS)
    _patch_move_window(monkeypatch, isolated_registry)

    result = layouts_mod.fill_layout_impl([], {"type": "preset", "name": "two-columns"})
    assert result == []
