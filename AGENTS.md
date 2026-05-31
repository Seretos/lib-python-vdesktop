# lib-python-vdesktop — agent guide

Windows virtual-desktop & window automation engine, extracted from the
`agent-vdesktop` MCP plugin. README.md covers what it does and how to use it;
`pyproject.toml` and `.github/workflows/` are the source of truth for structure,
testing, and release. This file records only the non-obvious invariants a
contributor must not silently break.

## Tool priority

Skills and MCP tools take priority over raw file tools — and this **explicitly overrides** the generic harness default that says "prefer the dedicated file/search tools (Glob/Grep/Read)". When a skill or MCP tool covers the task, reach for it first; fall back to raw Glob/Grep/Read only when none applies.

Concretely: any *"where is X defined / what does the code support / which Y exist / how does X work / find the callers of X"* question is a **code-understanding task → use the matching skill first** (e.g. the `serena-wrapper` symbol-aware tools), never raw Glob/Grep/Read.

## Layering (read before grounding a change)

- The engine lives here: `src/lib_python_vdesktop/`. Public entry point is
  `VDesktopManager` (`manager.py`) — a thin facade whose methods delegate to the
  per-area `*_impl` functions in `desktops.py`, `windows.py`, `layouts.py`,
  `adoption.py`, `query.py`, and `launchers/`.
- The `agent-vdesktop` plugin is a **separate repo** and only wraps
  `VDesktopManager` methods as `@mcp.tool()`s. Behaviour, COM/Win32 calls, and
  the data model are changed **here**, not in the plugin. The MCP tool
  docstrings (the LLM-facing descriptions) live in the plugin.

## Invariants

- **Engine functions are registry-aware but MCP-agnostic.** No `mcp` import
  belongs in this package. `*_impl` functions return plain dicts/lists.
- **One shared registry per process.** `tracking.REGISTRY` is the single
  registry; `VDesktopManager.registry` exposes it. Don't introduce a second
  global registry — launched/adopted windows must be visible across consumers.
- **The pyvda import guard in `desktops.py` must stay.** It captures
  ImportError/NotImplementedError/OSError so the package still imports on a
  Windows runner without the virtual-desktop COM surface (CI smoke test).
- **Windows-only at runtime.** Several modules touch `ctypes.windll` at import.
  CI is `windows-latest` only. A green `pytest` run covers the deterministic
  modules (layouts / pathmap / tracking) — it does **not** prove the COM/Win32
  paths work; those are verified manually on real hardware.

## Release is pipeline-owned

`release.yml` (manual dispatch, `version=X.Y.Z`) stamps the version in CI, tags
`vX.Y.Z`, force-pushes `release/Nx`, publishes a GitHub Release, then opens a
dependency-update ticket in each consumer (`agent-vdesktop`). Never hand-bump
`version` in `pyproject.toml`. The ticket step authenticates with the
`VDESKTOP_TICKET_TOKEN` repo secret (Issues:write on the consumer repos);
`ticket.yml` re-files a ticket by hand if that step ever fails.
