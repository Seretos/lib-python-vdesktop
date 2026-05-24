"""Virtual-desktop operations via pyvda."""
from __future__ import annotations

import logging
import unicodedata
from typing import Optional, Union

from .tracking import REGISTRY

log = logging.getLogger("vdesktop.desktops")

try:
    import pyvda  # type: ignore
except (ImportError, NotImplementedError, OSError) as exc:
    # ImportError: package missing or its native bindings unavailable.
    # NotImplementedError: pyvda's _check_version guard on Windows builds that
    #   predate the virtual-desktop API surface it expects (e.g. Windows
    #   Server 2022 runners on GitHub Actions).
    # OSError: COM cannot bind at import time.
    # Capture all three so the module still loads -- individual desktop ops
    # then fail with a clean RuntimeError via _require(), and the rest of the
    # engine (layouts, window-ops, launchers) keeps working. This is also what
    # makes the build smoke-test pass on the CI Windows Server runner.
    pyvda = None  # type: ignore
    _pyvda_error: Optional[Exception] = exc
else:
    _pyvda_error = None


DesktopRef = Union[int, str]


def _require() -> None:
    if pyvda is None:
        raise RuntimeError(
            f"pyvda is required but failed to import: {_pyvda_error}. "
            "Install on the Windows host with: pip install pyvda"
        )


def _current_guid() -> str:
    return str(pyvda.VirtualDesktop.current().id)


def _info(desktop, index: int, current_guid: Optional[str] = None) -> dict:
    name = getattr(desktop, "name", None) or f"Desktop {index + 1}"
    guid = str(desktop.id)
    return {
        "index": index,
        "name": name,
        "guid": guid,
        "is_current": (current_guid is not None and guid == current_guid),
    }


def list_desktops_impl() -> list[dict]:
    _require()
    desktops = pyvda.get_virtual_desktops()
    cur = _current_guid()
    return [_info(d, i, cur) for i, d in enumerate(desktops)]


def resolve_desktop(target: Optional[DesktopRef]):
    """Resolve a 0-based index, a name, or a GUID to a pyvda VirtualDesktop.

    `None` returns the current desktop.
    """
    _require()
    if target is None:
        return pyvda.VirtualDesktop.current()
    desktops = pyvda.get_virtual_desktops()
    if isinstance(target, int):
        if not (0 <= target < len(desktops)):
            raise ValueError(f"Desktop index {target} out of range (have {len(desktops)})")
        return desktops[target]
    if isinstance(target, str):
        stripped = target.strip()
        if stripped.lstrip("-").isdigit():
            idx = int(stripped)
            if not (0 <= idx < len(desktops)):
                raise ValueError(f"Desktop index {idx} out of range (have {len(desktops)})")
            return desktops[idx]
        for d in desktops:
            if getattr(d, "name", None) == stripped or str(d.id) == stripped:
                return d
    raise ValueError(f"Unknown desktop reference: {target!r}")


def _rename(desktop, name: str) -> None:
    # pyvda exposes either rename(name) or a settable .name property depending
    # on version — try both.
    try:
        if hasattr(desktop, "rename"):
            desktop.rename(name)
            return
        desktop.name = name  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        log.warning("Renaming desktop failed: %s", exc)


def get_current_desktop_impl() -> dict:
    _require()
    current = pyvda.VirtualDesktop.current()
    desktops = pyvda.get_virtual_desktops()
    index = next(
        (i for i, d in enumerate(desktops) if str(d.id) == str(current.id)),
        0,
    )
    return _info(current, index, str(current.id))


def create_desktop_impl(name: Optional[str] = None) -> dict:
    _require()
    new_desktop = pyvda.VirtualDesktop.create()
    if name:
        _rename(new_desktop, name)
    desktops = pyvda.get_virtual_desktops()
    index = next(
        (i for i, d in enumerate(desktops) if str(d.id) == str(new_desktop.id)),
        len(desktops) - 1,
    )
    return _info(new_desktop, index, _current_guid())


def delete_desktop_impl(
    target: DesktopRef,
    fallback_desktop: Optional[DesktopRef] = None,
) -> dict:
    _require()
    desktop = resolve_desktop(target)
    fallback = resolve_desktop(fallback_desktop) if fallback_desktop is not None else None
    try:
        if fallback is not None and hasattr(desktop, "remove"):
            desktop.remove(fallback)
        else:
            desktop.remove()
    except TypeError:
        # Some pyvda versions: remove() takes no args; the windows go to
        # the desktop on the left automatically.
        desktop.remove()
    return {"deleted_guid": str(desktop.id), "remaining": list_desktops_impl()}


def switch_to_desktop_impl(target: DesktopRef) -> dict:
    _require()
    desktop = resolve_desktop(target)
    desktop.go()
    return get_current_desktop_impl()


def rename_desktop_impl(target: DesktopRef, new_name: str) -> dict:
    _require()
    # F4: reject empty / whitespace-only names.
    cleaned = new_name.strip()
    if not cleaned:
        raise ValueError(
            "desktop.name-empty: new_name must not be empty or whitespace-only"
        )
    # F5: reject names containing control characters.
    for c in cleaned:
        if unicodedata.category(c).startswith("C"):
            raise ValueError(
                f"desktop.name-control-chars: new_name contains control character {c!r}"
            )
    desktop = resolve_desktop(target)
    target_guid = str(desktop.id)
    # F3: reject names already used by a DIFFERENT desktop.
    all_desktops = pyvda.get_virtual_desktops()
    for i, d in enumerate(all_desktops):
        if str(d.id) == target_guid:
            continue  # Skip the target itself — renaming to own current name is allowed.
        if getattr(d, "name", None) == cleaned:
            raise ValueError(
                f"desktop.name-already-exists: name {cleaned!r} is already used by desktop at index {i}"
            )
    _rename(desktop, cleaned)
    desktops = pyvda.get_virtual_desktops()
    index = next(
        (i for i, d in enumerate(desktops) if str(d.id) == str(desktop.id)),
        0,
    )
    return _info(desktop, index, _current_guid())


# -- Pinning (cross-desktop visibility) -------------------------------------


def pin_window_all_desktops_impl(handle_id: str) -> dict:
    _require()
    tw = REGISTRY.require(handle_id)
    view = pyvda.AppView(hwnd=tw.hwnd)
    view.pin()
    return {"handle_id": handle_id, "window_pinned": bool(view.is_pinned())}


def unpin_window_impl(handle_id: str) -> dict:
    _require()
    tw = REGISTRY.require(handle_id)
    view = pyvda.AppView(hwnd=tw.hwnd)
    already_unpinned = not bool(view.is_pinned())
    view.unpin()
    return {
        "handle_id": handle_id,
        "window_pinned": bool(view.is_pinned()),
        "already_unpinned": already_unpinned,
    }


def pin_app_all_desktops_impl(handle_id: str) -> dict:
    """Pin all windows of this application's AUMID across all virtual desktops.

    WARNING: The OS ``IVirtualDesktopPinnedApps`` COM interface operates by
    AUMID (application user model ID), not by HWND.  Calling this function
    affects *every* open window of the same application, including those that
    are not managed by this session.  Use ``pin_window_all_desktops_impl`` for
    per-window pinning.
    """
    _require()
    tw = REGISTRY.require(handle_id)
    view = pyvda.AppView(hwnd=tw.hwnd)
    view.pin_app()
    return {
        "handle_id": handle_id,
        "app_pinned": bool(view.is_app_pinned()),
        "scope": "app",
        "warning": (
            "pin_app operates on the application's AUMID and affects ALL windows "
            "of this application, including those not managed by this session."
        ),
    }


def unpin_app_impl(handle_id: str) -> dict:
    """Unpin all windows of this application's AUMID from cross-desktop visibility.

    WARNING: The OS ``IVirtualDesktopPinnedApps`` COM interface operates by
    AUMID (application user model ID), not by HWND.  Calling this function
    affects *every* open window of the same application, including those that
    are not managed by this session.  Use ``unpin_window_impl`` for per-window
    unpinning.
    """
    _require()
    tw = REGISTRY.require(handle_id)
    view = pyvda.AppView(hwnd=tw.hwnd)
    already_unpinned = not bool(view.is_app_pinned())
    view.unpin_app()
    return {
        "handle_id": handle_id,
        "app_pinned": bool(view.is_app_pinned()),
        "scope": "app",
        "already_unpinned": already_unpinned,
        "warning": (
            "unpin_app operates on the application's AUMID and affects ALL windows "
            "of this application, including those not managed by this session."
        ),
    }


def is_pinned_impl(handle_id: str) -> dict:
    _require()
    tw = REGISTRY.require(handle_id)
    view = pyvda.AppView(hwnd=tw.hwnd)
    app_pinned = bool(view.is_app_pinned())
    # window_pinned is only True when the window itself is pinned via HWND
    # (view.pin()), NOT when the whole app is pinned via AUMID.  The OS
    # reports is_pinned() True in both cases, so we subtract the app-pin
    # contribution to get strict per-window semantics.
    window_pinned = bool(view.is_pinned()) and not app_pinned
    return {
        "handle_id": handle_id,
        "window_pinned": window_pinned,
        "app_pinned": app_pinned,
    }


def pin_state_for_hwnd(hwnd: int) -> tuple[Optional[bool], Optional[bool]]:
    """Return (window_pinned, app_pinned) for an HWND.

    Either field is None when pyvda is unavailable or the underlying call
    raises — callers should treat None as "unknown", not "false".
    """
    if pyvda is None:
        return (None, None)
    try:
        view = pyvda.AppView(hwnd=hwnd)
        raw_win_pinned = bool(view.is_pinned())
    except Exception as exc:  # noqa: BLE001
        log.debug("pin_state_for_hwnd(%s): is_pinned failed: %s", hwnd, exc)
        raw_win_pinned = None
    try:
        view = pyvda.AppView(hwnd=hwnd)
        app_pinned = bool(view.is_app_pinned())
    except Exception as exc:  # noqa: BLE001
        log.debug("pin_state_for_hwnd(%s): is_app_pinned failed: %s", hwnd, exc)
        app_pinned = None
    # Apply strict per-window semantics: window_pinned is only True when
    # pinned via HWND (view.pin()), not when the whole app-AUMID is pinned.
    # Guard against None from either path.
    if raw_win_pinned is None or app_pinned is None:
        win_pinned = raw_win_pinned
    else:
        win_pinned = raw_win_pinned and not app_pinned
    return (win_pinned, app_pinned)


def desktop_guid_for_hwnd(hwnd: int) -> Optional[str]:
    """Return the GUID of the desktop currently holding the given HWND."""
    _require()
    try:
        view = pyvda.AppView(hwnd=hwnd)
        return str(view.desktop.id)
    except Exception as exc:  # noqa: BLE001
        log.debug("desktop_guid_for_hwnd failed for %s: %s", hwnd, exc)
        return None


def move_hwnd_to_desktop(hwnd: int, desktop_ref: DesktopRef) -> str:
    """Move an HWND to the given desktop. Returns the new desktop GUID."""
    _require()
    desktop = resolve_desktop(desktop_ref)
    view = pyvda.AppView(hwnd=hwnd)
    view.move(desktop)
    return str(desktop.id)
