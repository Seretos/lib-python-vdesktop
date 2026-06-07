"""Shared spawn + HWND-resolve pipeline used by all launchers."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import time
from ctypes import wintypes
from typing import Optional, Union

from .. import desktops as desktops_mod
from .._win32_helpers import (
    get_window_classname,
    get_window_pid,
    get_window_rect,
    get_window_title,
)
from ..layouts import lookup_slot
from ..tracking import REGISTRY
from ..windows import move_to_bounds

log = logging.getLogger("vdesktop.launcher")

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SYNCHRONIZE = 0x00100000

GW_OWNER = 4

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008


def _validate_cwd(cwd: Optional[str]) -> None:
    """Validate a launch working directory before spawning.

    A non-null `cwd` must point at an existing directory; we fail here with the
    offending path named, rather than letting subprocess.Popen surface an
    opaque OS error (or silently falling back to the server process's cwd).
    `cwd=None` is valid and means 'inherit the server process's cwd'.

    The caller is expected to have already translated POSIX paths to Windows
    (see `pathmap.to_windows`); this validates the path as given.
    """
    if cwd is None:
        return
    if not os.path.exists(cwd):
        raise ValueError(
            f"cwd does not exist: {cwd!r}. Pass an existing directory, or omit "
            "cwd to inherit the server's working directory."
        )
    if not os.path.isdir(cwd):
        raise ValueError(
            f"cwd is not a directory: {cwd!r}. Pass a directory path, or omit "
            "cwd to inherit the server's working directory."
        )


def spawn(
    args: list[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
) -> subprocess.Popen:
    """Spawn a Windows process detached from the MCP server's stdio. Returns
    Popen with .pid set to the immediate child PID — the foundation for HWND
    resolution."""
    flags = CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def wait_for_input_idle(pid: int, timeout_ms: int = 3000) -> None:
    """Wait until the process's message loop is idle (or timeout)."""
    handle = _kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_SYNCHRONIZE, False, pid
    )
    if not handle:
        return
    try:
        _user32.WaitForInputIdle(handle, timeout_ms)
    finally:
        _kernel32.CloseHandle(handle)


_EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def find_hwnd_for_pid(
    pid: int,
    *,
    class_filter: Optional[str] = None,
    not_in: Optional[set] = None,
) -> Optional[int]:
    """First top-level, visible, non-owned window belonging to `pid`."""
    result: list[int] = []
    not_in = not_in or set()

    def callback(hwnd, _lparam):
        if hwnd in not_in:
            return True
        if get_window_pid(hwnd) != pid:
            return True
        if not _user32.IsWindowVisible(hwnd):
            return True
        if _user32.GetWindow(hwnd, GW_OWNER) != 0:
            return True
        if class_filter and class_filter != get_window_classname(hwnd):
            return True
        result.append(hwnd)
        return False  # Stop enumeration.

    _user32.EnumWindows(_EnumWindowsProc(callback), 0)
    return result[0] if result else None


def find_hwnd_by_title(
    pattern: str,
    *,
    contains: bool = True,
    class_filter: Optional[str] = None,
    not_in: Optional[set] = None,
) -> Optional[int]:
    """First visible, non-owned window whose title matches the pattern."""
    result: list[int] = []
    not_in = not_in or set()

    def callback(hwnd, _lparam):
        if hwnd in not_in:
            return True
        if not _user32.IsWindowVisible(hwnd):
            return True
        if _user32.GetWindow(hwnd, GW_OWNER) != 0:
            return True
        if class_filter and class_filter != get_window_classname(hwnd):
            return True
        title = get_window_title(hwnd)
        if not title:
            return True
        match = (pattern in title) if contains else (title == pattern)
        if match:
            result.append(hwnd)
            return False
        return True

    _user32.EnumWindows(_EnumWindowsProc(callback), 0)
    return result[0] if result else None


def snapshot_hwnds(*, class_filter: Optional[str] = None) -> set[int]:
    """Capture the set of currently-visible top-level HWNDs, optionally filtered
    by class. Used to detect 'new' windows that appeared after spawn."""
    out: set[int] = set()

    def callback(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        if _user32.GetWindow(hwnd, GW_OWNER) != 0:
            return True
        if class_filter and class_filter != get_window_classname(hwnd):
            return True
        out.add(hwnd)
        return True

    _user32.EnumWindows(_EnumWindowsProc(callback), 0)
    return out


def find_new_hwnd_in_class(
    class_filter: str,
    previous: set[int],
    *,
    timeout_ms: int = 8000,
    tick_ms: int = 100,
    not_in: Optional[set] = None,
) -> Optional[int]:
    """Poll until a window of the given class appears that wasn't in `previous`.

    `not_in` is an additional exclusion set (e.g. HWNDs already tracked by
    REGISTRY) — those are filtered out regardless of whether they predate the
    spawn.
    """
    not_in = not_in or set()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        current = snapshot_hwnds(class_filter=class_filter)
        new = (current - previous) - not_in
        if new:
            # Prefer a window with non-empty title (real window, not splash).
            for hwnd in sorted(new):
                if get_window_title(hwnd):
                    return hwnd
            return next(iter(new))
        time.sleep(tick_ms / 1000.0)
    return None


def resolve_hwnd(
    *,
    pid: int,
    title_hint: Optional[str] = None,
    class_filter: Optional[str] = None,
    timeout_ms: int = 8000,
    tick_ms: int = 75,
    not_in: Optional[set] = None,
) -> Optional[int]:
    """Resolve a window handle for a freshly-launched process.

    Strategy per tick:
      1) If `pid` non-zero, look for a top-level window owned by that PID.
      2) If a `title_hint` is given, look for a window whose title contains it.
    Both filters honor `class_filter` if given. `not_in` excludes HWNDs that
    are already accounted for (typically the REGISTRY's tracked HWNDs) — this
    prevents the title-match fallback from hijacking an existing window whose
    title happens to contain `title_hint`.
    """
    not_in = not_in or set()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if pid:
            hwnd = find_hwnd_for_pid(pid, class_filter=class_filter, not_in=not_in)
            if hwnd:
                return hwnd
        if title_hint:
            hwnd = find_hwnd_by_title(
                title_hint, class_filter=class_filter, not_in=not_in
            )
            if hwnd:
                return hwnd
        time.sleep(tick_ms / 1000.0)
    return None


def _spawn_phase(
    args: list[str],
    *,
    cwd: Optional[str],
    env: Optional[dict],
    class_filter: Optional[str],
    pre_spawn_snapshot: bool,
) -> tuple[subprocess.Popen, set[int]]:
    """Snapshot pre-existing HWNDs (if requested), then spawn.

    When ``pre_spawn_snapshot`` is True the snapshot is always taken — filtered
    by ``class_filter`` when one is provided, or unfiltered (all visible
    top-level windows) when no class_filter is given.  The unfiltered snapshot
    is required so the title-hint fallback in ``_resolve_hwnd_phase`` can detect
    that a resolved HWND predates the launch (singleton / hand-off apps).
    """
    previous: set[int] = set()
    if pre_spawn_snapshot:
        previous = snapshot_hwnds(class_filter=class_filter)
    proc = spawn(args, cwd=cwd, env=env)
    log.debug("spawned pid=%s args=%s", proc.pid, args[0])
    return proc, previous


def _resolve_hwnd_phase(
    proc: subprocess.Popen,
    *,
    app_type: str,
    title_hint: Optional[str],
    class_filter: Optional[str],
    previous: set[int],
    tracked: set[int],
    resolve_timeout_ms: int,
) -> tuple[int, bool]:
    """WaitForInputIdle → resolve by PID → fall back to title → fall back to
    new-in-class diff. Already-tracked HWNDs are excluded at every step so the
    title-match fallback can't hijack an existing window whose title happens
    to contain `title_hint`. Raises RuntimeError if nothing resolves.

    Returns ``(hwnd, adopted_existing)`` where ``adopted_existing`` is True
    when the resolved HWND was already present before the spawn (i.e. the OS
    handed activation to a pre-existing singleton process).
    """
    wait_for_input_idle(proc.pid, 3000)
    hwnd = resolve_hwnd(
        pid=proc.pid,
        title_hint=title_hint,
        class_filter=class_filter,
        timeout_ms=resolve_timeout_ms,
        not_in=tracked,
    )
    if hwnd is None and class_filter:
        hwnd = find_new_hwnd_in_class(
            class_filter,
            previous,
            timeout_ms=resolve_timeout_ms,
            not_in=tracked,
        )
        if hwnd:
            log.info("resolved %s HWND via class-snapshot diff", app_type)
    if hwnd is None:
        raise RuntimeError(
            f"Could not resolve HWND for {app_type} after {resolve_timeout_ms}ms "
            f"(pid={proc.pid}, title_hint={title_hint!r}, class={class_filter!r}). "
            "Already-tracked windows are intentionally excluded to prevent "
            "hijacking; if the spawn truly hands off to an existing process, "
            "release that handle first or use tighter identification."
        )
    adopted_existing = bool(previous) and hwnd in previous
    return hwnd, adopted_existing


def _placement_phase(
    hwnd: int,
    *,
    desktop: Optional[Union[int, str]],
    slot: Optional[str],
) -> tuple[Optional[str], Optional[dict]]:
    """Move the HWND to the requested desktop (if any) and slot bounds (if any).

    Returns (desktop_guid, applied_bounds).
    """
    if desktop is not None:
        desktop_guid = desktops_mod.move_hwnd_to_desktop(hwnd, desktop)
    else:
        desktop_guid = desktops_mod.desktop_guid_for_hwnd(hwnd)

    applied_bounds: Optional[dict] = None
    if slot is not None:
        slot_info = lookup_slot(slot, desktop_guid=desktop_guid)
        if slot_info is None:
            raise KeyError(
                f"Slot {slot!r} unknown — call apply_layout before launching."
            )
        applied_bounds = move_to_bounds(hwnd, slot_info["bounds"])
    return desktop_guid, applied_bounds


def launch_and_register(
    *,
    args: list[str],
    app_type: str,
    label: Optional[str] = None,
    slot: Optional[str] = None,
    desktop: Optional[Union[int, str]] = None,
    title_hint: Optional[str] = None,
    class_filter: Optional[str] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    resolve_timeout_ms: int = 8000,
    pre_spawn_snapshot: bool = False,
) -> dict:
    """Canonical launch pipeline: spawn → resolve HWND → place → register.

    When ``env`` is supplied the process inherits a full copy of ``os.environ``
    with the caller's keys overlaid. Pass ``env=None`` (the default) to inherit
    the environment through the OS without copying.
    """
    _validate_cwd(cwd)  # Fail clearly before spawning, not via an opaque OS error.
    merged_env: Optional[dict] = {**os.environ, **env} if env is not None else None
    tracked: set[int] = {tw.hwnd for tw in REGISTRY.all()}
    proc, previous = _spawn_phase(
        args,
        cwd=cwd,
        env=merged_env,
        class_filter=class_filter,
        pre_spawn_snapshot=pre_spawn_snapshot,
    )
    # F15: if HWND resolution fails, kill the orphan process before re-raising
    # the RuntimeError so we don't leave orphan processes behind.
    try:
        hwnd, adopted_existing = _resolve_hwnd_phase(
            proc,
            app_type=app_type,
            title_hint=title_hint,
            class_filter=class_filter,
            previous=previous,
            tracked=tracked,
            resolve_timeout_ms=resolve_timeout_ms,
        )
    except RuntimeError:
        try:
            proc.kill()
        except OSError:
            pass
        raise
    desktop_guid, applied_bounds = _placement_phase(
        hwnd, desktop=desktop, slot=slot
    )
    # When no slot was requested, _placement_phase leaves applied_bounds None.
    # Fall back to querying Win32 so the caller gets real coordinates instead
    # of null and doesn't need a follow-up list_windows call.
    if applied_bounds is None:
        try:
            applied_bounds = get_window_rect(hwnd)
        except OSError as exc:
            log.debug("launch_and_register: get_window_rect(%s) failed: %s", hwnd, exc)
    # Belt-and-suspenders: if a race made `tracked` stale and we somehow
    # resolved onto an existing HWND anyway, the caller deserves to know.
    prior = REGISTRY.find_by_hwnd(hwnd)
    tw = REGISTRY.register(
        hwnd=hwnd,
        pid=proc.pid,
        app_type=app_type,
        label=label,
        desktop_guid=desktop_guid,
        slot_id=slot,
        bounds=applied_bounds,
        title=get_window_title(hwnd),
    )
    result = {
        "handle_id": tw.handle_id,
        "hwnd": tw.hwnd,
        "pid": tw.pid,
        "label": tw.label,
        "app_type": tw.app_type,
        "desktop_guid": tw.desktop_guid,
        "slot_id": tw.slot_id,
        "bounds": tw.bounds,
        "title": tw.title,
        "adopted_existing": adopted_existing,
    }
    # Build up warnings — there can be multiple (prior-tracked race and/or
    # singleton adoption).  Collect them and join so neither is silently lost.
    warnings: list[str] = []
    if prior is not None:
        warnings.append(
            f"matched an already-tracked window (prior handle_id={prior.handle_id!r}, "
            f"label={prior.label!r}); existing entry was updated. To avoid this, "
            f"release that handle first or pass tighter identification."
        )
    if adopted_existing:
        warnings.append(
            "Resolved HWND predates the launch: an existing user-owned window was "
            "adopted. Call release_window before close_window to avoid destroying "
            "unsaved data."
        )
    if warnings:
        result["warning"] = " | ".join(warnings)
    return result
