"""Generic launcher for any executable. Used as a fallback when no specialized
launcher fits the user's request."""
from __future__ import annotations

import logging
from typing import Optional, Union

from ..pathmap import to_windows
from ._common import launch_and_register

log = logging.getLogger("vdesktop.launcher.generic")


def launch_app_impl(
    executable: str,
    args: Optional[list[str]] = None,
    cwd: Optional[str] = None,
    slot: Optional[str] = None,
    desktop: Optional[Union[int, str]] = None,
    label: Optional[str] = None,
    identification: Optional[dict] = None,
) -> dict:
    exe = to_windows(executable) if executable.startswith("/") else executable
    cmd: list[str] = [exe]
    if args:
        cmd.extend(args)
    cwd_win = to_windows(cwd) if cwd else None

    ident = identification or {}
    title_hint = ident.get("title_contains")
    class_filter = ident.get("class_name")
    timeout = int(ident.get("timeout_ms", 8000))

    return launch_and_register(
        args=cmd,
        app_type="generic",
        label=label,
        slot=slot,
        desktop=desktop,
        cwd=cwd_win,
        title_hint=title_hint,
        class_filter=class_filter,
        resolve_timeout_ms=timeout,
        pre_spawn_snapshot=bool(class_filter),
    )
