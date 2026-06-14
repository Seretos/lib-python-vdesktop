"""Tests for lib_python_vdesktop.launchers.vscode — pure argv-builder tests.

These tests do NOT spawn any processes.  They intercept the argv that
``launch_vscode_impl`` would hand to the OS by monkeypatching ``find_vscode``
(returns a fake executable path) and ``launch_and_register`` (captures args,
returns a stub dict).
"""
from __future__ import annotations

import pytest

from lib_python_vdesktop.launchers import vscode as vscode_mod
from lib_python_vdesktop.launchers.vscode import launch_vscode_impl
from lib_python_vdesktop import pathmap


_FAKE_CODE = r"C:\fake\Code.exe"


@pytest.fixture(autouse=True)
def _stub_vscode(monkeypatch):
    """Make find_vscode() return a stable path without hitting the filesystem."""
    monkeypatch.setattr(vscode_mod, "find_vscode", lambda: _FAKE_CODE)


def _capture_args(monkeypatch):
    """Return a list that will be populated with the argv passed to launch_and_register."""
    captured = []

    def fake_launch(*, args, **kwargs):
        captured.extend(args)
        return {"status": "ok"}

    monkeypatch.setattr(vscode_mod, "launch_and_register", fake_launch)
    return captured


# ---------------------------------------------------------------------------
# Explicit wsl_distro overrides calling_wsl_distro
# ---------------------------------------------------------------------------


def test_explicit_wsl_distro_used_for_folder(monkeypatch):
    """Explicit wsl_distro converts POSIX folder path against the named distro."""
    args = _capture_args(monkeypatch)
    launch_vscode_impl("/home/user/repo", wsl_distro="my-distro")
    assert r"\\wsl$\my-distro\home\user\repo" in args


def test_explicit_wsl_distro_used_for_files(monkeypatch):
    """Explicit wsl_distro is also applied to each file path."""
    args = _capture_args(monkeypatch)
    launch_vscode_impl(
        "/home/user/repo",
        files=[{"path": "/home/user/repo/main.py"}],
        wsl_distro="my-distro",
    )
    assert r"\\wsl$\my-distro\home\user\repo" in args
    assert r"\\wsl$\my-distro\home\user\repo\main.py" in args


def test_explicit_wsl_distro_with_goto(monkeypatch):
    """Explicit wsl_distro works with line-number goto paths."""
    args = _capture_args(monkeypatch)
    launch_vscode_impl(
        "/home/user/repo",
        files=[{"path": "/home/user/repo/main.py", "line": 42}],
        wsl_distro="my-distro",
    )
    assert "--goto" in args
    goto_val = args[args.index("--goto") + 1]
    assert goto_val == r"\\wsl$\my-distro\home\user\repo\main.py:42"


# ---------------------------------------------------------------------------
# No explicit wsl_distro → calling_wsl_distro() is used (via to_windows)
# ---------------------------------------------------------------------------


def test_no_wsl_distro_uses_calling_wsl_distro(monkeypatch):
    """When wsl_distro is omitted, calling_wsl_distro() supplies the distro."""
    monkeypatch.setattr(pathmap, "calling_wsl_distro", lambda: "claude-agents")
    args = _capture_args(monkeypatch)
    launch_vscode_impl("/home/user/repo")
    assert r"\\wsl$\claude-agents\home\user\repo" in args


def test_no_wsl_distro_files_use_calling_wsl_distro(monkeypatch):
    """File paths also use calling_wsl_distro() when no explicit distro given."""
    monkeypatch.setattr(pathmap, "calling_wsl_distro", lambda: "claude-agents")
    args = _capture_args(monkeypatch)
    launch_vscode_impl(
        "/home/user/repo",
        files=[{"path": "/home/user/repo/utils.py"}],
    )
    # The file must be resolved against the inferred distro, not some other one.
    assert r"\\wsl$\Ubuntu\home\user\repo\utils.py" not in args
    assert r"\\wsl$\claude-agents\home\user\repo\utils.py" in args


# ---------------------------------------------------------------------------
# Windows paths pass through unchanged
# ---------------------------------------------------------------------------


def test_windows_folder_path_unchanged(monkeypatch):
    """A Windows drive path is forwarded as-is (no distro substitution)."""
    args = _capture_args(monkeypatch)
    launch_vscode_impl(r"C:\Users\me\project")
    assert r"C:\Users\me\project" in args


def test_windows_file_path_unchanged(monkeypatch):
    """Windows file paths are forwarded as-is."""
    args = _capture_args(monkeypatch)
    launch_vscode_impl(
        r"C:\Users\me\project",
        files=[{"path": r"C:\Users\me\project\main.py"}],
    )
    assert r"C:\Users\me\project\main.py" in args


# ---------------------------------------------------------------------------
# reuse_window flag
# ---------------------------------------------------------------------------


def test_new_window_flag_present_by_default(monkeypatch):
    """-n flag is included when reuse_window=False (default)."""
    args = _capture_args(monkeypatch)
    launch_vscode_impl(r"C:\Users\me\project")
    assert "-n" in args


def test_reuse_window_omits_new_flag(monkeypatch):
    """-n flag is absent when reuse_window=True."""
    args = _capture_args(monkeypatch)
    launch_vscode_impl(r"C:\Users\me\project", reuse_window=True)
    assert "-n" not in args
