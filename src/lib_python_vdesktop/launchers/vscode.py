"""VS Code launcher.

Code.exe's CLI spawn returns quickly while the Electron main window is still
booting in child processes; we resolve the HWND via title match
("<folder> - Visual Studio Code") with a class filter for VS Code.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Union

from .._window_classes import CHROME_WIDGET_CLASS
from ..pathmap import to_windows
from ._common import launch_and_register

log = logging.getLogger("vdesktop.launcher.vscode")

_VSCODE_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
    r"C:\Program Files\Microsoft VS Code\Code.exe",
    r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
    # VS Code Insiders fallback:
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code Insiders\Code - Insiders.exe"),
]


def find_vscode() -> str:
    for path in _VSCODE_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "Code.exe not found. Install VS Code or set the path explicitly via launch_app."
    )


def _folder_basename(folder_win: str) -> str:
    base = folder_win.rstrip("\\")
    if "\\" in base:
        return base.rsplit("\\", 1)[1] or base
    return base


def launch_vscode_impl(
    folder: str,
    files: Optional[list[dict]] = None,
    slot: Optional[str] = None,
    desktop: Optional[Union[int, str]] = None,
    label: Optional[str] = None,
    reuse_window: bool = False,
    env: Optional[dict[str, str]] = None,
    wsl_distro: Optional[str] = None,
) -> dict:
    code = find_vscode()
    folder_win = to_windows(folder, wsl_distro=wsl_distro)
    args = [code]
    if not reuse_window:
        args.append("-n")
    args.append(folder_win)
    if files:
        for f in files:
            p = to_windows(f["path"], wsl_distro=wsl_distro)
            line = f.get("line")
            if line:
                args.extend(["--goto", f"{p}:{line}"])
            else:
                args.append(p)

    title_hint = f"{_folder_basename(folder_win)} - Visual Studio Code"
    return launch_and_register(
        args=args,
        app_type="vscode",
        label=label,
        slot=slot,
        desktop=desktop,
        title_hint=title_hint,
        class_filter=CHROME_WIDGET_CLASS,  # VS Code uses Electron/Chromium class.
        resolve_timeout_ms=15000,
        pre_spawn_snapshot=True,
        env=env,
    )
