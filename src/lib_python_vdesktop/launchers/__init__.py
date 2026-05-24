"""App launchers — each module spawns a process, resolves its HWND, optionally
moves it to a target desktop and slot, then registers it in the tracking
registry. The shared pipeline lives in `_common.launch_and_register`."""
from __future__ import annotations
