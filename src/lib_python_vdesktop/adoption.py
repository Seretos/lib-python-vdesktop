"""Adoption — pulling existing top-level windows (not spawned by the engine) into
the handle registry so they can be addressed like first-class tracked windows."""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Optional

from . import desktops as desktops_mod
from ._win32_helpers import (
    get_window_classname,
    get_window_pid,
    get_window_rect,
    get_window_title,
    is_window,
)
from ._window_classes import CHROME_WIDGET_CLASS, TERMINAL_CLASS
from .tracking import REGISTRY

log = logging.getLogger("vdesktop.adoption")

_user32 = ctypes.windll.user32
_EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def _classify(class_name: str, title: str) -> str:
    """Best-effort app-type label from window class + title.

    Both Chrome and Edge use the Chrome_WidgetWin_1 class (Edge is Chromium-
    based). They are distinguished by their title suffix: "- Google Chrome"
    vs. "- Microsoft Edge" (sometimes "Microsoft​ Edge" with a
    zero-width space, hence the substring check).
    """
    cn = class_name.lower()
    if cn == CHROME_WIDGET_CLASS.lower():
        t = title.lower()
        if "microsoft edge" in t.replace("​", ""):
            return "edge"
        if "visual studio code" in t:
            return "vscode"
        return "chrome"
    if "cascadia" in cn:
        return "terminal"
    return "unknown"


def list_unmanaged_windows_impl(desktop_guid: Optional[str] = None) -> list[dict]:
    """Return all top-level, visible, non-owned, *titled* windows not already
    in the registry. If desktop_guid is given, filter by current desktop GUID."""
    known: set[int] = {tw.hwnd for tw in REGISTRY.all()}
    results: list[dict] = []

    def callback(hwnd, _lparam):
        if hwnd in known:
            return True
        if not _user32.IsWindowVisible(hwnd):
            return True
        if _user32.GetWindow(hwnd, 4) != 0:  # GW_OWNER
            return True
        title = get_window_title(hwnd)
        if not title:
            return True
        class_name = get_window_classname(hwnd)
        guid = desktops_mod.desktop_guid_for_hwnd(hwnd)
        if desktop_guid is not None and guid != desktop_guid:
            return True
        results.append(
            {
                "hwnd": int(hwnd),
                "pid": get_window_pid(hwnd),
                "title": title,
                "class_name": class_name,
                "app_type": _classify(class_name, title),
                "desktop_guid": guid,
                "bounds": get_window_rect(hwnd),
            }
        )
        return True

    _user32.EnumWindows(_EnumWindowsProc(callback), 0)
    return results


def adopt_window_impl(
    hwnd: int,
    label: Optional[str] = None,
    app_type_hint: Optional[str] = None,
) -> dict:
    """Adopt an existing top-level window into the tracking registry.

    Note on ``pid``: the returned ``pid`` is the owner of the HWND at adopt
    time as reported by GetWindowThreadProcessId.  For Windows Terminal
    (``wt.exe``), the host process re-parents the conhost/window handle to a
    long-lived ``WindowsTerminal.exe`` process, so the ``pid`` here will differ
    from the ``pid`` recorded by ``launch_terminal_impl`` (which captures the
    short-lived ``wt.exe`` stub PID).  This is expected Windows Terminal
    behaviour and is not a bug in this library.
    """
    if not is_window(int(hwnd)):
        raise ValueError(f"hwnd {hwnd!r} does not correspond to an existing window")
    existing = REGISTRY.find_by_hwnd(int(hwnd))
    if existing is not None:
        if label:
            REGISTRY.relabel(existing.handle_id, label)
        return {"handle_id": existing.handle_id, "already_tracked": True}

    title = get_window_title(int(hwnd))
    class_name = get_window_classname(int(hwnd))
    app_type = app_type_hint or _classify(class_name, title)
    desktop_guid = desktops_mod.desktop_guid_for_hwnd(int(hwnd))
    bounds = get_window_rect(int(hwnd))
    pid = get_window_pid(int(hwnd))

    tw = REGISTRY.register(
        hwnd=int(hwnd),
        pid=pid,
        app_type=app_type,
        label=label,
        desktop_guid=desktop_guid,
        bounds=bounds,
        title=title,
    )
    return {
        "handle_id": tw.handle_id,
        "hwnd": tw.hwnd,
        "pid": tw.pid,
        "label": tw.label,
        "app_type": tw.app_type,
        "desktop_guid": tw.desktop_guid,
        "bounds": tw.bounds,
        "title": tw.title,
    }


def release_window_impl(handle_id: str) -> dict:
    tw = REGISTRY.remove(handle_id)
    return {"handle_id": handle_id, "released": tw is not None}
