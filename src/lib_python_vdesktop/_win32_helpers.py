"""Shared Win32 helpers for querying top-level windows.

These wrap the GetWindowTextW / GetClassNameW / GetWindowThreadProcessId /
GetWindowRect calls used by adoption, query, launchers, and windows. Centralized
here so the buffer sizes and the ctypes plumbing live in one place.
"""
from __future__ import annotations

import ctypes
from ctypes import byref, wintypes

_user32 = ctypes.windll.user32

WINDOW_TEXT_BUFFER_SIZE = 512
CLASSNAME_BUFFER_SIZE = 256


def get_window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, byref(pid))
    return int(pid.value)


def get_window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(WINDOW_TEXT_BUFFER_SIZE)
    _user32.GetWindowTextW(hwnd, buf, WINDOW_TEXT_BUFFER_SIZE)
    return buf.value


def get_window_classname(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(CLASSNAME_BUFFER_SIZE)
    _user32.GetClassNameW(hwnd, buf, CLASSNAME_BUFFER_SIZE)
    return buf.value


def get_window_rect(hwnd: int) -> dict:
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, byref(rect))
    return {
        "x": rect.left,
        "y": rect.top,
        "w": rect.right - rect.left,
        "h": rect.bottom - rect.top,
    }
