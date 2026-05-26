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

    # Force fallback path: _get_extended_frame returns None so _get_window_rect is used.
    monkeypatch.setattr(windows_mod, "_get_extended_frame", lambda hwnd: None)
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
    monkeypatch.setattr(windows_mod, "_get_extended_frame", lambda hwnd: None)
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
    monkeypatch.setattr(windows_mod, "_get_extended_frame", lambda hwnd: None)
    monkeypatch.setattr(windows_mod, "_get_window_rect", lambda hwnd: _make_rect())
    monkeypatch.setattr(windows_mod, "get_window_title", lambda hwnd: "T")
    monkeypatch.setattr(desktops_mod, "pyvda", None)

    result = windows_mod.list_windows_impl()
    assert result[0]["state"] == "minimized"


def test_list_windows_state_fallback_none_on_oserror(monkeypatch, isolated_registry):
    """When _get_window_rect raises OSError, 'state' must be None (graceful fallback).

    _get_extended_frame returns None (forcing the fallback to _get_window_rect), which
    then raises OSError — confirming the outer except OSError catches it.
    """
    import lib_python_vdesktop.desktops as desktops_mod

    isolated_registry.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")

    # _get_extended_frame returns None → fallback; _get_window_rect raises OSError.
    monkeypatch.setattr(windows_mod, "_get_extended_frame", lambda hwnd: None)

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


# ---------------------------------------------------------------------------
# resize_window_impl: maximized-flag clearing (ticket #14 regression tests)
# ---------------------------------------------------------------------------


def _fake_user32_stateful(
    *,
    is_iconic: int = 0,
    is_zoomed_initial: int = 0,
) -> tuple[types.SimpleNamespace, list]:
    """Return (fake_user32, show_window_calls).

    show_window_calls records every (hwnd, cmd) pair passed to ShowWindow.
    IsZoomed returns is_zoomed_initial until SW_SHOWNOACTIVATE (4) is recorded
    in show_window_calls, then returns 0.  This lets tests verify that the guard
    in resize_window_impl actually clears the maximized flag before moving.
    """
    show_window_calls: list = []

    ns = types.SimpleNamespace()
    ns.IsIconic = lambda hwnd: is_iconic

    def is_zoomed(hwnd):
        # Once SW_SHOWNOACTIVATE has been called, report 0.
        sw_shownoactivate_called = any(cmd == windows_mod.SW_SHOWNOACTIVATE for _, cmd in show_window_calls)
        return 0 if sw_shownoactivate_called else is_zoomed_initial

    def show_window(hwnd, cmd):
        show_window_calls.append((hwnd, cmd))

    ns.IsZoomed = is_zoomed
    ns.ShowWindow = show_window
    ns.SetWindowPos = lambda *a: None
    ns.GetWindowRect = lambda hwnd, rect_ptr: None
    ns.GetWindowTextW = lambda hwnd, buf, size: None
    ns.SetForegroundWindow = lambda hwnd: None
    ns.PostMessageW = lambda *a: None
    return ns, show_window_calls


_BOUNDS = {"x": 10, "y": 20, "w": 800, "h": 600}


def test_resize_window_impl_clears_maximized_flag(monkeypatch):
    """Regression (#14): resize_window_impl must call SW_SHOWNOACTIVATE before
    moving when the window is maximized, so IsZoomed is 0 after the call."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    fake_u32, show_window_calls = _fake_user32_stateful(is_iconic=0, is_zoomed_initial=1)
    monkeypatch.setattr(windows_mod, "_user32", fake_u32)

    # Stub move_to_bounds to avoid _shadow_margins / _virtual_screen_rect round-trips.
    monkeypatch.setattr(windows_mod, "move_to_bounds", lambda hwnd, bounds: dict(bounds))

    result = windows_mod.resize_window_impl(tw.handle_id, _BOUNDS)

    # SW_SHOWNOACTIVATE must have been called.
    assert any(cmd == windows_mod.SW_SHOWNOACTIVATE for _, cmd in show_window_calls), (
        "resize_window_impl must call ShowWindow(SW_SHOWNOACTIVATE) when window is maximized"
    )

    # After the call, _window_state must report 'restored' (IsZoomed now 0).
    assert windows_mod._window_state(tw.hwnd) == "restored"

    # Return shape is unchanged.
    assert result["handle_id"] == tw.handle_id
    assert "bounds" in result


def test_resize_window_impl_already_restored_no_show_window_call(monkeypatch):
    """When the window is already restored (IsZoomed=0), ShowWindow must NOT be called."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    fake_u32, show_window_calls = _fake_user32_stateful(is_iconic=0, is_zoomed_initial=0)
    monkeypatch.setattr(windows_mod, "_user32", fake_u32)
    monkeypatch.setattr(windows_mod, "move_to_bounds", lambda hwnd, bounds: dict(bounds))

    result = windows_mod.resize_window_impl(tw.handle_id, _BOUNDS)

    assert show_window_calls == [], (
        "resize_window_impl must not call ShowWindow when window is already restored"
    )
    assert result["handle_id"] == tw.handle_id
    assert "bounds" in result


def test_resize_window_impl_minimized_no_show_window_call(monkeypatch):
    """When IsIconic=1 (minimized, not maximized), resize_window_impl must NOT
    call ShowWindow — restoring a minimized window may re-maximize it."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    # IsIconic=1, IsZoomed=0 → _window_state returns "minimized"
    fake_u32, show_window_calls = _fake_user32_stateful(is_iconic=1, is_zoomed_initial=0)
    monkeypatch.setattr(windows_mod, "_user32", fake_u32)
    monkeypatch.setattr(windows_mod, "move_to_bounds", lambda hwnd, bounds: dict(bounds))

    windows_mod.resize_window_impl(tw.handle_id, _BOUNDS)

    assert show_window_calls == [], (
        "resize_window_impl must not call ShowWindow when window is minimized"
    )


def test_resize_window_impl_invalid_bounds_on_maximized_no_show_window(monkeypatch):
    """Regression (#14 fix): when bounds are invalid (w=0), resize_window_impl must
    raise ValueError WITHOUT calling ShowWindow — the window must remain maximized
    and the operation must be fully side-effect free."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    fake_u32, show_window_calls = _fake_user32_stateful(is_iconic=0, is_zoomed_initial=1)
    monkeypatch.setattr(windows_mod, "_user32", fake_u32)
    monkeypatch.setattr(windows_mod, "move_to_bounds", lambda hwnd, bounds: dict(bounds))

    invalid_bounds = {"x": 10, "y": 20, "w": 0, "h": 600}

    with pytest.raises(ValueError):
        windows_mod.resize_window_impl(tw.handle_id, invalid_bounds)

    # ShowWindow must NOT have been called — the window stays maximized.
    assert show_window_calls == [], (
        "resize_window_impl must not call ShowWindow when bounds are invalid; "
        "the window must remain maximized"
    )


def test_resize_window_impl_returns_correct_bounds_when_maximized(monkeypatch):
    """When the window was maximized, the returned bounds must match the input
    bounds (move_to_bounds ran after SW_RESTORE with the correct values)."""
    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    monkeypatch.setattr(windows_mod, "REGISTRY", r)

    fake_u32, show_window_calls = _fake_user32_stateful(is_iconic=0, is_zoomed_initial=1)
    monkeypatch.setattr(windows_mod, "_user32", fake_u32)

    received_bounds: list = []

    def capturing_move_to_bounds(hwnd, bounds):
        received_bounds.append(dict(bounds))
        return dict(bounds)

    monkeypatch.setattr(windows_mod, "move_to_bounds", capturing_move_to_bounds)

    result = windows_mod.resize_window_impl(tw.handle_id, _BOUNDS)

    # move_to_bounds must have been called with our exact input bounds.
    assert len(received_bounds) == 1
    assert received_bounds[0] == _BOUNDS

    # Returned bounds must match.
    assert result["bounds"] == _BOUNDS


# ---------------------------------------------------------------------------
# Ticket #17: list_windows_impl reports DWMWA_EXTENDED_FRAME_BOUNDS (regression)
# ---------------------------------------------------------------------------


def test_list_windows_reports_extended_frame_bounds_when_available(
    monkeypatch, isolated_registry
):
    """Regression (#17): list_windows_impl must use _get_extended_frame when it
    returns a non-None rect, not the shadow-inflated GetWindowRect value."""
    import lib_python_vdesktop.desktops as desktops_mod

    isolated_registry.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")

    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=0, is_zoomed=0))

    # Extended frame: visible bounds (no shadow).
    monkeypatch.setattr(
        windows_mod, "_get_extended_frame", lambda hwnd: _make_rect(0, 0, 1280, 1080)
    )
    # OS rect: shadow-inflated (-7 px per edge).
    monkeypatch.setattr(
        windows_mod, "_get_window_rect", lambda hwnd: _make_rect(-7, -7, 1287, 1087)
    )
    monkeypatch.setattr(windows_mod, "get_window_title", lambda hwnd: "T")
    monkeypatch.setattr(desktops_mod, "pyvda", None)

    result = windows_mod.list_windows_impl()
    assert len(result) == 1
    assert result[0]["bounds"] == {"x": 0, "y": 0, "w": 1280, "h": 1080}, (
        "list_windows_impl must report extended-frame bounds (visible), not the "
        "shadow-inflated GetWindowRect value"
    )


def test_list_windows_falls_back_to_window_rect_when_extended_frame_unavailable(
    monkeypatch, isolated_registry
):
    """When _get_extended_frame returns None (DWM unavailable), bounds must come
    from _get_window_rect."""
    import lib_python_vdesktop.desktops as desktops_mod

    isolated_registry.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")

    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=0, is_zoomed=0))

    # DWM unavailable — extended frame returns None.
    monkeypatch.setattr(windows_mod, "_get_extended_frame", lambda hwnd: None)
    # OS rect is the only source.
    monkeypatch.setattr(
        windows_mod, "_get_window_rect", lambda hwnd: _make_rect(-7, -7, 1287, 1087)
    )
    monkeypatch.setattr(windows_mod, "get_window_title", lambda hwnd: "T")
    monkeypatch.setattr(desktops_mod, "pyvda", None)

    result = windows_mod.list_windows_impl()
    assert len(result) == 1
    assert result[0]["bounds"] == {"x": -7, "y": -7, "w": 1294, "h": 1094}, (
        "list_windows_impl must fall back to _get_window_rect when "
        "_get_extended_frame returns None"
    )


def test_list_windows_falls_back_to_registry_bounds_when_extended_frame_raises(
    monkeypatch, isolated_registry
):
    """When _get_extended_frame raises OSError, the outer except OSError must catch it
    and return tw.bounds (registry-stored value), with state None."""
    import lib_python_vdesktop.desktops as desktops_mod

    tw = isolated_registry.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test")
    # Store a known bounds value in the registry so we can assert it is returned.
    isolated_registry.update_bounds(tw.handle_id, {"x": 10, "y": 20, "w": 800, "h": 600})

    monkeypatch.setattr(windows_mod, "_user32", _fake_user32(is_iconic=0, is_zoomed=0))

    def raising_extended_frame(hwnd):
        raise OSError("DWM not available")

    monkeypatch.setattr(windows_mod, "_get_extended_frame", raising_extended_frame)
    monkeypatch.setattr(windows_mod, "get_window_title", lambda hwnd: "T")
    monkeypatch.setattr(desktops_mod, "pyvda", None)

    result = windows_mod.list_windows_impl()
    assert len(result) == 1
    entry = result[0]
    assert entry["bounds"] == {"x": 10, "y": 20, "w": 800, "h": 600}, (
        "list_windows_impl must return registry-stored bounds when _get_extended_frame "
        "raises OSError"
    )
    assert entry["state"] is None, (
        "state must be None when the Win32 call raises OSError"
    )


# ---------------------------------------------------------------------------
# Ticket #21: move_to_bounds returns OS-reported actual bounds, not requested
# ---------------------------------------------------------------------------


def test_move_to_bounds_returns_extended_frame_bounds_not_requested(monkeypatch):
    """Regression (#21): move_to_bounds must return the DWM extended-frame bounds
    reported by the OS after SetWindowPos, NOT the clamped-requested bounds.

    The caller requests {x:100,y:100,w:800,h:500} but DWM adjusts the window
    so the extended frame is left=93, top=100, right=907, bottom=507.
    The return value must reflect the DWM-adjusted rect.
    """
    ns = types.SimpleNamespace()
    ns.SetWindowPos = lambda *a: None
    ns.IsIconic = lambda hwnd: 0
    ns.IsZoomed = lambda hwnd: 0
    ns.ShowWindow = lambda hwnd, cmd: None
    ns.GetWindowRect = lambda hwnd, rect_ptr: None

    monkeypatch.setattr(windows_mod, "_user32", ns)
    monkeypatch.setattr(windows_mod, "_shadow_margins", lambda hwnd: (0, 0, 0, 0))
    monkeypatch.setattr(windows_mod, "_virtual_screen_rect",
                        lambda: {"x": 0, "y": 0, "w": 1920, "h": 1080})
    # DWM returns adjusted bounds (slightly different from requested).
    monkeypatch.setattr(
        windows_mod,
        "_get_extended_frame",
        lambda hwnd: _make_rect(left=93, top=100, right=907, bottom=507),
    )

    result = windows_mod.move_to_bounds(
        _FAKE_HWND, {"x": 100, "y": 100, "w": 800, "h": 500}
    )

    # Must reflect the DWM-adjusted extended frame, not the requested values.
    assert result == {"x": 93, "y": 100, "w": 814, "h": 407}, (
        "move_to_bounds must return OS-reported extended-frame bounds, not the "
        "requested (clamped) bounds"
    )


def test_move_to_bounds_falls_back_to_window_rect_when_extended_frame_none(monkeypatch):
    """When _get_extended_frame returns None, move_to_bounds must fall back to
    _get_window_rect and return bounds derived from that rect."""
    ns = types.SimpleNamespace()
    ns.SetWindowPos = lambda *a: None
    ns.IsIconic = lambda hwnd: 0
    ns.IsZoomed = lambda hwnd: 0
    ns.ShowWindow = lambda hwnd, cmd: None
    ns.GetWindowRect = lambda hwnd, rect_ptr: None

    monkeypatch.setattr(windows_mod, "_user32", ns)
    monkeypatch.setattr(windows_mod, "_shadow_margins", lambda hwnd: (0, 0, 0, 0))
    monkeypatch.setattr(windows_mod, "_virtual_screen_rect",
                        lambda: {"x": 0, "y": 0, "w": 1920, "h": 1080})
    # DWM unavailable — extended frame returns None.
    monkeypatch.setattr(windows_mod, "_get_extended_frame", lambda hwnd: None)
    # _get_window_rect returns a known rect.
    monkeypatch.setattr(
        windows_mod,
        "_get_window_rect",
        lambda hwnd: _make_rect(left=90, top=95, right=910, bottom=610),
    )

    result = windows_mod.move_to_bounds(
        _FAKE_HWND, {"x": 100, "y": 100, "w": 800, "h": 500}
    )

    # Must reflect the _get_window_rect values (fallback path).
    assert result == {"x": 90, "y": 95, "w": 820, "h": 515}, (
        "move_to_bounds must fall back to _get_window_rect bounds when "
        "_get_extended_frame returns None"
    )


def test_move_to_bounds_falls_back_to_requested_when_read_back_is_zero(monkeypatch):
    """Regression (#21 guard): if both read-backs return a zero-sized rect (window
    disappeared between SetWindowPos and the read-back), move_to_bounds must return
    the clamped-requested bounds rather than persisting a zero-rect to the registry."""
    ns = types.SimpleNamespace()
    ns.SetWindowPos = lambda *a: None
    ns.IsIconic = lambda hwnd: 0
    ns.IsZoomed = lambda hwnd: 0
    ns.ShowWindow = lambda hwnd, cmd: None
    ns.GetWindowRect = lambda hwnd, rect_ptr: None

    monkeypatch.setattr(windows_mod, "_user32", ns)
    monkeypatch.setattr(windows_mod, "_shadow_margins", lambda hwnd: (0, 0, 0, 0))
    monkeypatch.setattr(windows_mod, "_virtual_screen_rect",
                        lambda: {"x": 0, "y": 0, "w": 1920, "h": 1080})
    # Extended frame unavailable.
    monkeypatch.setattr(windows_mod, "_get_extended_frame", lambda hwnd: None)
    # _get_window_rect returns a zero-sized rect (window briefly invalid).
    monkeypatch.setattr(
        windows_mod,
        "_get_window_rect",
        lambda hwnd: _make_rect(left=0, top=0, right=0, bottom=0),
    )

    result = windows_mod.move_to_bounds(
        _FAKE_HWND, {"x": 100, "y": 100, "w": 800, "h": 500}
    )

    # Must fall back to the clamped-requested bounds, not the zero-rect.
    assert result == {"x": 100, "y": 100, "w": 800, "h": 500}, (
        "move_to_bounds must return clamped-requested bounds when the read-back "
        "yields a zero-sized rect (window briefly disappeared after SetWindowPos)"
    )
