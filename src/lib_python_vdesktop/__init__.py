"""lib-python-vdesktop — Windows virtual-desktop & window automation engine.

The reusable engine extracted from the agent-vdesktop MCP plugin. Drives
Microsoft Virtual Desktops (via pyvda/COM), window placement (Win32 +
DWM-shadow correction), monitor/layout computation, app launching, and a
handle-based tracking registry.

Primary entry point for consumers:

    >>> from lib_python_vdesktop import VDesktopManager
    >>> m = VDesktopManager()
    >>> m.list_desktops()
    >>> m.list_monitors()

Lower-level pieces (`compute_slots`, the `Registry`, individual `*_impl`
functions in the submodules) are also importable for advanced use.

Runtime is Windows-only (pyvda calls undocumented COM interfaces; several
modules touch `ctypes.windll` at import time). The pure modules — `layouts`,
`pathmap`, `tracking` — are platform-independent and unit-tested.
"""
from __future__ import annotations

from .layouts import LayoutSpec, compute_slots
from .manager import VDesktopManager
from .monitors import Monitor
from .tracking import REGISTRY, Registry, TrackedWindow

__version__ = "0.1.0"

__all__ = [
    "VDesktopManager",
    "Registry",
    "TrackedWindow",
    "REGISTRY",
    "Monitor",
    "LayoutSpec",
    "compute_slots",
    "__version__",
]
