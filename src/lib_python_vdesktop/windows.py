"""Window-positioning primitives: SetWindowPos with DWM-shadow correction,
focus, close, minimize/maximize/restore — plus the higher-level operations
(list/move/resize/...) that combine them with the tracking registry."""
from __future__ import annotations

import ctypes
import logging
import time
from ctypes import byref, wintypes
from typing import Optional, Union

from . import adoption, desktops as desktops_mod
from ._win32_helpers import get_window_title
from .layouts import lookup_slot
from .monitors import monitor_for_hwnd
from .tracking import REGISTRY

log = logging.getLogger("vdesktop.windows")

_user32 = ctypes.windll.user32
_dwmapi = ctypes.windll.dwmapi

DWMWA_EXTENDED_FRAME_BOUNDS = 9

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_ASYNCWINDOWPOS = 0x4000

WM_CLOSE = 0x0010

SW_RESTORE = 9
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_SHOWNORMAL = 1


def _window_state(hwnd: int) -> str:
    """Return the current show-state of an HWND as a string.

    Uses Win32 IsIconic / IsZoomed — no pyvda dependency.
    Minimized takes precedence over maximized (a minimized window can also
    report IsZoomed if it was maximised before being minimised).
    """
    if _user32.IsIconic(hwnd):
        return "minimized"
    if _user32.IsZoomed(hwnd):
        return "maximized"
    return "restored"


def _get_window_rect(hwnd: int) -> wintypes.RECT:
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, byref(rect))
    return rect


def _get_extended_frame(hwnd: int) -> Optional[wintypes.RECT]:
    rect = wintypes.RECT()
    hr = _dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, byref(rect), ctypes.sizeof(rect)
    )
    if hr != 0:
        return None
    return rect


def _shadow_margins(hwnd: int) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) invisible margin sizes.

    Positive value means the window-rect extends *past* the visible frame on
    that side by that many pixels (drop shadow / DWM compositor inset).
    """
    win = _get_window_rect(hwnd)
    ext = _get_extended_frame(hwnd)
    if ext is None:
        return (0, 0, 0, 0)
    # Clamp to zero — a non-shadowed frame (e.g. some apps with custom chrome)
    # can occasionally report ext outside win, which would otherwise produce
    # negative margins that shift the placement off-target.
    return (
        max(0, ext.left - win.left),
        max(0, ext.top - win.top),
        max(0, win.right - ext.right),
        max(0, win.bottom - ext.bottom),
    )


def move_to_bounds(hwnd: int, bounds: dict) -> dict:
    """Move/resize a window so its **visible** frame matches `bounds` exactly,
    compensating for DWM drop-shadow margins. Returns the bounds actually
    applied (visible).
    """
    bx, by = int(bounds["x"]), int(bounds["y"])
    bw, bh = int(bounds["w"]), int(bounds["h"])
    if bw <= 0 or bh <= 0:
        raise ValueError(
            f"move_to_bounds: width and height must be positive, got w={bw}, h={bh}"
        )
    sx, sy, sr, sb = _shadow_margins(hwnd)
    x = bx - sx
    y = by - sy
    w = bw + sx + sr
    h = bh + sy + sb
    flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW
    _user32.SetWindowPos(hwnd, 0, x, y, w, h, flags)
    return {"x": bx, "y": by, "w": bw, "h": bh}


def focus_window_hwnd(hwnd: int) -> None:
    """Bring an HWND to the foreground, switching its virtual desktop first if needed."""
    # Switch desktops if necessary.
    try:
        import pyvda  # type: ignore

        view = pyvda.AppView(hwnd=hwnd)
        if not view.is_on_current_desktop():
            view.switch_to()
    except Exception as exc:  # noqa: BLE001
        log.debug("focus: desktop switch fallback: %s", exc)
    # Restore if minimized.
    try:
        _user32.ShowWindow(hwnd, SW_RESTORE)
    except OSError as exc:
        log.debug("focus: ShowWindow(SW_RESTORE) failed: %s", exc)
    _user32.SetForegroundWindow(hwnd)


def close_window_hwnd(hwnd: int, *, force: bool = False) -> None:
    if force:
        _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        time.sleep(0.3)
        # If still alive, terminate the process. (Best-effort; we don't have the PID here.)
    else:
        _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def _resolve_target(handle_id: str, target: dict) -> tuple[Optional[dict], Optional[str]]:
    """Translate a move target into (bounds, desktop_ref).

    Accepted target shapes:
      {"slot": "<slot_id>", "monitor": <int>?}   → bounds from last layout
      {"bounds": {"x":..,"y":..,"w":..,"h":..}}  → explicit bounds
      {"desktop": <ref>}                          → move across desktops only
    Combinations possible: {"slot": "right", "desktop": "test-1"}.
    """
    bounds: Optional[dict] = None
    desktop_ref: Optional[str] = None

    if "bounds" in target:
        bounds = dict(target["bounds"])
    elif "slot" in target:
        tw = REGISTRY.get(handle_id)
        guid = tw.desktop_guid if tw else None
        slot = lookup_slot(target["slot"], desktop_guid=guid)
        if slot is None:
            raise KeyError(f"Slot {target['slot']!r} unknown — apply_layout first")
        bounds = slot["bounds"]
    if "desktop" in target:
        desktop_ref = target["desktop"]
    return bounds, desktop_ref


def list_windows_impl(
    desktop: Optional[Union[int, str]] = None,
    include_unmanaged: bool = False,
) -> list[dict]:
    desktop_guid: Optional[str] = None
    if desktop is not None:
        d = desktops_mod.resolve_desktop(desktop)
        desktop_guid = str(d.id)

    results: list[dict] = []
    for tw in REGISTRY.all():
        if desktop_guid and tw.desktop_guid and tw.desktop_guid != desktop_guid:
            continue
        try:
            rect = _get_window_rect(tw.hwnd)
            bounds = {
                "x": rect.left,
                "y": rect.top,
                "w": rect.right - rect.left,
                "h": rect.bottom - rect.top,
            }
            state: Optional[str] = _window_state(tw.hwnd)
        except OSError as exc:
            log.debug("list_windows: GetWindowRect(%s) failed: %s", tw.hwnd, exc)
            bounds = tw.bounds
            state = None
        try:
            title = get_window_title(tw.hwnd)
        except OSError as exc:
            log.debug("list_windows: get_window_title(%s) failed: %s", tw.hwnd, exc)
            title = tw.title
        window_pinned, app_pinned = desktops_mod.pin_state_for_hwnd(tw.hwnd)
        results.append(
            {
                "handle_id": tw.handle_id,
                "label": tw.label,
                "app_type": tw.app_type,
                "title": title,
                "hwnd": tw.hwnd,
                "pid": tw.pid,
                "desktop_guid": tw.desktop_guid,
                "slot_id": tw.slot_id,
                "bounds": bounds,
                "state": state,
                "is_pinned": window_pinned,
                "is_app_pinned": app_pinned,
            }
        )

    if include_unmanaged:
        results.extend(adoption.list_unmanaged_windows_impl(desktop_guid))

    return results


def move_window_impl(handle_id: str, target: dict) -> dict:
    tw = REGISTRY.require(handle_id)
    bounds, desktop_ref = _resolve_target(handle_id, target)

    if desktop_ref is not None:
        new_guid = desktops_mod.move_hwnd_to_desktop(tw.hwnd, desktop_ref)
        tw.desktop_guid = new_guid

    if bounds is not None:
        applied = move_to_bounds(tw.hwnd, bounds)
        slot_id = target.get("slot") if "slot" in target else tw.slot_id
        REGISTRY.update_bounds(handle_id, applied, slot_id=slot_id)
        return {"handle_id": handle_id, "bounds": applied, "desktop_guid": tw.desktop_guid}

    return {"handle_id": handle_id, "bounds": tw.bounds, "desktop_guid": tw.desktop_guid}


def resize_window_impl(handle_id: str, bounds: dict) -> dict:
    tw = REGISTRY.require(handle_id)
    applied = move_to_bounds(tw.hwnd, bounds)
    REGISTRY.update_bounds(handle_id, applied)
    return {"handle_id": handle_id, "bounds": applied}


def close_window_impl(handle_id: str, force: bool = False) -> dict:
    tw = REGISTRY.require(handle_id)
    close_window_hwnd(tw.hwnd, force=force)
    REGISTRY.remove(handle_id)
    return {"handle_id": handle_id, "closed": True}


def focus_window_impl(handle_id: str) -> dict:
    tw = REGISTRY.require(handle_id)
    focus_window_hwnd(tw.hwnd)
    return {"handle_id": handle_id, "focused": True}


def relabel_window_impl(handle_id: str, new_label: Optional[str]) -> dict:
    REGISTRY.require(handle_id)
    REGISTRY.relabel(handle_id, new_label)
    return {"handle_id": handle_id, "label": new_label}


def minimize_window_impl(handle_id: str) -> dict:
    tw = REGISTRY.require(handle_id)
    _user32.ShowWindow(tw.hwnd, SW_MINIMIZE)
    return {"handle_id": handle_id, "state": _window_state(tw.hwnd)}


def maximize_window_impl(handle_id: str) -> dict:
    tw = REGISTRY.require(handle_id)
    _user32.ShowWindow(tw.hwnd, SW_MAXIMIZE)
    return {"handle_id": handle_id, "state": _window_state(tw.hwnd)}


def restore_window_impl(handle_id: str) -> dict:
    tw = REGISTRY.require(handle_id)
    _user32.ShowWindow(tw.hwnd, SW_RESTORE)
    return {"handle_id": handle_id, "state": _window_state(tw.hwnd)}
