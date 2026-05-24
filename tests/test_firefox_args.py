"""Tests for lib_python_vdesktop.launchers.firefox — pure argv builders.

All tests are pure Python with no real process spawning or Win32 calls.
Filesystem and Win32 entry points are monkeypatched where needed.
"""
from __future__ import annotations

import pytest

from lib_python_vdesktop._window_classes import MOZILLA_WINDOW_CLASS
from lib_python_vdesktop.launchers.firefox import (
    build_firefox_args,
    find_firefox,
    launch_firefox_impl,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FAKE_EXE = r"C:\Program Files\Mozilla Firefox\firefox.exe"
_FAKE_PROFILE = r"C:\Temp\vdesktop-firefox-abc123"
_URLS = ["https://example.com", "https://mozilla.org"]


# ---------------------------------------------------------------------------
# MOZILLA_WINDOW_CLASS constant
# ---------------------------------------------------------------------------


def test_mozilla_window_class_value():
    """Regression guard: the class name string must exactly match what Windows
    reports for Firefox top-level windows."""
    assert MOZILLA_WINDOW_CLASS == "MozillaWindowClass"


# ---------------------------------------------------------------------------
# build_firefox_args — pure arg-builder tests (no Win32, no filesystem)
# ---------------------------------------------------------------------------


def test_no_remote_flag_present():
    """Regression: -no-remote must be in the built args.

    Without this flag Firefox hands off to an existing instance and exits
    immediately, breaking PID-based HWND resolution — the core ticket failure.
    """
    args = build_firefox_args(_FAKE_EXE, _FAKE_PROFILE, _URLS)
    assert "-no-remote" in args


def test_profile_flag_present():
    """-profile followed by the profile dir must appear in the args.

    Firefox's -P flag selects a profile by name from profiles.ini and does
    NOT accept a filesystem path.  The correct flag for an arbitrary directory
    is -profile <path>, which is what enables singleton isolation.
    """
    args = build_firefox_args(_FAKE_EXE, _FAKE_PROFILE, _URLS)
    assert "-profile" in args
    profile_idx = args.index("-profile")
    assert args[profile_idx + 1] == _FAKE_PROFILE


def test_new_window_flag_present():
    """-new-window must be in the built args."""
    args = build_firefox_args(_FAKE_EXE, _FAKE_PROFILE, _URLS)
    assert "-new-window" in args


def test_urls_are_appended():
    """Each URL must appear in the args, in order."""
    args = build_firefox_args(_FAKE_EXE, _FAKE_PROFILE, _URLS)
    # Both URLs present
    for url in _URLS:
        assert url in args
    # Preserved order
    assert args.index(_URLS[0]) < args.index(_URLS[1])


def test_private_flag_present_when_requested():
    """-private-window must appear when private=True."""
    args = build_firefox_args(_FAKE_EXE, _FAKE_PROFILE, _URLS, private=True)
    assert "-private-window" in args


def test_private_flag_absent_by_default():
    """-private-window must NOT appear when private is not set."""
    args = build_firefox_args(_FAKE_EXE, _FAKE_PROFILE, _URLS)
    assert "-private-window" not in args


def test_new_window_flag_precedes_urls():
    """-new-window must appear before the first URL."""
    args = build_firefox_args(_FAKE_EXE, _FAKE_PROFILE, _URLS)
    new_window_idx = args.index("-new-window")
    first_url_idx = args.index(_URLS[0])
    assert new_window_idx < first_url_idx


def test_exe_is_first_arg():
    """The executable path must be the first element."""
    args = build_firefox_args(_FAKE_EXE, _FAKE_PROFILE, _URLS)
    assert args[0] == _FAKE_EXE


# ---------------------------------------------------------------------------
# find_firefox — filesystem detection
# ---------------------------------------------------------------------------


def test_find_firefox_raises_when_no_candidate_exists(monkeypatch):
    """find_firefox must raise FileNotFoundError when none of the candidate
    paths exist on disk."""
    monkeypatch.setattr("os.path.isfile", lambda path: False)
    with pytest.raises(FileNotFoundError, match="firefox.exe not found"):
        find_firefox()


def test_find_firefox_returns_first_existing_candidate(monkeypatch, tmp_path):
    """find_firefox must return the first candidate path that exists."""
    import lib_python_vdesktop.launchers.firefox as ff_mod

    fake_path = str(tmp_path / "firefox.exe")
    # Create the file so isfile returns True
    (tmp_path / "firefox.exe").write_text("")

    # Patch _FIREFOX_CANDIDATES so the first entry is our fake path
    monkeypatch.setattr(ff_mod, "_FIREFOX_CANDIDATES", [fake_path, "nonexistent.exe"])
    result = find_firefox()
    assert result == fake_path


# ---------------------------------------------------------------------------
# launch_firefox_impl — empty-URL validation (monkeypatch Win32 away)
# ---------------------------------------------------------------------------


def test_empty_urls_raises_value_error(monkeypatch):
    """launch_firefox_impl must raise ValueError for an empty URL list.

    find_firefox and launch_and_register are patched so no filesystem or
    Win32 calls are made.
    """
    import lib_python_vdesktop.launchers.firefox as ff_mod

    monkeypatch.setattr(ff_mod, "find_firefox", lambda: _FAKE_EXE)
    monkeypatch.setattr(ff_mod, "launch_and_register", lambda **kw: {})

    with pytest.raises(ValueError, match="launch_firefox requires at least one URL"):
        launch_firefox_impl([])


def test_new_profile_false_passes_default_profile(monkeypatch):
    """When new_profile=False, launch_firefox_impl must pass the literal
    "default" string as the -profile value to launch_and_register.

    This exercises the non-isolation branch: no tempdir is created and the
    profile value is the hard-coded "default" sentinel.
    """
    import lib_python_vdesktop.launchers.firefox as ff_mod

    captured: dict = {}

    def fake_launch_and_register(**kw):
        captured.update(kw)
        return {}

    monkeypatch.setattr(ff_mod, "find_firefox", lambda: _FAKE_EXE)
    monkeypatch.setattr(ff_mod, "launch_and_register", fake_launch_and_register)

    launch_firefox_impl(["https://example.com"], new_profile=False)

    args = captured["args"]
    assert "-profile" in args
    profile_idx = args.index("-profile")
    assert args[profile_idx + 1] == "default"
