"""Tests for F13: move_to_bounds clamps coordinates so ≥32px remain on
the virtual screen.

All tests are pure Python / no real Win32. _virtual_screen_rect, _shadow_margins,
SetWindowPos, _get_extended_frame, and _get_window_rect are all monkeypatched.
"""
from __future__ import annotations

import types

import pytest
from ctypes import wintypes

import lib_python_vdesktop.windows as windows_mod


_FAKE_HWND = 555
_SCREEN = {"x": 0, "y": 0, "w": 1920, "h": 1080}
_MIN_VISIBLE = windows_mod._MIN_VISIBLE  # 32


def _make_rect(left=0, top=0, right=0, bottom=0):
    """Return a RECT-like object with the four expected attributes."""
    r = wintypes.RECT()
    r.left = left
    r.top = top
    r.right = right
    r.bottom = bottom
    return r


class _FakeUser32WithCapture:
    """Fake _user32 that records the last SetWindowPos call so _get_window_rect
    can return a matching rect for the read-back in move_to_bounds."""

    def __init__(self):
        self.calls: list[tuple] = []
        self._last_pos = (0, 0, 0, 0)

    def SetWindowPos(self, hwnd, z, x, y, w, h, flags):
        self.calls.append((x, y, w, h))
        self._last_pos = (x, y, w, h)

    def IsIconic(self, hwnd):
        return 0

    def IsZoomed(self, hwnd):
        return 0

    def ShowWindow(self, hwnd, cmd):
        return None

    def GetWindowRect(self, hwnd, rect_ptr):
        return None

    def make_rect_from_last_pos(self):
        x, y, w, h = self._last_pos
        return _make_rect(left=x, top=y, right=x + w, bottom=y + h)


def _fake_user32_setwindowpos():
    """Return a (fake_user32_instance, calls_list) pair.

    The instance records SetWindowPos args; make_rect_from_last_pos() returns
    a rect that move_to_bounds can read back via _get_window_rect.
    """
    ns = _FakeUser32WithCapture()
    return ns, ns.calls


@pytest.fixture(autouse=True)
def patch_shadow_and_screen(monkeypatch):
    """Patch shadow margins to zero, screen to 1920x1080, and _get_extended_frame
    to None so the _get_window_rect fallback path is exercised by all clamp tests."""
    monkeypatch.setattr(windows_mod, "_shadow_margins", lambda hwnd: (0, 0, 0, 0))
    monkeypatch.setattr(windows_mod, "_virtual_screen_rect", lambda: dict(_SCREEN))
    monkeypatch.setattr(windows_mod, "_get_extended_frame", lambda hwnd: None)


# ---------------------------------------------------------------------------
# F13: in-bounds coordinates pass through unchanged
# ---------------------------------------------------------------------------


def test_move_to_bounds_in_bounds_no_clamp(monkeypatch):
    """A position well within the virtual screen must not be clamped."""
    ns, calls = _fake_user32_setwindowpos()
    monkeypatch.setattr(windows_mod, "_user32", ns)
    monkeypatch.setattr(windows_mod, "_get_window_rect",
                        lambda hwnd: ns.make_rect_from_last_pos())

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
    monkeypatch.setattr(windows_mod, "_get_window_rect",
                        lambda hwnd: ns.make_rect_from_last_pos())

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
    monkeypatch.setattr(windows_mod, "_get_window_rect",
                        lambda hwnd: ns.make_rect_from_last_pos())

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
    monkeypatch.setattr(windows_mod, "_get_window_rect",
                        lambda hwnd: ns.make_rect_from_last_pos())

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
    monkeypatch.setattr(windows_mod, "_get_window_rect",
                        lambda hwnd: ns.make_rect_from_last_pos())

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
    monkeypatch.setattr(windows_mod, "_get_window_rect",
                        lambda hwnd: ns.make_rect_from_last_pos())

    w, h = 800, 600
    exact_min_x = _SCREEN["x"] - w + _MIN_VISIBLE
    result = windows_mod.move_to_bounds(_FAKE_HWND, {"x": exact_min_x, "y": 0, "w": w, "h": h})

    assert result["x"] == exact_min_x
