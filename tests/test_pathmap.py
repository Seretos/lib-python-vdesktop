"""Tests for lib_python_vdesktop.pathmap — POSIX <-> Windows path conversion."""
from __future__ import annotations

import subprocess

import pytest

from lib_python_vdesktop import pathmap
from lib_python_vdesktop.pathmap import (
    calling_wsl_distro,
    default_wsl_distro,
    to_posix,
    to_windows,
)


# --- to_windows --------------------------------------------------------------


def test_to_windows_empty():
    assert to_windows("") == ""


def test_to_windows_windows_path_unchanged():
    assert to_windows("C:\\foo\\bar") == "C:\\foo\\bar"


def test_to_windows_normalizes_forward_slashes():
    assert to_windows("C:/foo/bar") == "C:\\foo\\bar"


def test_to_windows_unc_path_normalized():
    assert to_windows("\\\\server\\share/file") == "\\\\server\\share\\file"


def test_to_windows_mnt_drive():
    assert to_windows("/mnt/c/foo") == "C:\\foo"


def test_to_windows_mnt_drive_root_only():
    assert to_windows("/mnt/c") == "C:\\"


def test_to_windows_mnt_drive_uppercase():
    # Source is lowercased on the POSIX side, output should be uppercase.
    assert to_windows("/mnt/d/Users/me") == "D:\\Users\\me"


def test_to_windows_wsl_home_path():
    assert to_windows("/home/user", wsl_distro="Ubuntu") == "\\\\wsl$\\Ubuntu\\home\\user"


def test_to_windows_wsl_uses_calling_distro(monkeypatch):
    monkeypatch.setattr(pathmap, "calling_wsl_distro", lambda: "TestDistro")
    assert to_windows("/etc/hosts") == "\\\\wsl$\\TestDistro\\etc\\hosts"


def test_to_windows_relative_path_normalized():
    assert to_windows("foo/bar/baz") == "foo\\bar\\baz"


# --- to_posix ----------------------------------------------------------------


def test_to_posix_empty():
    assert to_posix("") == ""


def test_to_posix_already_posix_unchanged():
    assert to_posix("/home/user/file") == "/home/user/file"


def test_to_posix_windows_drive():
    assert to_posix("C:\\foo\\bar") == "/mnt/c/foo/bar"


def test_to_posix_windows_drive_root_only():
    # Note: current implementation returns "/mnt/c/" with a trailing slash for
    # drive-root inputs (the backslash in "C:\\" becomes "/" and is appended).
    # Both "/mnt/c" and "/mnt/c/" are accepted by WSL — keeping the test in
    # sync with actual behavior rather than fixing pathmap here.
    assert to_posix("C:\\") == "/mnt/c/"
    assert to_posix("D:\\") == "/mnt/d/"


def test_to_posix_unc_wsl():
    assert to_posix("\\\\wsl$\\Ubuntu\\home\\user") == "/home/user"


def test_to_posix_unc_non_wsl_returns_as_is():
    # Plain UNC share is not a WSL filesystem mount; leave it alone.
    p = "\\\\server\\share\\file"
    assert to_posix(p) == p


def test_to_posix_relative_path_normalized():
    assert to_posix("foo\\bar\\baz") == "foo/bar/baz"


# --- roundtrip ---------------------------------------------------------------


@pytest.mark.parametrize("posix_path", [
    "/mnt/c/foo/bar",
    "/mnt/d/Users/me/Documents",
])
def test_roundtrip_mnt_paths(posix_path):
    assert to_posix(to_windows(posix_path)) == posix_path


def test_roundtrip_drive_root_has_trailing_slash():
    # See note in test_to_posix_windows_drive_root_only: the trailing slash
    # is a known quirk of the round trip, not a regression.
    assert to_posix(to_windows("/mnt/e")) == "/mnt/e/"


@pytest.mark.parametrize("posix_path", [
    "/home/user",
    "/etc/hosts",
])
def test_roundtrip_wsl_paths(posix_path):
    win = to_windows(posix_path, wsl_distro="Ubuntu")
    assert to_posix(win) == posix_path


# --- default_wsl_distro ------------------------------------------------------


def test_default_wsl_distro_uses_env(monkeypatch):
    default_wsl_distro.cache_clear()
    monkeypatch.setenv("WSL_DEFAULT_DISTRO", "Debian")
    assert default_wsl_distro() == "Debian"
    default_wsl_distro.cache_clear()


def test_default_wsl_distro_parses_wsl_output(monkeypatch):
    default_wsl_distro.cache_clear()
    monkeypatch.delenv("WSL_DEFAULT_DISTRO", raising=False)

    class FakeResult:
        # UTF-16-LE encoded "Ubuntu\nDebian\n"
        stdout = "Ubuntu\nDebian\n".encode("utf-16-le")

    def fake_run(*args, **kwargs):
        return FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert default_wsl_distro() == "Ubuntu"
    default_wsl_distro.cache_clear()


def test_default_wsl_distro_falls_back_when_wsl_missing(monkeypatch):
    default_wsl_distro.cache_clear()
    monkeypatch.delenv("WSL_DEFAULT_DISTRO", raising=False)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("wsl.exe not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert default_wsl_distro() == "Ubuntu"
    default_wsl_distro.cache_clear()


# --- calling_wsl_distro -------------------------------------------------------


def test_calling_wsl_distro_wsl_localhost_unc(monkeypatch):
    """CWD of the form \\\\wsl.localhost\\<distro>\\... (UNC) -> that distro."""
    # A real UNC path has two leading backslashes: \\wsl.localhost\claude-agents\...
    # In Python string literals that is "\\\\wsl.localhost\\claude-agents\\..."
    monkeypatch.setattr(pathmap.os, "getcwd", lambda: "\\\\wsl.localhost\\claude-agents\\home\\user\\repo")
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    assert calling_wsl_distro() == "claude-agents"


def test_calling_wsl_distro_wsl_dollar_unc(monkeypatch):
    """CWD of the older \\\\wsl$\\<distro>\\... form -> that distro."""
    monkeypatch.setattr(pathmap.os, "getcwd", lambda: "\\\\wsl$\\claude-agents\\home\\user")
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    assert calling_wsl_distro() == "claude-agents"


def test_calling_wsl_distro_uses_env_when_no_unc(monkeypatch):
    """Normal Windows drive CWD + WSL_DISTRO_NAME set -> env value."""
    monkeypatch.setattr(pathmap.os, "getcwd", lambda: "C:\\Users\\me")
    monkeypatch.setenv("WSL_DISTRO_NAME", "EnvDistro")
    assert calling_wsl_distro() == "EnvDistro"


def test_calling_wsl_distro_falls_back_to_default(monkeypatch):
    """Normal CWD + env unset -> falls back to default_wsl_distro()."""
    monkeypatch.setattr(pathmap.os, "getcwd", lambda: "C:\\Users\\me")
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(pathmap, "default_wsl_distro", lambda: "sentinel-distro")
    assert calling_wsl_distro() == "sentinel-distro"


def test_to_windows_uses_calling_wsl_distro_when_no_explicit(monkeypatch):
    """to_windows() without explicit wsl_distro uses calling_wsl_distro()."""
    monkeypatch.setattr(pathmap, "calling_wsl_distro", lambda: "claude-agents")
    assert to_windows("/home/user/repo") == "\\\\wsl$\\claude-agents\\home\\user\\repo"
