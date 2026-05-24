"""High-level facade over the vdesktop engine.

`VDesktopManager` is the single entry point for non-MCP consumers (scripts,
CLIs, other services). Every method maps 1:1 to an engine operation and returns
plain dicts/lists — no MCP or COM types leak out. The MCP plugin wraps these
same methods as `@mcp.tool()`s.

The manager operates on the process-wide tracking registry (`tracking.REGISTRY`)
exposed as ``self.registry``; there is one Windows session per process, so a
shared registry is the correct model. Launched/adopted windows registered via
one consumer are visible to every other consumer in the same process.
"""
from __future__ import annotations

from typing import Optional, Union

from . import adoption, desktops, layouts, query, windows
from .launchers import chrome, edge, generic, terminal, vscode
from .layouts import LayoutSpec
from .tracking import REGISTRY, Registry

DesktopRef = Union[int, str]


class VDesktopManager:
    """Facade bundling virtual-desktop, window, layout and launcher operations."""

    def __init__(self) -> None:
        self.registry: Registry = REGISTRY

    # -- desktops -----------------------------------------------------------

    def list_desktops(self) -> list[dict]:
        return desktops.list_desktops_impl()

    def get_current_desktop(self) -> dict:
        return desktops.get_current_desktop_impl()

    def create_desktop(self, name: Optional[str] = None) -> dict:
        return desktops.create_desktop_impl(name)

    def delete_desktop(
        self, target: DesktopRef, fallback_desktop: Optional[DesktopRef] = None
    ) -> dict:
        return desktops.delete_desktop_impl(target, fallback_desktop)

    def switch_to_desktop(self, target: DesktopRef) -> dict:
        return desktops.switch_to_desktop_impl(target)

    def rename_desktop(self, target: DesktopRef, new_name: str) -> dict:
        return desktops.rename_desktop_impl(target, new_name)

    def pin_window_all_desktops(self, handle_id: str) -> dict:
        return desktops.pin_window_all_desktops_impl(handle_id)

    def unpin_window(self, handle_id: str) -> dict:
        return desktops.unpin_window_impl(handle_id)

    def pin_app_all_desktops(self, handle_id: str) -> dict:
        return desktops.pin_app_all_desktops_impl(handle_id)

    def unpin_app(self, handle_id: str) -> dict:
        return desktops.unpin_app_impl(handle_id)

    def is_pinned(self, handle_id: str) -> dict:
        return desktops.is_pinned_impl(handle_id)

    # -- windows ------------------------------------------------------------

    def list_windows(
        self,
        desktop: Optional[DesktopRef] = None,
        include_unmanaged: bool = False,
    ) -> list[dict]:
        return windows.list_windows_impl(desktop, include_unmanaged)

    def move_window(self, handle_id: str, target: dict) -> dict:
        return windows.move_window_impl(handle_id, target)

    def resize_window(self, handle_id: str, bounds: dict) -> dict:
        return windows.resize_window_impl(handle_id, bounds)

    def close_window(self, handle_id: str, force: bool = False) -> dict:
        return windows.close_window_impl(handle_id, force)

    def focus_window(self, handle_id: str) -> dict:
        return windows.focus_window_impl(handle_id)

    def relabel_window(self, handle_id: str, new_label: Optional[str]) -> dict:
        return windows.relabel_window_impl(handle_id, new_label)

    def minimize_window(self, handle_id: str) -> dict:
        return windows.minimize_window_impl(handle_id)

    def maximize_window(self, handle_id: str) -> dict:
        return windows.maximize_window_impl(handle_id)

    def restore_window(self, handle_id: str) -> dict:
        return windows.restore_window_impl(handle_id)

    # -- layouts / monitors -------------------------------------------------

    def list_monitors(self) -> list[dict]:
        return layouts.list_monitors_impl()

    def list_layout_presets(self) -> list[dict]:
        return layouts.list_layout_presets_impl()

    def compute_layout(self, spec: LayoutSpec) -> list[dict]:
        return layouts.compute_slots(spec)

    def apply_layout(
        self, spec: LayoutSpec, target_desktop: Optional[DesktopRef] = None
    ) -> list[dict]:
        return layouts.apply_layout_impl(spec, target_desktop)

    # -- launchers ----------------------------------------------------------

    def launch_chrome(
        self,
        urls: list[str],
        slot: Optional[str] = None,
        desktop: Optional[DesktopRef] = None,
        label: Optional[str] = None,
        new_user_data_dir: bool = True,
        incognito: bool = False,
    ) -> dict:
        return chrome.launch_chrome_impl(
            urls, slot, desktop, label, new_user_data_dir, incognito
        )

    def launch_edge(
        self,
        urls: list[str],
        slot: Optional[str] = None,
        desktop: Optional[DesktopRef] = None,
        label: Optional[str] = None,
        new_user_data_dir: bool = True,
        inprivate: bool = False,
    ) -> dict:
        return edge.launch_edge_impl(
            urls, slot, desktop, label, new_user_data_dir, inprivate
        )

    def launch_terminal(
        self,
        tabs: list[dict],
        slot: Optional[str] = None,
        desktop: Optional[DesktopRef] = None,
        label: Optional[str] = None,
        window_title: Optional[str] = None,
    ) -> dict:
        return terminal.launch_terminal_impl(tabs, slot, desktop, label, window_title)

    def launch_vscode(
        self,
        folder: str,
        files: Optional[list[dict]] = None,
        slot: Optional[str] = None,
        desktop: Optional[DesktopRef] = None,
        label: Optional[str] = None,
        reuse_window: bool = False,
    ) -> dict:
        return vscode.launch_vscode_impl(
            folder, files, slot, desktop, label, reuse_window
        )

    def launch_app(
        self,
        executable: str,
        args: Optional[list[str]] = None,
        cwd: Optional[str] = None,
        slot: Optional[str] = None,
        desktop: Optional[DesktopRef] = None,
        label: Optional[str] = None,
        identification: Optional[dict] = None,
    ) -> dict:
        return generic.launch_app_impl(
            executable, args, cwd, slot, desktop, label, identification
        )

    # -- adoption / query ---------------------------------------------------

    def list_unmanaged_windows(self, desktop: Optional[DesktopRef] = None) -> list[dict]:
        desktop_guid: Optional[str] = None
        if desktop is not None:
            desktop_guid = str(desktops.resolve_desktop(desktop).id)
        return adoption.list_unmanaged_windows_impl(desktop_guid)

    def adopt_window(
        self,
        hwnd: int,
        label: Optional[str] = None,
        app_type_hint: Optional[str] = None,
    ) -> dict:
        return adoption.adopt_window_impl(hwnd, label, app_type_hint)

    def release_window(self, handle_id: str) -> dict:
        return adoption.release_window_impl(handle_id)

    def find_window_by_title(
        self,
        pattern: str,
        desktop: Optional[DesktopRef] = None,
        regex: bool = False,
    ) -> list[dict]:
        return query.find_window_by_title_impl(pattern, desktop, regex)

    def find_chrome_tab(self, pattern: str, regex: bool = False) -> list[dict]:
        return query.find_chrome_tab_impl(pattern, regex)
