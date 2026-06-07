"""Firefox launcher.

Key insight: Firefox uses a singleton-process IPC mechanism. When another
Firefox instance is already running, a new `firefox.exe` invocation hands off
to that process and exits immediately, which breaks PID-based HWND resolution.

The fix: pass ``-no-remote`` (prevents IPC hand-off) together with
``-profile <unique_profile_dir>`` (each profile directory is locked to one
process, so even if -no-remote were stripped by a wrapper this keeps the
spawned PID alive).  With a temporary, throwaway profile directory the spawned
PID stays alive and maps reliably to the new window.

Note: ``-P <name>`` selects a profile **by name** from ``profiles.ini`` and
does NOT accept an arbitrary filesystem path. ``-profile <path>`` is required
to point Firefox at a specific directory, which is what enables the isolation.

Firefox CLI flags used:
  -no-remote          Do not accept or send remote commands; always start a
                      new browser process regardless of existing instances.
  -profile <path>     Use the specified profile directory (filesystem path,
                      not a profiles.ini name). This is the isolation flag.
  -new-window         Open a new browser window (single-dash Firefox convention).
  -private-window     Open the window in private-browsing mode.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional, Union

from .._window_classes import MOZILLA_WINDOW_CLASS
from ._common import launch_and_register

log = logging.getLogger("vdesktop.launcher.firefox")

_FIREFOX_CANDIDATES = [
    os.path.expandvars(r"%ProgramFiles%\Mozilla Firefox\firefox.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Mozilla Firefox\firefox.exe"),
]


def find_firefox() -> str:
    for path in _FIREFOX_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "firefox.exe not found. Install Mozilla Firefox or set the path explicitly via launch_app."
    )


def build_firefox_args(
    firefox_exe: str,
    profile_dir: str,
    urls: list[str],
    private: bool = False,
) -> list[str]:
    """Assemble the full argv list for a Firefox launch.

    Pure function — no side-effects, no Win32 calls — so it is fully
    unit-testable without mocking.

    Order: exe, isolation flags, window-type flag, optional private flag, URLs.
    """
    args = [
        firefox_exe,
        "-no-remote",
        "-profile", profile_dir,
        "-new-window",
    ]
    if private:
        args.append("-private-window")
    args.extend(urls)
    return args


def launch_firefox_impl(
    urls: list[str],
    slot: Optional[str] = None,
    desktop: Optional[Union[int, str]] = None,
    label: Optional[str] = None,
    new_profile: bool = True,
    private: bool = False,
    env: Optional[dict[str, str]] = None,
) -> dict:
    if not urls:
        raise ValueError("launch_firefox requires at least one URL")
    firefox = find_firefox()
    if new_profile:
        profile_dir = tempfile.mkdtemp(prefix="vdesktop-firefox-")
    else:
        # Non-isolation path: pass the literal string "default" as the
        # -profile value, which Firefox interprets as a relative directory
        # name beside its install dir.  This does NOT guarantee a fresh
        # process (no singleton isolation); callers who need isolation must
        # leave new_profile=True (the default).
        profile_dir = "default"
    args = build_firefox_args(firefox, profile_dir, urls, private=private)

    return launch_and_register(
        args=args,
        app_type="firefox",
        label=label,
        slot=slot,
        desktop=desktop,
        class_filter=MOZILLA_WINDOW_CLASS,
        resolve_timeout_ms=10000,
        env=env,
    )
