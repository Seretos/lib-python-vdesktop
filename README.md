# lib-python-vdesktop

Windows virtual-desktop & window automation engine for the Seretos agent-plugin
ecosystem. Bundles Microsoft Virtual Desktop control (via `pyvda` / undocumented
COM interfaces), Win32 window placement with DWM-shadow correction, monitor and
layout computation, app launchers (Chrome, Edge, Windows Terminal, VS Code, and a
generic fallback), WSL `↔` Windows path mapping, and an in-memory handle registry.

Extracted from the `agent-vdesktop` MCP plugin so the engine can be reused by any
Python program — a CLI, a service, a test harness — without pulling in the MCP
server. The plugin is now a thin wrapper that exposes this library's
`VDesktopManager` surface as MCP tools.

## Usage

```python
from lib_python_vdesktop import VDesktopManager

m = VDesktopManager()

# Virtual desktops
m.create_desktop(name="work")
m.list_desktops()
m.switch_to_desktop("work")

# Monitors & layouts
m.list_monitors()
m.apply_layout({"type": "preset", "name": "three-columns"})

# Launch an app into a slot on a desktop, then move it
res = m.launch_chrome(["https://example.com"], slot="left", desktop="work")
m.move_window(res["handle_id"], {"slot": "right"})
```

`VDesktopManager` operates on the process-wide tracking registry
(`lib_python_vdesktop.REGISTRY`, also reachable as `m.registry`): there is one
Windows session per process, so launched/adopted windows are shared across all
consumers in that process.

Lower-level pieces are importable directly — e.g.
`from lib_python_vdesktop import compute_slots, Registry, Monitor`, or the
per-area `*_impl` functions in `lib_python_vdesktop.{desktops,windows,layouts,...}`.

## Platform

Runtime is **Windows 11 only** — `pyvda` calls undocumented
`IVirtualDesktopManagerInternal` COM interfaces, and several modules touch
`ctypes.windll` at import time. The deterministic, platform-independent modules
(`layouts`, `pathmap`, `tracking`) are unit-tested; the COM/Win32 paths are
exercised manually on real hardware (a green `pytest` run does **not** prove the
COM paths work).

## Development

```
pip install -e ".[test]"
python -m pytest
```

## Releases & downstream consumers

Releases are a manual `release.yml` workflow dispatch (`version=X.Y.Z`); the
version is stamped in CI from the workflow input and never hand-bumped. Each
release produces a `vX.Y.Z` tag and a GitHub Release.

Downstream consumers pin an **exact tag** (`@vX.Y.Z`) for deterministic builds.
On every release, the pipeline opens a dependency-update ticket in the consuming
repo (today `agent-vdesktop`) so the bump is tracked rather than silently
floating. See `.github/workflows/release.yml`.
