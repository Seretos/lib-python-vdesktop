"""Tests for the _window_state helper and the 'state' field in list_windows_impl.

All tests are pure Python / no COM / no real ctypes — _user32 is monkeypatched
with a minimal namespace so nothing actually talks to Win32.
"""
from __future__ import annotations

import types
from typing import Optional

import pytest

import lib_python_vdesktop.windows as windows_mod
from lib_python_vdesktop.tracking import Registry


# ---------------------------------------------------------------------------
# Helpers — fake _user32 that controls IsIconic / IsZoomed return values
# ---------------------------------------------------------------------------

def _fake_user32(*, is_iconic: int = 0, is_zoomed: int = 0) -> types.SimpleNamespace:
    ns = types.SimpleNamespace()
    ns.IsIconic = lambda hwnd: is_iconic
    ns.IsZoomed = lambda hwnd: is_zoomed
    # These are called by ShowWindow, SetWindowPos, GetWindowRect, etc.
    # Provide no-op stubs so monkeypatched tests that exercise more code paths
    # don't crash.
    ns.ShowWindow = lambda hwnd, cmd: None
    ns.SetWindowPos = lambda *a: None
    ns.GetWindowRect = lambda hwnd, rect_ptr: None
    ns.GetWindowTextW = lambda hwnd, buf, size: None
    ns.SetForegroundWindow = lambda hwnd: None
    ns.PostMessageW = lambda *a: None
    return ns


_FAKE_HWND = 42
_FAKE_PID = 7


# ---------------------------------------------------------------------------
# _window_state unit tests
# ---------------------------------------------------------------------------


def test_window_state_minimized(monkeypatch):
    """IsIconic non-zero → 'minimized', regardless of IsZoomed."""
    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=1, is_zoomed=1))
    assert windows_mod._window_state(_FAKE_HWND) == "minimized"


def test_window_state_minimized_zoomed_zero(monkeypatch):
    """IsIconic non-zero, IsZoomed zero → still 'minimized'."""
    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=1, is_zoomed=0))
    assert windows_mod._window_state(_FAKE_HWND) == "minimized"


def test_window_state_maximized(monkeypatch):
    """IsIconic 0, IsZoomed non-zero → 'maximized'."""
    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=0, is_zoomed=1))
    assert windows_mod._window_state(_FAKE_HWND) == "maximized"


def test_window_state_restored(monkeypatch):
    """Both IsIconic and IsZoomed return 0 → 'restored'."""
    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=0, is_zoomed=0))
    assert windows_mod._window_state(_FAKE_HWND) == "restored"


# ---------------------------------------------------------------------------
# list_windows_impl includes 'state' key
# ---------------------------------------------------------------------------


def _make_rect(left=0, top=0, right=100, bottom=100):
    """Return a RECT-like object with the four expected attributes."""

    class FakeRect:
        pass

    r = FakeRect()
    r.left = left
    r.top = top
    r.right = right
    r.bottom = bottom
    return r


@pytest.fixture
def isolated_registry(monkeypatch):
    """Inject a fresh Registry into windows_mod and desktops_mod so each test
    is fully isolated from REGISTRY state leaking between tests."""
    import lib_python_vdesktop.desktops as desktops_mod

    r = Registry()
    monkeypatch.setattr(windows_mod, "REGISTRY", r)
    monkeypatch.setattr(desktops_mod, "REGISTRY", r)
    return r


def test_list_windows_has_state_key(monkeypatch, isolated_registry):
    """list_windows_impl must include 'state' in every window entry."""
    import lib_python_vdesktop.desktops as desktops_mod

    # Register a window.
    isolated_registry.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")

    # Fake _user32 — restored window.
    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=0, is_zoomed=0))

    # Fake _get_window_rect to return a predictable rect.
    monkeypatch.setattr(windows_mod, "_get_window_rect", lambda hwnd: _make_rect())

    # Fake _win32_helpers.get_window_title (imported into windows_mod as get_window_title).
    monkeypatch.setattr(windows_mod, "get_window_title", lambda hwnd: "Test Window")

    # Disable pyvda so pin_state_for_hwnd returns (None, None) cleanly.
    monkeypatch.setattr(desktops_mod, "pyvda", None)

    result = windows_mod.list_windows_impl()
    assert len(result) == 1
    entry = result[0]
    assert "state" in entry, "list_windows_impl entry must contain 'state' key"


def test_list_windows_state_value_restored(monkeypatch, isolated_registry):
    """list_windows_impl returns 'restored' when both IsIconic and IsZoomed are 0."""
    import lib_python_vdesktop.desktops as desktops_mod

    isolated_registry.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")

    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=0, is_zoomed=0))
    monkeypatch.setattr(windows_mod, "_get_window_rect", lambda hwnd: _make_rect())
    monkeypatch.setattr(windows_mod, "get_window_title", lambda hwnd: "T")
    monkeypatch.setattr(desktops_mod, "pyvda", None)

    result = windows_mod.list_windows_impl()
    assert result[0]["state"] == "restored"


def test_list_windows_state_value_minimized(monkeypatch, isolated_registry):
    """list_windows_impl returns 'minimized' when IsIconic is non-zero."""
    import lib_python_vdesktop.desktops as desktops_mod

    isolated_registry.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")

    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=1, is_zoomed=0))
    monkeypatch.setattr(windows_mod, "_get_window_rect", lambda hwnd: _make_rect())
    monkeypatch.setattr(windows_mod, "get_window_title", lambda hwnd: "T")
    monkeypatch.setattr(desktops_mod, "pyvda", None)

    result = windows_mod.list_windows_impl()
    assert result[0]["state"] == "minimized"


def test_list_windows_state_fallback_none_on_oserror(monkeypatch, isolated_registry):
    """When _get_window_rect raises OSError, 'state' must be None (graceful fallback)."""
    import lib_python_vdesktop.desktops as desktops_mod

    isolated_registry.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")

    # _get_window_rect raises — state must fall back to None.
    def bad_rect(hwnd):
        raise OSError("no such window")

    monkeypatch.setattr(windows_mod, "_get_window_rect", bad_rect)
    monkeypatch.setattr(windows_mod, "_user32", _fake_user32())
    monkeypatch.setattr(windows_mod, "get_window_title", lambda hwnd: "T")
    monkeypatch.setattr(desktops_mod, "pyvda", None)

    result = windows_mod.list_windows_impl()
    assert result[0]["state"] is None, (
        "state must be None when Win32 call raises OSError"
    )


# ---------------------------------------------------------------------------
# Consistency: minimize_window_impl state matches _window_state
# ---------------------------------------------------------------------------


def test_minimize_window_impl_state_uses_window_state(monkeypatch):
    """minimize_window_impl's returned 'state' comes from _window_state, not a
    hard-coded string — so if ShowWindow fails silently the state is accurate."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    # Simulate a window that is already minimized and reports so.
    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=1, is_zoomed=0))

    result = windows_mod.minimize_window_impl(tw.handle_id)
    assert result["state"] == windows_mod._window_state(_FAKE_HWND)


def test_maximize_window_impl_state_uses_window_state(monkeypatch):
    """maximize_window_impl's state is consistent with _window_state."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=0, is_zoomed=1))

    result = windows_mod.maximize_window_impl(tw.handle_id)
    assert result["state"] == "maximized"


def test_restore_window_impl_state_uses_window_state(monkeypatch):
    """restore_window_impl's state is consistent with _window_state."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=0, is_zoomed=0))

    result = windows_mod.restore_window_impl(tw.handle_id)
    assert result["state"] == "restored"


# ---------------------------------------------------------------------------
# U2: focus_window_impl returns resolved_handle_id
# ---------------------------------------------------------------------------


def test_focus_window_impl_resolved_handle_id_equals_input_when_canonical(monkeypatch):
    """When handle_id is the canonical handle_id (not a label), resolved_handle_id
    must equal handle_id."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)
    monkeypatch.setattr(windows_mod, "_user32", _fake_user32())
    # Stub focus_window_hwnd to avoid real Win32 calls.
    monkeypatch.setattr(windows_mod, "focus_window_hwnd", lambda hwnd: None)

    result = windows_mod.focus_window_impl(tw.handle_id)

    assert result["focused"] is True
    assert "resolved_handle_id" in result, "focus_window_impl must return resolved_handle_id"
    assert result["resolved_handle_id"] == tw.handle_id
    assert result["handle_id"] == tw.handle_id


def test_focus_window_impl_returns_resolved_handle_id_for_label_lookup(monkeypatch):
    """When the caller uses a label, handle_id in the result is the label (input),
    while resolved_handle_id is the canonical handle_id from the registry."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test", label="my-win")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)
    monkeypatch.setattr(windows_mod, "_user32", _fake_user32())
    monkeypatch.setattr(windows_mod, "focus_window_hwnd", lambda hwnd: None)

    result = windows_mod.focus_window_impl("my-win")

    assert result["focused"] is True
    assert result["handle_id"] == "my-win"          # the input as-given
    assert result["resolved_handle_id"] == tw.handle_id  # the canonical ID


# ---------------------------------------------------------------------------
# U3: get_window_impl
# ---------------------------------------------------------------------------


def test_get_window_impl_returns_dict(monkeypatch):
    """get_window_impl must return a dict with the expected fields."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    result = windows_mod.get_window_impl(tw.handle_id)

    assert isinstance(result, dict)
    assert result["handle_id"] == tw.handle_id
    assert result["hwnd"] == _FAKE_HWND
    assert result["pid"] == _FAKE_PID
    assert result["app_type"] == "test"


def test_get_window_impl_label_resolution(monkeypatch):
    """get_window_impl must resolve by label as well as by handle_id."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test", label="my-label")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    result = windows_mod.get_window_impl("my-label")

    assert result["handle_id"] == tw.handle_id
    assert result["label"] == "my-label"


def test_get_window_impl_missing_raises_key_error(monkeypatch):
    """get_window_impl must raise KeyError when the handle/label is not tracked."""
    r = Registry()
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    with pytest.raises(KeyError):
        windows_mod.get_window_impl("does-not-exist")
