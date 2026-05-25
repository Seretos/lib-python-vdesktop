"""Regression and edge-case tests for the pinning subsystem in desktops.py.

All tests are pure Python / no COM / no ctypes — safe to run on any Windows CI
runner regardless of whether the virtual-desktop COM surface is present.  The
tests monkey-patch ``lib_python_vdesktop.desktops.pyvda`` with a minimal fake
and inject a fresh Registry so each test is fully isolated.
"""
from __future__ import annotations

import types
from typing import Optional

import pytest

from lib_python_vdesktop.tracking import Registry
import lib_python_vdesktop.desktops as desktops_mod


# ---------------------------------------------------------------------------
# Fake pyvda
# ---------------------------------------------------------------------------


class FakeAppView:
    """Minimal pyvda.AppView look-alike controlled by two boolean flags."""

    def __init__(self, *, hwnd: int, _is_pinned: bool = False, _is_app_pinned: bool = False):
        self.hwnd = hwnd
        self._is_pinned = _is_pinned
        self._is_app_pinned = _is_app_pinned

    def is_pinned(self) -> bool:
        return self._is_pinned

    def is_app_pinned(self) -> bool:
        return self._is_app_pinned

    def pin(self) -> None:
        self._is_pinned = True

    def unpin(self) -> None:
        self._is_pinned = False

    def pin_app(self) -> None:
        self._is_app_pinned = True

    def unpin_app(self) -> None:
        self._is_app_pinned = False


def _make_fake_pyvda(is_pinned: bool = False, is_app_pinned: bool = False):
    """Return a fake pyvda module whose AppView returns the given initial state."""
    fake = types.SimpleNamespace()

    def AppView(*, hwnd: int):  # noqa: N802 – mimic pyvda.AppView
        return FakeAppView(hwnd=hwnd, _is_pinned=is_pinned, _is_app_pinned=is_app_pinned)

    fake.AppView = AppView
    return fake


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_HWND = 12345
_FAKE_PID = 999


@pytest.fixture
def reg() -> Registry:
    """Fresh registry with one pre-registered window."""
    r = Registry()
    r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test_app")
    return r


@pytest.fixture
def fake_pyvda(monkeypatch, request):
    """Monkeypatch desktops.pyvda with a stub whose initial pin states come from
    ``request.param`` — a dict with ``is_pinned`` and ``is_app_pinned`` keys
    (both default False).  Also injects a fresh registry so impl calls work.
    """
    params = getattr(request, "param", {}) or {}
    stub = _make_fake_pyvda(
        is_pinned=params.get("is_pinned", False),
        is_app_pinned=params.get("is_app_pinned", False),
    )
    monkeypatch.setattr(desktops_mod, "pyvda", stub)

    r = Registry()
    tw = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test_app")
    monkeypatch.setattr(desktops_mod, "REGISTRY", r)
    return stub, tw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _handle(tw) -> str:
    return tw.handle_id


# ===========================================================================
# Regression tests (must fail on the unpatched code)
# ===========================================================================


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": True}], indirect=True)
def test_is_pinned_app_only_sets_window_pinned_false(fake_pyvda):
    """When only the app is pinned (is_pinned True AND is_app_pinned True),
    window_pinned must be False — the old code returned True here (the bug)."""
    _stub, tw = fake_pyvda
    result = desktops_mod.is_pinned_impl(_handle(tw))
    assert result["window_pinned"] is False, (
        "window_pinned should be False when app-pin is active"
    )
    assert result["app_pinned"] is True


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": False, "is_app_pinned": False}], indirect=True)
def test_pin_app_result_includes_scope_and_warning(fake_pyvda):
    """pin_app_all_desktops_impl must include 'scope' and 'warning' keys."""
    _stub, tw = fake_pyvda
    result = desktops_mod.pin_app_all_desktops_impl(_handle(tw))
    assert "scope" in result, "result must contain 'scope'"
    assert result["scope"] == "app"
    assert "warning" in result, "result must contain 'warning'"
    assert isinstance(result["warning"], str) and len(result["warning"]) > 0


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": True}], indirect=True)
def test_unpin_app_result_includes_scope_and_warning(fake_pyvda):
    """unpin_app_impl must include 'scope' and 'warning' keys."""
    _stub, tw = fake_pyvda
    result = desktops_mod.unpin_app_impl(_handle(tw))
    assert "scope" in result, "result must contain 'scope'"
    assert result["scope"] == "app"
    assert "warning" in result, "result must contain 'warning'"
    assert isinstance(result["warning"], str) and len(result["warning"]) > 0


# ===========================================================================
# Edge-case tests for is_pinned_impl
# ===========================================================================


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": False}], indirect=True)
def test_is_pinned_window_only(fake_pyvda):
    """Window pinned via HWND only: window_pinned True, app_pinned False."""
    _stub, tw = fake_pyvda
    result = desktops_mod.is_pinned_impl(_handle(tw))
    assert result["window_pinned"] is True
    assert result["app_pinned"] is False


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": False, "is_app_pinned": False}], indirect=True)
def test_is_pinned_neither(fake_pyvda):
    """Neither flag set: both fields False."""
    _stub, tw = fake_pyvda
    result = desktops_mod.is_pinned_impl(_handle(tw))
    assert result["window_pinned"] is False
    assert result["app_pinned"] is False


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": True}], indirect=True)
def test_is_pinned_both_active(fake_pyvda):
    """Both flags True (OS overlap case): window_pinned False, app_pinned True."""
    _stub, tw = fake_pyvda
    result = desktops_mod.is_pinned_impl(_handle(tw))
    assert result["window_pinned"] is False
    assert result["app_pinned"] is True


# ===========================================================================
# Edge-case tests for pin_state_for_hwnd
# ===========================================================================


def test_pin_state_for_hwnd_app_only(monkeypatch):
    """Both is_pinned True AND is_app_pinned True → tuple (False, True)."""
    stub = _make_fake_pyvda(is_pinned=True, is_app_pinned=True)
    monkeypatch.setattr(desktops_mod, "pyvda", stub)
    result = desktops_mod.pin_state_for_hwnd(_FAKE_HWND)
    assert result == (False, True), f"expected (False, True), got {result}"


def test_pin_state_for_hwnd_window_only(monkeypatch):
    """Window pinned only → tuple (True, False)."""
    stub = _make_fake_pyvda(is_pinned=True, is_app_pinned=False)
    monkeypatch.setattr(desktops_mod, "pyvda", stub)
    result = desktops_mod.pin_state_for_hwnd(_FAKE_HWND)
    assert result == (True, False), f"expected (True, False), got {result}"


def test_pin_state_for_hwnd_pyvda_none(monkeypatch):
    """When pyvda is None (unavailable), the helper must return (None, None) without raising."""
    monkeypatch.setattr(desktops_mod, "pyvda", None)
    result = desktops_mod.pin_state_for_hwnd(_FAKE_HWND)
    assert result == (None, None), f"expected (None, None), got {result}"


# ===========================================================================
# Confirm window-level ops do NOT include scope/warning
# ===========================================================================


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": False, "is_app_pinned": False}], indirect=True)
def test_pin_window_no_scope_field(fake_pyvda):
    """pin_window_all_desktops_impl must NOT include 'scope' — it's HWND-only."""
    _stub, tw = fake_pyvda
    result = desktops_mod.pin_window_all_desktops_impl(_handle(tw))
    assert "scope" not in result, "window-pin result must not expose 'scope'"


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": False}], indirect=True)
def test_unpin_window_no_scope_field(fake_pyvda):
    """unpin_window_impl must NOT include 'scope' — it's HWND-only."""
    _stub, tw = fake_pyvda
    result = desktops_mod.unpin_window_impl(_handle(tw))
    assert "scope" not in result, "window-unpin result must not expose 'scope'"


# ===========================================================================
# Verify app_pinned is reflected in pin_app / unpin_app results
# ===========================================================================


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": False, "is_app_pinned": False}], indirect=True)
def test_pin_app_returns_app_pinned_true(fake_pyvda):
    """After pin_app_all_desktops_impl, result['app_pinned'] should be True
    (the stub's pin_app() sets _is_app_pinned True)."""
    _stub, tw = fake_pyvda
    result = desktops_mod.pin_app_all_desktops_impl(_handle(tw))
    assert result["app_pinned"] is True
    assert result["handle_id"] == _handle(tw)


# ===========================================================================
# Gap 3 regression: already_unpinned signal in unpin impls
# ===========================================================================


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": False, "is_app_pinned": False}], indirect=True)
def test_unpin_window_already_unpinned_true(fake_pyvda):
    """unpin_window_impl on an already-unpinned window must set already_unpinned=True."""
    _stub, tw = fake_pyvda
    result = desktops_mod.unpin_window_impl(_handle(tw))
    assert "already_unpinned" in result, "result must contain 'already_unpinned'"
    assert result["already_unpinned"] is True, (
        "already_unpinned must be True when the window was not pinned before the call"
    )


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": False}], indirect=True)
def test_unpin_window_already_unpinned_false(fake_pyvda):
    """unpin_window_impl on a pinned window must set already_unpinned=False."""
    _stub, tw = fake_pyvda
    result = desktops_mod.unpin_window_impl(_handle(tw))
    assert "already_unpinned" in result, "result must contain 'already_unpinned'"
    assert result["already_unpinned"] is False, (
        "already_unpinned must be False when the window was pinned before the call"
    )


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": False, "is_app_pinned": False}], indirect=True)
def test_unpin_app_already_unpinned_true(fake_pyvda):
    """unpin_app_impl on an already-unpinned app must set already_unpinned=True."""
    _stub, tw = fake_pyvda
    result = desktops_mod.unpin_app_impl(_handle(tw))
    assert "already_unpinned" in result, "result must contain 'already_unpinned'"
    assert result["already_unpinned"] is True, (
        "already_unpinned must be True when the app was not pinned before the call"
    )


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": True}], indirect=True)
def test_unpin_app_already_unpinned_false(fake_pyvda):
    """unpin_app_impl on a pinned app must set already_unpinned=False."""
    _stub, tw = fake_pyvda
    result = desktops_mod.unpin_app_impl(_handle(tw))
    assert "already_unpinned" in result, "result must contain 'already_unpinned'"
    assert result["already_unpinned"] is False, (
        "already_unpinned must be False when the app was pinned before the call"
    )


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": False}], indirect=True)
def test_unpin_window_preserves_existing_keys(fake_pyvda):
    """unpin_window_impl must preserve 'handle_id' and 'window_pinned' keys."""
    _stub, tw = fake_pyvda
    result = desktops_mod.unpin_window_impl(_handle(tw))
    assert "handle_id" in result
    assert "window_pinned" in result
    # After unpin, the window should no longer be pinned.
    assert result["window_pinned"] is False


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": True}], indirect=True)
def test_unpin_app_preserves_existing_keys(fake_pyvda):
    """unpin_app_impl must preserve 'handle_id', 'app_pinned', 'scope', 'warning' keys."""
    _stub, tw = fake_pyvda
    result = desktops_mod.unpin_app_impl(_handle(tw))
    assert "handle_id" in result
    assert "app_pinned" in result
    assert "scope" in result
    assert "warning" in result
    assert result["scope"] == "app"


# ===========================================================================
# V1 / #16: collateral_windows + desktop-reassignment warning (new)
# ===========================================================================


_FAKE_HWND_2 = 54321
_FAKE_PID_2 = 888


def _make_two_window_registry():
    """Return a Registry with two windows registered (HWNDs _FAKE_HWND and _FAKE_HWND_2)."""
    r = Registry()
    tw1 = r.register(hwnd=_FAKE_HWND, pid=_FAKE_PID, app_type="test_app")
    tw2 = r.register(hwnd=_FAKE_HWND_2, pid=_FAKE_PID_2, app_type="test_app2")
    return r, tw1, tw2


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": True}], indirect=True)
def test_unpin_app_collateral_windows_detected(fake_pyvda, monkeypatch):
    """Two registered windows: after unpin, the collateral window's desktop GUID
    changes from 'B' to 'A' — it must appear in collateral_windows."""
    _stub, tw1 = fake_pyvda
    # Register a second window in the same isolated registry.
    r = desktops_mod.REGISTRY
    tw2 = r.register(hwnd=_FAKE_HWND_2, pid=_FAKE_PID_2, app_type="test_app2")

    call_count = [0]

    def fake_desktop_guid(hwnd):
        call_count[0] += 1
        # First call cycle (pre-snap): tw2 is on 'B'
        # Second call cycle (post-snap): tw2 is on 'A' (OS collapsed it)
        # We distinguish via call_count parity.
        if call_count[0] <= 1:
            # pre-snap: collateral window (tw2) is on 'B'
            return "B"
        else:
            # post-snap: collateral window (tw2) has moved to 'A'
            return "A"

    monkeypatch.setattr(desktops_mod, "desktop_guid_for_hwnd", fake_desktop_guid)

    result = desktops_mod.unpin_app_impl(_handle(tw1))
    assert "collateral_windows" in result, "result must contain 'collateral_windows'"
    assert tw2.handle_id in result["collateral_windows"], (
        "collateral window must appear in collateral_windows when its desktop changed"
    )


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": True}], indirect=True)
def test_unpin_app_no_collateral_when_solo(fake_pyvda, monkeypatch):
    """Single registered window: collateral_windows must be present and empty."""
    _stub, tw = fake_pyvda
    # Only one window in the registry — no other windows to detect collateral on.
    monkeypatch.setattr(desktops_mod, "desktop_guid_for_hwnd", lambda hwnd: "A")

    result = desktops_mod.unpin_app_impl(_handle(tw))
    assert "collateral_windows" in result, "result must always contain 'collateral_windows'"
    assert result["collateral_windows"] == [], (
        "collateral_windows must be empty when only one window is registered"
    )


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": True}], indirect=True)
def test_unpin_app_collateral_windows_key_always_present(fake_pyvda, monkeypatch):
    """Even when desktop_guid_for_hwnd raises, collateral_windows is present (empty)
    and unpin still succeeds (no exception propagates)."""
    _stub, tw = fake_pyvda

    def exploding_guid(hwnd):
        raise RuntimeError("COM surface unavailable")

    monkeypatch.setattr(desktops_mod, "desktop_guid_for_hwnd", exploding_guid)

    result = desktops_mod.unpin_app_impl(_handle(tw))
    assert "collateral_windows" in result, (
        "collateral_windows key must be present even when desktop_guid_for_hwnd raises"
    )
    assert result["collateral_windows"] == [], (
        "collateral_windows must be empty when snapshot fails"
    )
    assert result["handle_id"] == _handle(tw), "unpin must still succeed when snapshot errors"


@pytest.mark.parametrize("fake_pyvda", [{"is_pinned": True, "is_app_pinned": True}], indirect=True)
def test_unpin_app_warning_mentions_desktop_relocation(fake_pyvda, monkeypatch):
    """The warning string must mention both 'desktop' and 'reassign' to make the
    destructive side-effect explicit to callers."""
    _stub, tw = fake_pyvda
    monkeypatch.setattr(desktops_mod, "desktop_guid_for_hwnd", lambda hwnd: "A")

    result = desktops_mod.unpin_app_impl(_handle(tw))
    warning = result.get("warning", "")
    assert "desktop" in warning.lower(), (
        f"warning must mention 'desktop' but got: {warning!r}"
    )
    assert "reassign" in warning.lower(), (
        f"warning must mention 'reassign' but got: {warning!r}"
    )
