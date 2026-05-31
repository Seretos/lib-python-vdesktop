"""Tests for lib_python_vdesktop.adoption._classify — app-type detection from
window class + title, and adopt_window_impl HWND validation.

Note: adoption transitively imports ctypes.windll, so these tests are
Windows-only. That matches the production CI runner."""
from __future__ import annotations
from unittest.mock import MagicMock, patch

import pytest

from lib_python_vdesktop.adoption import _classify, adopt_window_impl
from lib_python_vdesktop.tracking import TrackedWindow


@pytest.mark.parametrize("title", [
    "GitHub - Google Chrome",
    "vdesktop-plugin – src/ - Visual Studio Code",  # vscode (still chrome-class)
    "Search results - Google Chrome",
])
def test_classify_chrome_widget_default(title):
    # Anything that isn't VS Code or Edge under Chrome_WidgetWin_1 is Chrome.
    if "Visual Studio Code" in title:
        assert _classify("Chrome_WidgetWin_1", title) == "vscode"
    else:
        assert _classify("Chrome_WidgetWin_1", title) == "chrome"


def test_classify_vscode():
    assert _classify("Chrome_WidgetWin_1", "myproj - Visual Studio Code") == "vscode"


def test_classify_edge_plain():
    assert _classify("Chrome_WidgetWin_1", "YouTube - Microsoft Edge") == "edge"


def test_classify_edge_with_zero_width_space():
    # Edge sometimes renders the title with a zero-width space between
    # "Microsoft" and "Edge". _classify strips ZWSPs so detection still works.
    title = "YouTube - Microsoft​ Edge"
    assert _classify("Chrome_WidgetWin_1", title) == "edge"


def test_classify_edge_case_insensitive():
    assert _classify("Chrome_WidgetWin_1", "page - MICROSOFT EDGE") == "edge"


def test_classify_terminal():
    assert _classify("CASCADIA_HOSTING_WINDOW_CLASS", "PowerShell") == "terminal"


def test_classify_terminal_case_insensitive():
    assert _classify("cascadia_hosting_window_class", "anything") == "terminal"


def test_classify_unknown_class():
    assert _classify("Notepad", "Untitled - Notepad") == "unknown"


def test_classify_unknown_with_chrome_in_title_only():
    # Title alone shouldn't fool us — class is required.
    assert _classify("Notepad", "fake Google Chrome") == "unknown"


# --- adopt_window_impl HWND validation ---------------------------------------


def test_adopt_window_rejects_invalid_hwnd():
    """Regression: adopt_window_impl must raise ValueError for a bogus HWND
    instead of registering a phantom entry in the registry."""
    with patch("lib_python_vdesktop._win32_helpers._user32") as mock_user32:
        mock_user32.IsWindow.return_value = 0
        with pytest.raises(ValueError, match="99999999"):
            adopt_window_impl(99999999)


def test_adopt_window_accepts_valid_hwnd_already_tracked():
    """When IsWindow returns truthy and the HWND is already tracked,
    adopt_window_impl returns the already-tracked result without raising."""
    fake_tw = TrackedWindow(
        handle_id="abcd1234",
        hwnd=12345,
        pid=999,
        app_type="chrome",
        label="my-window",
        desktop_guid="guid-x",
        bounds={"x": 0, "y": 0, "w": 100, "h": 100},
        title="Test Window",
    )
    with patch("lib_python_vdesktop._win32_helpers._user32") as mock_user32:
        mock_user32.IsWindow.return_value = 1
        with patch("lib_python_vdesktop._win32_helpers._kernel32") as mock_kernel32:
            mock_kernel32.GetConsoleWindow.return_value = 0  # no console window
            with patch("lib_python_vdesktop.adoption.REGISTRY") as mock_registry:
                mock_registry.find_by_hwnd.return_value = fake_tw
                result = adopt_window_impl(12345)

    assert result == {"handle_id": "abcd1234", "already_tracked": True}


# --- Issue 1: console window guard -------------------------------------------


def test_adopt_window_rejects_console_hwnd():
    """Regression (#25 Issue 1): adopt_window_impl must raise ValueError when the
    target hwnd equals the process console window."""
    with patch("lib_python_vdesktop._win32_helpers._user32") as mock_user32:
        mock_user32.IsWindow.return_value = 1
        with patch("lib_python_vdesktop._win32_helpers._kernel32") as mock_kernel32:
            mock_kernel32.GetConsoleWindow.return_value = 12345
            with pytest.raises(ValueError, match="console"):
                adopt_window_impl(12345)


def test_adopt_window_console_returns_zero_no_raise():
    """Edge (#25 Issue 1): when GetConsoleWindow returns 0 (no console), adoption
    of a valid non-tracked hwnd must NOT raise a ValueError for the console guard."""
    with patch("lib_python_vdesktop._win32_helpers._user32") as mock_user32:
        mock_user32.IsWindow.return_value = 1
        with patch("lib_python_vdesktop._win32_helpers._kernel32") as mock_kernel32:
            mock_kernel32.GetConsoleWindow.return_value = 0
            with patch("lib_python_vdesktop.adoption.REGISTRY") as mock_registry:
                with patch("lib_python_vdesktop.adoption.desktops_mod"):
                    with patch("lib_python_vdesktop.adoption.get_window_title", return_value="T"):
                        with patch("lib_python_vdesktop.adoption.get_window_classname", return_value="Cls"):
                            with patch("lib_python_vdesktop.adoption.get_window_rect", return_value={"x": 0, "y": 0, "w": 100, "h": 100}):
                                with patch("lib_python_vdesktop.adoption.get_window_pid", return_value=1):
                                    mock_registry.find_by_hwnd.return_value = None
                                    fake_tw = TrackedWindow(
                                        handle_id="new1",
                                        hwnd=99,
                                        pid=1,
                                        app_type="unknown",
                                        label=None,
                                        desktop_guid=None,
                                        bounds={"x": 0, "y": 0, "w": 100, "h": 100},
                                        title="T",
                                    )
                                    mock_registry.register.return_value = fake_tw
                                    # Should not raise
                                    result = adopt_window_impl(99)
                                    assert result["handle_id"] == "new1"


def test_adopt_window_console_different_hwnd_no_raise():
    """Edge (#25 Issue 1): console hwnd differs from target → no false positive,
    adoption proceeds normally."""
    fake_tw = TrackedWindow(
        handle_id="abcd5678",
        hwnd=99,
        pid=1,
        app_type="unknown",
        label=None,
        desktop_guid=None,
        bounds={"x": 0, "y": 0, "w": 100, "h": 100},
        title="T",
    )
    with patch("lib_python_vdesktop._win32_helpers._user32") as mock_user32:
        mock_user32.IsWindow.return_value = 1
        with patch("lib_python_vdesktop._win32_helpers._kernel32") as mock_kernel32:
            # Console is a different HWND (12345) than the target (99).
            mock_kernel32.GetConsoleWindow.return_value = 12345
            with patch("lib_python_vdesktop.adoption.REGISTRY") as mock_registry:
                mock_registry.find_by_hwnd.return_value = fake_tw
                result = adopt_window_impl(99)
    assert result == {"handle_id": "abcd5678", "already_tracked": True}


# --- Issue 2: idempotency — no relabel on already-tracked --------------------


def test_adopt_window_already_tracked_does_not_relabel():
    """Regression (#25 Issue 2): calling adopt_window_impl with a new label on an
    already-tracked HWND must NOT relabel the registry entry."""
    from lib_python_vdesktop.tracking import Registry

    r = Registry()
    tw = r.register(
        hwnd=55555,
        pid=1,
        app_type="chrome",
        label="original",
        desktop_guid=None,
        bounds={"x": 0, "y": 0, "w": 100, "h": 100},
        title="W",
    )

    with patch("lib_python_vdesktop._win32_helpers._user32") as mock_user32:
        mock_user32.IsWindow.return_value = 1
        with patch("lib_python_vdesktop._win32_helpers._kernel32") as mock_kernel32:
            mock_kernel32.GetConsoleWindow.return_value = 0
            with patch("lib_python_vdesktop.adoption.REGISTRY", r):
                result = adopt_window_impl(55555, label="new")

    assert result == {"handle_id": tw.handle_id, "already_tracked": True}
    # Label must still be the original value — no silent relabelling.
    assert r.get(tw.handle_id).label == "original"


# --- Issue 1 (regression): 64-bit HWND truncation guard ---------------------


def test_adopt_window_rejects_console_hwnd_64bit():
    """Regression (#25 restype fix): GetConsoleWindow must return the full 64-bit
    HWND. If restype were left as c_long the value 0x1_0000_1234 would be
    truncated to 0x1234 (lower 32 bits sign-extended), and the console guard
    `console_hwnd == int(hwnd)` would silently miss, letting the console window
    be adopted. With restype=c_void_p the full value is preserved and the guard
    fires correctly."""
    large_hwnd = 0x1_0000_1234
    with patch("lib_python_vdesktop._win32_helpers._user32") as mock_user32:
        mock_user32.IsWindow.return_value = 1
        with patch("lib_python_vdesktop._win32_helpers._kernel32") as mock_kernel32:
            # Simulate GetConsoleWindow returning a value that exceeds 32-bit range.
            # With c_void_p restype ctypes passes this through as a full Python int.
            mock_kernel32.GetConsoleWindow.return_value = large_hwnd
            with pytest.raises(ValueError, match="console"):
                adopt_window_impl(large_hwnd)
