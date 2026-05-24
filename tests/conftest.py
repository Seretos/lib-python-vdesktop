"""Shared pytest fixtures.

Note: `pythonpath = ["server"]` in pyproject lets tests import
`lib_python_vdesktop.*` without an install. Tests in this suite cover the pure-
Python, platform-independent modules; nothing here touches ctypes, pyvda,
or uiautomation.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass
class FakeMonitor:
    """Minimal Monitor-shaped object for layouts tests.

    The real `lib_python_vdesktop.monitors.Monitor` carries DPI, primary flag,
    handle, etc. — for slot-bounds computation only `work_area` and `index`
    matter.
    """
    index: int
    work_area: dict


@pytest.fixture
def primary_monitor() -> FakeMonitor:
    """A 1920x1080 primary monitor whose work area starts at (0, 0)."""
    return FakeMonitor(
        index=0,
        work_area={"x": 0, "y": 0, "w": 1920, "h": 1080},
    )


@pytest.fixture
def secondary_monitor() -> FakeMonitor:
    """A 2560x1440 second monitor to the right of the primary one."""
    return FakeMonitor(
        index=1,
        work_area={"x": 1920, "y": 0, "w": 2560, "h": 1440},
    )
