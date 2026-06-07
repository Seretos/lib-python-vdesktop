"""Regression tests for environment-variable overlay semantics in launchers.

Ticket #28: env passed to launch_and_register must be overlaid on os.environ,
not replace it.  All tests are pure Python — nothing is spawned.  The spawn,
HWND-resolution, placement, and registry paths are monkeypatched exactly as
test_launcher_bounds.py does them.
"""
from __future__ import annotations

import os
import types
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

import lib_python_vdesktop.launchers._common as common_mod
from lib_python_vdesktop.launchers import generic as generic_mod
from lib_python_vdesktop.tracking import Registry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FAKE_HWND = 888
_FAKE_PID = 5678
_FAKE_GUID = "11112222-3333-4444-5555-666677778888"


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _fake_proc(pid: int = _FAKE_PID):
    p = types.SimpleNamespace()
    p.pid = pid
    return p


@pytest.fixture
def isolated_registry(monkeypatch):
    """Fresh Registry injected into _common_mod so tests don't share state."""
    r = Registry()
    monkeypatch.setattr(common_mod, "REGISTRY", r)
    return r


def _patch_non_spawn_phases(monkeypatch):
    """Patch everything in launch_and_register except _spawn_phase itself,
    so we can inspect what _spawn_phase (or spawn / Popen) receives."""
    monkeypatch.setattr(
        common_mod,
        "_resolve_hwnd_phase",
        lambda *a, **kw: (_FAKE_HWND, False),
    )
    monkeypatch.setattr(
        common_mod,
        "_placement_phase",
        lambda hwnd, *, desktop, slot: (_FAKE_GUID, {"x": 0, "y": 0, "w": 1, "h": 1}),
    )
    monkeypatch.setattr(
        common_mod,
        "get_window_title",
        lambda hwnd: "Fake Window",
    )
    monkeypatch.setattr(
        common_mod,
        "get_window_rect",
        lambda hwnd: {"x": 0, "y": 0, "w": 1, "h": 1},
    )


def _call_launch_and_capture_popen_env(monkeypatch, isolated_registry, *, env):
    """Run launch_and_register with the given env kwarg and return the `env`
    keyword argument that was passed to subprocess.Popen."""
    _patch_non_spawn_phases(monkeypatch)
    captured = {}

    class _FakePopen:
        def __init__(self, args, **kwargs):
            captured["env"] = kwargs.get("env")
            self.pid = _FAKE_PID

    with patch("lib_python_vdesktop.launchers._common.subprocess.Popen", _FakePopen):
        common_mod.launch_and_register(
            args=["fake.exe"],
            app_type="test",
            env=env,
        )

    return captured["env"]


# ---------------------------------------------------------------------------
# Regression: overlay semantics — existing env key + new key both present
# ---------------------------------------------------------------------------


def test_env_overlay_merges_with_os_environ(monkeypatch, isolated_registry):
    """Regression (#28): Popen env must contain both EXISTING from os.environ
    and MY_KEY supplied by the caller."""
    monkeypatch.setenv("EXISTING", "yes")

    result_env = _call_launch_and_capture_popen_env(
        monkeypatch, isolated_registry, env={"MY_KEY": "my_val"}
    )

    assert result_env is not None
    assert result_env["EXISTING"] == "yes", "inherited key must be present"
    assert result_env["MY_KEY"] == "my_val", "caller-supplied key must be present"


# ---------------------------------------------------------------------------
# Override: caller key shadows os.environ key of the same name
# ---------------------------------------------------------------------------


def test_env_caller_key_overrides_os_environ(monkeypatch, isolated_registry):
    """When the caller supplies a key already in os.environ, the caller's value wins."""
    monkeypatch.setenv("PATH", "original")

    result_env = _call_launch_and_capture_popen_env(
        monkeypatch, isolated_registry, env={"PATH": "/custom"}
    )

    assert result_env is not None
    assert result_env["PATH"] == "/custom"


# ---------------------------------------------------------------------------
# env=None → Popen receives env=None (inherits from OS without copying)
# ---------------------------------------------------------------------------


def test_env_none_passes_none_to_popen(monkeypatch, isolated_registry):
    """env=None must forward None to Popen, not an empty dict or a copy."""
    result_env = _call_launch_and_capture_popen_env(
        monkeypatch, isolated_registry, env=None
    )

    assert result_env is None


# ---------------------------------------------------------------------------
# env={} → Popen receives a dict equal to os.environ (no extra keys)
# ---------------------------------------------------------------------------


def test_env_empty_dict_gives_copy_of_os_environ(monkeypatch, isolated_registry):
    """env={} must produce a Popen env equal to dict(os.environ) with no additions."""
    result_env = _call_launch_and_capture_popen_env(
        monkeypatch, isolated_registry, env={}
    )

    assert result_env is not None
    assert result_env == dict(os.environ)


# ---------------------------------------------------------------------------
# End-to-end through launch_app_impl
# ---------------------------------------------------------------------------


def test_env_end_to_end_through_launch_app_impl(monkeypatch, isolated_registry):
    """launch_app_impl(env=...) must reach Popen with the overlay applied."""
    monkeypatch.setenv("AMBIENT", "ambient_val")
    _patch_non_spawn_phases(monkeypatch)
    captured = {}

    class _FakePopen:
        def __init__(self, args, **kwargs):
            captured["env"] = kwargs.get("env")
            self.pid = _FAKE_PID

    with patch("lib_python_vdesktop.launchers._common.subprocess.Popen", _FakePopen):
        generic_mod.launch_app_impl(
            executable="notepad.exe",
            env={"FOO": "bar"},
        )

    result_env = captured["env"]
    assert result_env is not None
    assert result_env["FOO"] == "bar", "caller key must be present"
    assert result_env["AMBIENT"] == "ambient_val", "ambient env must be inherited"
