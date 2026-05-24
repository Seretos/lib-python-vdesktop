"""Tests for F13: move_to_bounds clamps coordinates so ≥32px remain on
the virtual screen.

All tests are pure Python / no real Win32. _virtual_screen_rect, _shadow_margins,
and SetWindowPos are all monkeypatched.
"""
from __future__ import annotations

import types

import pytest

import lib_python_vdesktop.windows as windows_mod


_FAKE_HWND = 555
_SCREEN = {"x": 0, "y": 0, "w": 1920, "h": 1080}
_MIN_VISIBLE = windows_mod._MIN_VISIBLE  # 32


def _fake_user32_setwindowpos():
    """Return a fake _user32 namespace with a spy on SetWindowPos."""
    calls: list[tuple] = []
    ns = types.SimpleNamespace()
    ns.SetWindowPos = lambda hwnd, z, x, y, w, h, flags: calls.append((x, y, w, h))
    ns.IsIconic = lambda hwnd: 0
    ns.IsZoomed = lambda hwnd: 0
    ns.ShowWindow = lambda hwnd, cmd: None
    ns.GetWindowRect = lambda hwnd, rect_ptr: None
    return ns, calls


@pytest.fixture(autouse=True)
def patch_shadow_and_screen(monkeypatch):
    """Patch shadow margins to zero and screen to a standard 1920x1080."""
    monkeypatch.setattr(windows_mod, "_shadow_margins", lambda hwnd: (0, 0, 0, 0))
    monkeypatch.setattr(windows_mod, "_virtual_screen_rect", lambda: dict(_SCREEN))


# ---------------------------------------------------------------------------
# F13: in-bounds coordinates pass through unchanged
# ---------------------------------------------------------------------------


def test_move_to_bounds_in_bounds_no_clamp(monkeypatch):
    """A position well within the virtual screen must not be clamped."""
    ns, calls = _fake_user32_setwindowpos()
    monkeypatch.setattr(windows_mod, "_user32", ns)

    result = windows_mod.move_to_bounds(_FAKE_HWND, {"x": 100, "y": 100, "w": 800, "h": 600})

    assert result == {"x": 100, "y": 100, "w": 800, "h": 600}
    assert len(calls) == 1
    # x, y as passed (no clamping)
    assert calls[0][0] == 100  # x
    assert calls[0][1] == 100  # y


# ---------------------------------------------------------------------------
# F13: far-left / far-top negative coordinate clamped
# ---------------------------------------------------------------------------


def test_move_to_bounds_clamps_far_left(monkeypatch):
    """A very negative x (e.g. -2000) must be clamped so ≥32px remain on screen."""
    ns, calls = _fake_user32_setwindowpos()
    monkeypatch.setattr(windows_mod, "_user32", ns)

    w, h = 800, 600
    result = windows_mod.move_to_bounds(_FAKE_HWND, {"x": -2000, "y": 100, "w": w, "h": h})

    # Minimum allowed x: vx - w + 32 = 0 - 800 + 32 = -768
    expected_x = _SCREEN["x"] - w + _MIN_VISIBLE
    assert result["x"] == expected_x
    assert result["y"] == 100  # y not clamped


def test_move_to_bounds_clamps_far_top(monkeypatch):
    """A very negative y (e.g. -3000) must be clamped so ≥32px remain on screen."""
    ns, calls = _fake_user32_setwindowpos()
    monkeypatch.setattr(windows_mod, "_user32", ns)

    w, h = 800, 600
    result = windows_mod.move_to_bounds(_FAKE_HWND, {"x": 100, "y": -3000, "w": w, "h": h})

    expected_y = _SCREEN["y"] - h + _MIN_VISIBLE
    assert result["y"] == expected_y
    assert result["x"] == 100  # x not clamped


# ---------------------------------------------------------------------------
# F13: INT_MAX coordinate clamped to right/bottom edge
# ---------------------------------------------------------------------------


def test_move_to_bounds_int_max_x_clamped(monkeypatch):
    """A very large x (INT_MAX) must be clamped to keep ≥32px on screen."""
    ns, calls = _fake_user32_setwindowpos()
    monkeypatch.setattr(windows_mod, "_user32", ns)

    INT_MAX = 2**31 - 1
    w, h = 800, 600
    result = windows_mod.move_to_bounds(_FAKE_HWND, {"x": INT_MAX, "y": 100, "w": w, "h": h})

    # Maximum allowed x: vx + vw - 32 = 0 + 1920 - 32 = 1888
    expected_x = _SCREEN["x"] + _SCREEN["w"] - _MIN_VISIBLE
    assert result["x"] == expected_x


def test_move_to_bounds_int_max_y_clamped(monkeypatch):
    """A very large y must be clamped to keep ≥32px on screen."""
    ns, calls = _fake_user32_setwindowpos()
    monkeypatch.setattr(windows_mod, "_user32", ns)

    INT_MAX = 2**31 - 1
    w, h = 800, 600
    result = windows_mod.move_to_bounds(_FAKE_HWND, {"x": 100, "y": INT_MAX, "w": w, "h": h})

    expected_y = _SCREEN["y"] + _SCREEN["h"] - _MIN_VISIBLE
    assert result["y"] == expected_y


# ---------------------------------------------------------------------------
# F13: bounds that exactly touch the allowed limits are NOT clamped further
# ---------------------------------------------------------------------------


def test_move_to_bounds_at_min_visible_left_edge_not_over_clamped(monkeypatch):
    """A position exactly at the minimum allowed x must not be changed."""
    ns, calls = _fake_user32_setwindowpos()
    monkeypatch.setattr(windows_mod, "_user32", ns)

    w, h = 800, 600
    exact_min_x = _SCREEN["x"] - w + _MIN_VISIBLE
    result = windows_mod.move_to_bounds(_FAKE_HWND, {"x": exact_min_x, "y": 0, "w": w, "h": h})

    assert result["x"] == exact_min_x
