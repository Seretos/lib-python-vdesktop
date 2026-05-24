"""Tests for the bounds-fallback behaviour in launchers/_common.py.

When no slot is provided, launch_and_register must read the window's actual
Win32 bounds rather than returning None.  All tests are pure Python / no real
process spawning — _spawn_phase, _resolve_hwnd_phase, _placement_phase, and
get_window_rect are all monkeypatched.
"""
from __future__ import annotations

import types
from typing import Optional
from unittest.mock import MagicMock

import pytest

import lib_python_vdesktop.launchers._common as common_mod
from lib_python_vdesktop.tracking import Registry


# ---------------------------------------------------------------------------
# Constants shared across tests
# ---------------------------------------------------------------------------

_FAKE_HWND = 999
_FAKE_PID = 1234
_FAKE_GUID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
_FAKE_BOUNDS = {"x": 10, "y": 20, "w": 800, "h": 600}


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _fake_proc(pid: int = _FAKE_PID):
    """Minimal subprocess.Popen look-alike."""
    p = types.SimpleNamespace()
    p.pid = pid
    return p


@pytest.fixture
def isolated_registry(monkeypatch):
    """Fresh Registry injected into _common_mod so tests don't share state."""
    r = Registry()
    monkeypatch.setattr(common_mod, "REGISTRY", r)
    return r


def _patch_phases(monkeypatch, *, applied_bounds: Optional[dict]):
    """Monkeypatch _spawn_phase, _resolve_hwnd_phase, _placement_phase, and
    get_window_title so launch_and_register can run without real Win32."""
    monkeypatch.setattr(
        common_mod,
        "_spawn_phase",
        lambda *a, **kw: (_fake_proc(), set()),
    )
    monkeypatch.setattr(
        common_mod,
        "_resolve_hwnd_phase",
        lambda *a, **kw: _FAKE_HWND,
    )
    monkeypatch.setattr(
        common_mod,
        "_placement_phase",
        lambda hwnd, *, desktop, slot: (_FAKE_GUID, applied_bounds),
    )
    monkeypatch.setattr(
        common_mod,
        "get_window_title",
        lambda hwnd: "Fake Window",
    )


# ---------------------------------------------------------------------------
# Regression: slot=None → bounds must not be None (regression for the bug)
# ---------------------------------------------------------------------------


def test_no_slot_bounds_populated_from_get_window_rect(monkeypatch, isolated_registry):
    """When slot=None and _placement_phase returns applied_bounds=None,
    get_window_rect is called and its result appears in the returned bounds."""
    _patch_phases(monkeypatch, applied_bounds=None)
    monkeypatch.setattr(common_mod, "get_window_rect", lambda hwnd: _FAKE_BOUNDS)

    result = common_mod.launch_and_register(
        args=["fake.exe"],
        app_type="test",
        slot=None,
    )
    assert result["bounds"] == _FAKE_BOUNDS, (
        "bounds must be populated from get_window_rect when no slot is given"
    )


# ---------------------------------------------------------------------------
# OSError in get_window_rect → bounds stays None (non-fatal)
# ---------------------------------------------------------------------------


def test_no_slot_bounds_none_when_get_window_rect_raises(monkeypatch, isolated_registry):
    """When get_window_rect raises OSError, bounds must be None — not a crash."""
    _patch_phases(monkeypatch, applied_bounds=None)

    def bad_rect(hwnd):
        raise OSError("access denied")

    monkeypatch.setattr(common_mod, "get_window_rect", bad_rect)

    result = common_mod.launch_and_register(
        args=["fake.exe"],
        app_type="test",
        slot=None,
    )
    assert result["bounds"] is None, (
        "bounds must be None when get_window_rect raises OSError"
    )


# ---------------------------------------------------------------------------
# Slot provided → get_window_rect must NOT be called
# ---------------------------------------------------------------------------


def test_slot_provided_get_window_rect_not_called(monkeypatch, isolated_registry):
    """When a slot is given and _placement_phase returns non-None applied_bounds,
    get_window_rect must not be invoked — it's not needed."""
    slot_bounds = {"x": 0, "y": 0, "w": 1920, "h": 1080}
    _patch_phases(monkeypatch, applied_bounds=slot_bounds)

    call_count = []

    def spy_rect(hwnd):
        call_count.append(hwnd)
        return {"x": 999, "y": 999, "w": 1, "h": 1}

    monkeypatch.setattr(common_mod, "get_window_rect", spy_rect)

    result = common_mod.launch_and_register(
        args=["fake.exe"],
        app_type="test",
        slot="left",
    )
    assert call_count == [], "get_window_rect must not be called when slot bounds are set"
    assert result["bounds"] == slot_bounds


# ---------------------------------------------------------------------------
# Verify bounds propagate correctly to registry and result
# ---------------------------------------------------------------------------


def test_no_slot_bounds_stored_in_registry(monkeypatch, isolated_registry):
    """The fallback bounds must be stored in the registry entry, not just the result."""
    _patch_phases(monkeypatch, applied_bounds=None)
    monkeypatch.setattr(common_mod, "get_window_rect", lambda hwnd: _FAKE_BOUNDS)

    result = common_mod.launch_and_register(
        args=["fake.exe"],
        app_type="test",
    )
    handle_id = result["handle_id"]
    tw = isolated_registry.get(handle_id)
    assert tw is not None
    assert tw.bounds == _FAKE_BOUNDS
