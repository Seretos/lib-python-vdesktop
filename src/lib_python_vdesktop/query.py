"""Title/URL-based window queries — fallback identification when labels aren't
known yet. find_chrome_tab uses UI Automation to walk Chrome's tab strip."""
from __future__ import annotations

import ctypes
import logging
import re
from ctypes import wintypes
from typing import Optional, Union

from . import desktops as desktops_mod
from ._win32_helpers import get_window_classname, get_window_title
from ._window_classes import CHROME_WIDGET_CLASS
from .tracking import REGISTRY

log = logging.getLogger("vdesktop.query")

_user32 = ctypes.windll.user32
_EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def find_window_by_title_impl(
    pattern: str,
    desktop: Optional[Union[int, str]] = None,
    regex: bool = False,
) -> list[dict]:
    """Enumerate visible top-level windows whose title matches `pattern`.
    Returns a list of {hwnd, title, class_name, desktop_guid, handle_id?, label?}.
    """
    if regex:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(
                f"pattern: invalid regex in 'pattern' argument: {exc}"
            ) from exc
    else:
        compiled = None
    desktop_guid: Optional[str] = None
    if desktop is not None:
        d = desktops_mod.resolve_desktop(desktop)
        desktop_guid = str(d.id)

    results: list[dict] = []

    def callback(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        if _user32.GetWindow(hwnd, 4) != 0:  # GW_OWNER
            return True
        title = get_window_title(hwnd)
        if not title:
            return True
        matched = (
            bool(compiled.search(title)) if compiled else (pattern in title)
        )
        if not matched:
            return True
        guid = desktops_mod.desktop_guid_for_hwnd(hwnd)
        if desktop_guid is not None and guid != desktop_guid:
            return True
        tracked = REGISTRY.find_by_hwnd(int(hwnd))
        results.append(
            {
                "hwnd": int(hwnd),
                "title": title,
                "class_name": get_window_classname(hwnd),
                "desktop_guid": guid,
                "handle_id": tracked.handle_id if tracked else None,
                "label": tracked.label if tracked else None,
            }
        )
        return True

    _user32.EnumWindows(_EnumWindowsProc(callback), 0)
    return results


def find_chrome_tab_impl(
    pattern: str,
    regex: bool = False,
) -> list[dict]:
    """Search the tab strips of all Chrome windows for a tab whose title
    contains (or matches as regex) `pattern`, via UI Automation.

    Returns a list of {handle_id, hwnd, tab_index, tab_title, window_title}.
    ``tab_index = -1`` means the match came from the window title (active-tab
    fallback) rather than UIA enumeration. Adopts the matching Chrome window
    into the registry if it wasn't tracked yet.
    """
    try:
        import uiautomation as uia  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "find_chrome_tab requires the `uiautomation` package on Windows."
        ) from exc

    if regex:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(
                f"pattern: invalid regex in 'pattern' argument: {exc}"
            ) from exc
    else:
        compiled = None
    results: list[dict] = []

    def _tab_title_matches(tab_title: str) -> bool:
        if compiled is not None:
            return bool(compiled.search(tab_title))
        return pattern.lower() in tab_title.lower()

    def _record_match(hwnd: int, window_title: str, tab_index: int, tab_title: str) -> None:
        tracked = REGISTRY.find_by_hwnd(hwnd)
        if tracked is None:
            desktop_guid = desktops_mod.desktop_guid_for_hwnd(hwnd)
            tracked = REGISTRY.register(
                hwnd=hwnd,
                pid=0,
                app_type="chrome",
                desktop_guid=desktop_guid,
                title=window_title,
            )
        results.append(
            {
                "handle_id": tracked.handle_id,
                "hwnd": hwnd,
                "tab_index": tab_index,
                "tab_title": tab_title,
                "window_title": window_title,
            }
        )

    # F6: Keep the ClassName guard to identify Chrome windows, but drop the
    # w.Name substring check — Chrome windows in non-English locales or with
    # custom titles would otherwise be silently excluded.
    chrome_windows = [
        w for w in uia.GetRootControl().GetChildren()
        if w.ClassName == CHROME_WIDGET_CLASS
        and (w.Name or "")  # must have a non-empty title (real window, not splash)
    ]
    log.debug("find_chrome_tab: %d Chrome window(s) visible", len(chrome_windows))

    for win in chrome_windows:
        title = win.Name or ""
        hwnd = int(win.NativeWindowHandle)
        try:
            tab_strip = win.TabControl()
            if not tab_strip.Exists(0.5, 0.1):
                log.debug(
                    "find_chrome_tab: tab strip not found for hwnd=%s title=%r",
                    hwnd, title,
                )
                raise LookupError("no tab strip")
            tabs = tab_strip.GetChildren()
        except Exception as exc:  # noqa: BLE001
            log.debug(
                "find_chrome_tab: UIA tab enumeration failed for hwnd=%s (%s); "
                "falling back to window-title match",
                hwnd, exc,
            )
            if _tab_title_matches(title):
                _record_match(hwnd, title, -1, title)
            continue

        log.debug(
            "find_chrome_tab: hwnd=%s exposed %d tab(s) via UIA",
            hwnd, len(tabs),
        )
        tab_matched = False
        for idx, tab in enumerate(tabs):
            tab_title = tab.Name or ""
            if _tab_title_matches(tab_title):
                _record_match(hwnd, title, idx, tab_title)
                tab_matched = True
        # If UIA enumerated tabs but none matched, the window title is
        # usually "<active tab title> - Google Chrome" — try that as a
        # last-resort substring match so a user-visible tab can't be
        # missed when UIA reports the wrong children.
        if not tab_matched and _tab_title_matches(title):
            _record_match(hwnd, title, -1, title)

    log.debug("find_chrome_tab: %d match(es) for pattern=%r", len(results), pattern)
    return results
