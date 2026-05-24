"""Tests for F15: launch_and_register kills the spawned process when HWND
resolution fails, and re-raises the original RuntimeError.

All tests are pure Python / no real process spawning — _spawn_phase and
_resolve_hwnd_phase are monkeypatched.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

import lib_python_vdesktop.launchers._common as common_mod
from lib_python_vdesktop.tracking import Registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_PID = 5678


def _fake_proc():
    """Minimal Popen look-alike with a trackable kill()."""
    p = MagicMock()
    p.pid = _FAKE_PID
    return p


@pytest.fixture
def isolated_registry(monkeypatch):
    r = Registry()
    monkeypatch.setattr(common_mod, "REGISTRY", r)
    return r


# ---------------------------------------------------------------------------
# F15: kill() called once, RuntimeError re-raised
# ---------------------------------------------------------------------------


def test_launch_kills_proc_on_resolution_failure(monkeypatch, isolated_registry):
    """When _resolve_hwnd_phase raises RuntimeError, proc.kill() must be called
    exactly once and the RuntimeError must propagate to the caller."""
    proc = _fake_proc()

    monkeypatch.setattr(
        common_mod,
        "_spawn_phase",
        lambda *a, **kw: (proc, set()),
    )
    monkeypatch.setattr(
        common_mod,
        "_resolve_hwnd_phase",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("Could not resolve HWND for test after 0ms")
        ),
    )

    with pytest.raises(RuntimeError, match="Could not resolve HWND"):
        common_mod.launch_and_register(
            args=["fake.exe"],
            app_type="test",
        )

    proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# F15: OSError from proc.kill() is suppressed, RuntimeError still propagates
# ---------------------------------------------------------------------------


def test_launch_kill_oserror_suppressed(monkeypatch, isolated_registry):
    """If proc.kill() raises OSError, it must be swallowed — the original
    RuntimeError from _resolve_hwnd_phase still propagates."""
    proc = _fake_proc()
    proc.kill.side_effect = OSError("process already gone")

    monkeypatch.setattr(
        common_mod,
        "_spawn_phase",
        lambda *a, **kw: (proc, set()),
    )
    monkeypatch.setattr(
        common_mod,
        "_resolve_hwnd_phase",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("Could not resolve HWND for test after 0ms")
        ),
    )

    with pytest.raises(RuntimeError, match="Could not resolve HWND"):
        common_mod.launch_and_register(
            args=["fake.exe"],
            app_type="test",
        )

    # kill() was still attempted once even though it raised OSError.
    proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Sanity: successful launch does NOT call proc.kill()
# ---------------------------------------------------------------------------

_FAKE_HWND = 777
_FAKE_GUID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
_FAKE_BOUNDS = {"x": 0, "y": 0, "w": 1920, "h": 1080}


def test_launch_success_does_not_kill(monkeypatch, isolated_registry):
    """On a successful launch, proc.kill() must not be called."""
    proc = _fake_proc()

    monkeypatch.setattr(
        common_mod,
        "_spawn_phase",
        lambda *a, **kw: (proc, set()),
    )
    monkeypatch.setattr(
        common_mod,
        "_resolve_hwnd_phase",
        lambda *a, **kw: _FAKE_HWND,
    )
    monkeypatch.setattr(
        common_mod,
        "_placement_phase",
        lambda hwnd, *, desktop, slot: (_FAKE_GUID, _FAKE_BOUNDS),
    )
    monkeypatch.setattr(
        common_mod,
        "get_window_title",
        lambda hwnd: "Fake Window",
    )

    result = common_mod.launch_and_register(
        args=["fake.exe"],
        app_type="test",
    )

    assert result["hwnd"] == _FAKE_HWND
    proc.kill.assert_not_called()
