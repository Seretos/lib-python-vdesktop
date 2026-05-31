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


# --- Regression: suffix-anchored classifier (ticket #24) ---------------------


def test_classify_chrome_page_about_vscode_is_chrome():
    """A Chrome window whose *page title* contains 'Visual Studio Code' mid-string
    must NOT be misclassified as vscode — only a title that ends with the suffix
    counts. Regression for the unanchored 'in' check bug."""
    title = "Visual Studio Code - Download - Google Chrome"
    assert _classify("Chrome_WidgetWin_1", title) == "chrome"


def test_classify_chrome_page_about_edge_is_chrome():
    """A Chrome window whose page title contains 'Microsoft Edge' mid-string
    must NOT be misclassified as edge."""
    title = "Microsoft Edge - Browser Download - Google Chrome"
    assert _classify("Chrome_WidgetWin_1", title) == "chrome"


def test_classify_vscode_suffix_still_detected():
    """A genuine VS Code window (title ends with '- Visual Studio Code') must
    still be classified as vscode after switching to endswith."""
    assert _classify("Chrome_WidgetWin_1", "myproj - src/foo.py - Visual Studio Code") == "vscode"


def test_classify_edge_suffix_still_detected():
    """A genuine Edge window (title ends with '- Microsoft Edge') must still
    be classified as edge after switching to endswith."""
    assert _classify("Chrome_WidgetWin_1", "GitHub - Microsoft Edge") == "edge"


def test_classify_edge_zero_width_space_suffix_still_detected():
    """Edge's zero-width-space variant in the suffix must still match."""
    title = "YouTube - Microsoft​ Edge"
    assert _classify("Chrome_WidgetWin_1", title) == "edge"


# --- Regression: VS Code Insiders suffix (ticket #24 follow-up) --------------


def test_classify_vscode_insiders():
    """A VS Code Insiders window (title ends with '- Visual Studio Code - Insiders')
    must be classified as vscode, not chrome. Regression for the missing Insiders
    suffix in the endswith check."""
    assert _classify("Chrome_WidgetWin_1", "myproj - Visual Studio Code - Insiders") == "vscode"


def test_classify_chrome_page_about_vscode_insiders_is_chrome():
    """A Chrome window whose page title contains 'Visual Studio Code - Insiders'
    mid-string (not as a suffix) must still classify as chrome, not vscode.
    Guards against re-introducing unanchored matching."""
    title = "Visual Studio Code - Insiders - Download - Google Chrome"
    assert _classify("Chrome_WidgetWin_1", title) == "chrome"


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
        with patch("lib_python_vdesktop.adoption.REGISTRY") as mock_registry:
            mock_registry.find_by_hwnd.return_value = fake_tw
            result = adopt_window_impl(12345)

    assert result == {"handle_id": "abcd1234", "already_tracked": True}
