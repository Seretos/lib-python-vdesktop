"""Chrome launcher.

Key insight: passing a fresh ``--user-data-dir`` per launch forces Chrome to
spawn a brand-new master/browser process. Otherwise chrome.exe IPCs to the
existing instance and exits, breaking PID-based HWND resolution.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional, Union

from .._window_classes import CHROME_WIDGET_CLASS
from ._common import launch_and_register

log = logging.getLogger("vdesktop.launcher.chrome")

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome() -> str:
    for path in _CHROME_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "chrome.exe not found. Install Google Chrome or set the path explicitly via launch_app."
    )


def launch_chrome_impl(
    urls: list[str],
    slot: Optional[str] = None,
    desktop: Optional[Union[int, str]] = None,
    label: Optional[str] = None,
    new_user_data_dir: bool = True,
    incognito: bool = False,
) -> dict:
    if not urls:
        raise ValueError("launch_chrome requires at least one URL")
    chrome = find_chrome()
    args = [chrome, "--new-window"]
    if incognito:
        args.append("--incognito")
    if new_user_data_dir:
        udd = tempfile.mkdtemp(prefix="vdesktop-chrome-")
        args.extend(
            [
                f"--user-data-dir={udd}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )
    args.extend(urls)

    return launch_and_register(
        args=args,
        app_type="chrome",
        label=label,
        slot=slot,
        desktop=desktop,
        class_filter=CHROME_WIDGET_CLASS,
        resolve_timeout_ms=10000,
    )
