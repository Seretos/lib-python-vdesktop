"""Microsoft Edge launcher.

Same Chromium foundation as Chrome — distinct user-data-dir per launch is
required to guarantee a fresh master/browser process whose spawn PID maps to
the new window. Without `--user-data-dir`, msedge.exe IPCs to the existing
instance and exits, breaking PID-based HWND resolution.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional, Union

from .._window_classes import CHROME_WIDGET_CLASS
from ._common import launch_and_register

log = logging.getLogger("vdesktop.launcher.edge")

_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]


def find_edge() -> str:
    for path in _EDGE_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "msedge.exe not found. Install Microsoft Edge or set the path explicitly via launch_app."
    )


def launch_edge_impl(
    urls: list[str],
    slot: Optional[str] = None,
    desktop: Optional[Union[int, str]] = None,
    label: Optional[str] = None,
    new_user_data_dir: bool = True,
    inprivate: bool = False,
) -> dict:
    if not urls:
        raise ValueError("launch_edge requires at least one URL")
    edge = find_edge()
    args = [edge, "--new-window"]
    if inprivate:
        args.append("--inprivate")
    if new_user_data_dir:
        udd = tempfile.mkdtemp(prefix="vdesktop-edge-")
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
        app_type="edge",
        label=label,
        slot=slot,
        desktop=desktop,
        class_filter=CHROME_WIDGET_CLASS,
        resolve_timeout_ms=10000,
    )
