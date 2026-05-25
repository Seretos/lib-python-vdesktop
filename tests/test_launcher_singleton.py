"""Tests for F16: singleton-launch HWND adoption detection.

All tests are pure Python / no real process spawning — _spawn_phase,
_resolve_hwnd_phase, _placement_phase, snapshot_hwnds, and get_window_title are
monkeypatched as needed.

Regression contract: the tests for adopted_existing=True MUST fail on the
unpatched code (where _resolve_hwnd_phase returns a bare int and _spawn_phase
skips the snapshot when class_filter is None) and PASS after the fix.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

import lib_python_vdesktop.launchers._common as common_mod
import lib_python_vdesktop.launchers.generic as generic_mod
from lib_python_vdesktop.tracking import Registry


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_FAKE_HWND = 4242
_FAKE_PID = 7777
_FAKE_GUID = "11112222-3333-4444-5555-666677778888"
_FAKE_BOUNDS = {"x": 0, "y": 0, "w": 1280, "h": 720}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_proc(pid: int = _FAKE_PID):
    p = MagicMock()
    p.pid = pid
    return p


@pytest.fixture
def isolated_registry(monkeypatch):
    """Fresh Registry injected into _common_mod."""
    r = Registry()
    monkeypatch.setattr(common_mod, "REGISTRY", r)
    return r


def _patch_placement(monkeypatch):
    monkeypatch.setattr(
        common_mod,
        "_placement_phase",
        lambda hwnd, *, desktop, slot: (_FAKE_GUID, _FAKE_BOUNDS),
    )
    monkeypatch.setattr(common_mod, "get_window_title", lambda hwnd: "Fake Window")


# ===========================================================================
# _spawn_phase unit tests
# ===========================================================================


def test_spawn_phase_snapshots_without_class_filter(monkeypatch):
    """_spawn_phase with pre_spawn_snapshot=True, class_filter=None must call
    snapshot_hwnds and return the sentinel set as `previous`."""
    sentinel: set[int] = {101, 202, 303}

    snapshot_calls: list[dict] = []

    def fake_snapshot(*, class_filter=None):
        snapshot_calls.append({"class_filter": class_filter})
        return sentinel

    monkeypatch.setattr(common_mod, "snapshot_hwnds", fake_snapshot)

    fake_args = ["notepad.exe"]

    def fake_spawn(args, *, cwd, env):
        p = types.SimpleNamespace()
        p.pid = _FAKE_PID
        return p

    monkeypatch.setattr(common_mod, "spawn", fake_spawn)

    _proc, previous = common_mod._spawn_phase(
        fake_args,
        cwd=None,
        env=None,
        class_filter=None,
        pre_spawn_snapshot=True,
    )

    assert previous == sentinel, (
        "_spawn_phase must return the snapshot set when pre_spawn_snapshot=True "
        "and class_filter=None"
    )
    assert len(snapshot_calls) == 1, "snapshot_hwnds must be called exactly once"
    assert snapshot_calls[0]["class_filter"] is None, (
        "snapshot_hwnds must be called with class_filter=None when no class_filter given"
    )


def test_spawn_phase_no_snapshot_when_disabled(monkeypatch):
    """_spawn_phase with pre_spawn_snapshot=False must NOT call snapshot_hwnds."""
    snapshot_calls: list[int] = []

    def fake_snapshot(*, class_filter=None):
        snapshot_calls.append(1)
        return {999}

    monkeypatch.setattr(common_mod, "snapshot_hwnds", fake_snapshot)

    def fake_spawn(args, *, cwd, env):
        p = types.SimpleNamespace()
        p.pid = _FAKE_PID
        return p

    monkeypatch.setattr(common_mod, "spawn", fake_spawn)

    _proc, previous = common_mod._spawn_phase(
        ["notepad.exe"],
        cwd=None,
        env=None,
        class_filter=None,
        pre_spawn_snapshot=False,
    )

    assert previous == set(), "previous must be empty when pre_spawn_snapshot=False"
    assert snapshot_calls == [], "snapshot_hwnds must NOT be called when pre_spawn_snapshot=False"


# ===========================================================================
# _resolve_hwnd_phase unit tests
# ===========================================================================


def test_resolve_hwnd_phase_returns_tuple(monkeypatch):
    """_resolve_hwnd_phase must return a (hwnd, adopted_existing) tuple."""
    monkeypatch.setattr(common_mod, "wait_for_input_idle", lambda pid, timeout: None)
    monkeypatch.setattr(
        common_mod,
        "resolve_hwnd",
        lambda *, pid, title_hint, class_filter, timeout_ms, not_in: _FAKE_HWND,
    )

    proc = _fake_proc()
    result = common_mod._resolve_hwnd_phase(
        proc,
        app_type="test",
        title_hint=None,
        class_filter=None,
        previous=set(),
        tracked=set(),
        resolve_timeout_ms=100,
    )
    assert isinstance(result, tuple) and len(result) == 2, (
        "_resolve_hwnd_phase must return a (hwnd, adopted_existing) tuple"
    )


# ===========================================================================
# V2 regression: adopted_existing detection via launch_and_register
# ===========================================================================


def test_adopted_existing_true_when_hwnd_in_previous_snapshot(
    monkeypatch, isolated_registry
):
    """When the resolved HWND is in the pre-spawn snapshot (previous set),
    adopted_existing must be True and result['warning'] must mention 'existing' or 'adopted'."""
    proc = _fake_proc()

    # Simulate: previous snapshot contains the HWND that will be resolved.
    monkeypatch.setattr(
        common_mod,
        "_spawn_phase",
        lambda *a, **kw: (proc, {_FAKE_HWND}),
    )
    monkeypatch.setattr(
        common_mod,
        "_resolve_hwnd_phase",
        lambda *a, **kw: (_FAKE_HWND, True),  # adopted_existing=True
    )
    _patch_placement(monkeypatch)

    result = common_mod.launch_and_register(
        args=["notepad.exe"],
        app_type="generic",
    )

    assert result["adopted_existing"] is True, (
        "adopted_existing must be True when HWND was in pre-spawn snapshot"
    )
    warning = result.get("warning", "")
    assert warning, "warning must be present when adopted_existing is True"
    assert "existing" in warning.lower() or "adopted" in warning.lower(), (
        f"warning must mention 'existing' or 'adopted' but got: {warning!r}"
    )


def test_adopted_existing_false_for_new_hwnd(monkeypatch, isolated_registry):
    """When HWND is NOT in previous snapshot (normal new launch), adopted_existing
    must be False and no adoption warning emitted."""
    proc = _fake_proc()

    # previous is empty — HWND definitely not in it.
    monkeypatch.setattr(
        common_mod,
        "_spawn_phase",
        lambda *a, **kw: (proc, set()),
    )
    monkeypatch.setattr(
        common_mod,
        "_resolve_hwnd_phase",
        lambda *a, **kw: (_FAKE_HWND, False),  # adopted_existing=False
    )
    _patch_placement(monkeypatch)

    result = common_mod.launch_and_register(
        args=["myapp.exe"],
        app_type="generic",
    )

    assert result["adopted_existing"] is False, (
        "adopted_existing must be False for a genuinely new window"
    )
    # No adoption warning expected.
    warning = result.get("warning", "")
    assert "adopted" not in warning.lower(), (
        "no adoption warning expected when adopted_existing is False"
    )


def test_adopted_existing_true_does_not_suppress_prior_warning(
    monkeypatch, isolated_registry
):
    """When BOTH a prior-tracked-window race AND adopted_existing=True fire,
    the result['warning'] must contain content from both (neither is silently dropped)."""
    proc = _fake_proc()

    # Pre-register the HWND so REGISTRY.find_by_hwnd returns a prior entry.
    isolated_registry.register(
        hwnd=_FAKE_HWND, pid=9999, app_type="existing", label="my-existing-window"
    )

    monkeypatch.setattr(
        common_mod,
        "_spawn_phase",
        lambda *a, **kw: (proc, {_FAKE_HWND}),
    )
    monkeypatch.setattr(
        common_mod,
        "_resolve_hwnd_phase",
        lambda *a, **kw: (_FAKE_HWND, True),
    )
    _patch_placement(monkeypatch)

    result = common_mod.launch_and_register(
        args=["notepad.exe"],
        app_type="generic",
    )

    warning = result.get("warning", "")
    assert warning, "warning must be present"
    # Prior-tracked warning content (contains handle_id reference or 'already-tracked').
    assert "already-tracked" in warning.lower() or "prior" in warning.lower(), (
        f"prior-tracked warning content missing from: {warning!r}"
    )
    # Adoption warning content.
    assert "existing" in warning.lower() or "adopted" in warning.lower(), (
        f"adoption warning content missing from: {warning!r}"
    )


# ===========================================================================
# generic.py: pre_spawn_snapshot always True
# ===========================================================================


def test_launch_app_impl_always_passes_pre_spawn_snapshot_true(monkeypatch):
    """launch_app_impl (generic) must call launch_and_register with
    pre_spawn_snapshot=True even when no identification/class_filter is provided."""
    captured: list[dict] = []

    def fake_launch_and_register(**kwargs):
        captured.append(kwargs)
        return {
            "handle_id": "abc12345",
            "hwnd": _FAKE_HWND,
            "pid": _FAKE_PID,
            "label": None,
            "app_type": "generic",
            "desktop_guid": _FAKE_GUID,
            "slot_id": None,
            "bounds": _FAKE_BOUNDS,
            "title": "Fake",
            "adopted_existing": False,
        }

    monkeypatch.setattr(generic_mod, "launch_and_register", fake_launch_and_register)
    # to_windows / pathmap is not relevant here — exe has no leading slash.
    generic_mod.launch_app_impl(executable="notepad.exe")

    assert len(captured) == 1
    assert captured[0].get("pre_spawn_snapshot") is True, (
        "generic.launch_app_impl must pass pre_spawn_snapshot=True unconditionally"
    )
