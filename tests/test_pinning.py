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
