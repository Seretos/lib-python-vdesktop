"""Tests for lib_python_vdesktop.adoption._classify — app-type detection from
window class + title.

Note: adoption transitively imports ctypes.windll, so these tests are
Windows-only. That matches the production CI runner."""
from __future__ import annotations

import pytest

from lib_python_vdesktop.adoption import _classify


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
