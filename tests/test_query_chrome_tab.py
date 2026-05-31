"""Tests for the no-side-effect fix to find_chrome_tab_impl (ticket #24).

Verifies:
- Pure query: REGISTRY.register is never called, regardless of whether the
  window is already tracked or not.
- handle_id is None for untracked windows, correct value for tracked ones.
- VS Code and Edge windows (Chrome_WidgetWin_1 class) are excluded by _classify.
- Empty pattern raises ValueError before any UIA enumeration.
- Fallback (tab-strip enumeration failure) path also never calls register.
"""
from __future__ import annotations

import sys
import types
import unittest.mock as mock

import pytest

import lib_python_vdesktop.query as query_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHROME_CLASS = "Chrome_WidgetWin_1"


def _make_fake_window(class_name: str, title: str, hwnd: int = 1001):
    """Return a SimpleNamespace that looks like a uiautomation control."""
    win = types.SimpleNamespace(
        ClassName=class_name,
        Name=title,
        NativeWindowHandle=hwnd,
    )

    def tab_control():
        raise LookupError("no tab strip (test stub)")

    win.TabControl = tab_control
    return win


def _make_fake_window_with_tabs(class_name: str, title: str, tab_titles: list[str], hwnd: int = 1001):
    """Return a fake window whose TabControl exposes the given tab titles."""
    win = types.SimpleNamespace(
        ClassName=class_name,
        Name=title,
        NativeWindowHandle=hwnd,
    )

    tab_children = [
        types.SimpleNamespace(Name=t) for t in tab_titles
    ]

    tab_strip = types.SimpleNamespace(
        GetChildren=lambda: tab_children,
    )
    tab_strip.Exists = lambda *a: True

    win.TabControl = lambda: tab_strip
    return win


def _make_fake_uia(windows: list):
    """Return a fake uiautomation module whose GetRootControl yields `windows`."""
    root = types.SimpleNamespace(GetChildren=lambda: windows)
    fake_uia = types.SimpleNamespace(GetRootControl=lambda: root)
    return fake_uia


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_find_chrome_tab_does_not_register_untracked_window(monkeypatch):
    """Matching Chrome window where find_by_hwnd returns None: register must
    never be called and result must have handle_id=None."""
    chrome_win = _make_fake_window_with_tabs(
        CHROME_CLASS, "Python docs - Google Chrome", ["Python docs"], hwnd=2001
    )
    monkeypatch.setitem(sys.modules, "uiautomation", _make_fake_uia([chrome_win]))

    monkeypatch.setattr(query_mod.REGISTRY, "find_by_hwnd", lambda hwnd: None)
    mock_register = mock.MagicMock()
    monkeypatch.setattr(query_mod.REGISTRY, "register", mock_register)

    results = query_mod.find_chrome_tab_impl("Python docs")

    assert len(results) == 1
    assert results[0]["handle_id"] is None
    assert results[0]["hwnd"] == 2001
    mock_register.assert_not_called()


def test_find_chrome_tab_returns_handle_id_for_tracked_window(monkeypatch):
    """Matching Chrome window already in registry: handle_id from tracked
    window is returned and register is never called."""
    chrome_win = _make_fake_window_with_tabs(
        CHROME_CLASS, "GitHub - Google Chrome", ["GitHub"], hwnd=3001
    )
    monkeypatch.setitem(sys.modules, "uiautomation", _make_fake_uia([chrome_win]))

    fake_tracked = types.SimpleNamespace(handle_id="win-42", label="my-browser")
    monkeypatch.setattr(query_mod.REGISTRY, "find_by_hwnd", lambda hwnd: fake_tracked)
    mock_register = mock.MagicMock()
    monkeypatch.setattr(query_mod.REGISTRY, "register", mock_register)

    results = query_mod.find_chrome_tab_impl("GitHub")

    assert len(results) == 1
    assert results[0]["handle_id"] == "win-42"
    mock_register.assert_not_called()


def test_find_chrome_tab_excludes_vscode_window(monkeypatch):
    """A Chrome_WidgetWin_1 window titled '... - Visual Studio Code' must be
    excluded; a genuine Chrome window must still appear."""
    vscode_win = _make_fake_window_with_tabs(
        CHROME_CLASS, "query.py - Visual Studio Code", ["query.py - Visual Studio Code"], hwnd=4001
    )
    chrome_win = _make_fake_window_with_tabs(
        CHROME_CLASS, "Python docs - Google Chrome", ["Python docs"], hwnd=4002
    )
    monkeypatch.setitem(sys.modules, "uiautomation", _make_fake_uia([vscode_win, chrome_win]))

    monkeypatch.setattr(query_mod.REGISTRY, "find_by_hwnd", lambda hwnd: None)
    monkeypatch.setattr(query_mod.REGISTRY, "register", mock.MagicMock())

    results = query_mod.find_chrome_tab_impl("Python")

    hwnds = [r["hwnd"] for r in results]
    assert 4002 in hwnds, "genuine Chrome window must match"
    assert 4001 not in hwnds, "VS Code window must be excluded"


def test_find_chrome_tab_excludes_edge_window(monkeypatch):
    """A Chrome_WidgetWin_1 window titled '... - Microsoft Edge' must be
    excluded."""
    edge_win = _make_fake_window_with_tabs(
        CHROME_CLASS, "GitHub - Microsoft Edge", ["GitHub"], hwnd=5001
    )
    chrome_win = _make_fake_window_with_tabs(
        CHROME_CLASS, "GitHub - Google Chrome", ["GitHub"], hwnd=5002
    )
    monkeypatch.setitem(sys.modules, "uiautomation", _make_fake_uia([edge_win, chrome_win]))

    monkeypatch.setattr(query_mod.REGISTRY, "find_by_hwnd", lambda hwnd: None)
    monkeypatch.setattr(query_mod.REGISTRY, "register", mock.MagicMock())

    results = query_mod.find_chrome_tab_impl("GitHub")

    hwnds = [r["hwnd"] for r in results]
    assert 5002 in hwnds, "genuine Chrome window must match"
    assert 5001 not in hwnds, "Edge window must be excluded"


def test_find_chrome_tab_empty_pattern_raises(monkeypatch):
    """find_chrome_tab_impl('') must raise ValueError with 'pattern' in the
    message before any UIA enumeration."""
    call_log: list[str] = []

    fake_uia = types.SimpleNamespace(
        GetRootControl=lambda: (_ for _ in ()).throw(
            AssertionError("GetRootControl must not be called for empty pattern")
        )
    )
    # Use a sentinel that will error if called
    def failing_get_root():
        call_log.append("GetRootControl called")
        return types.SimpleNamespace(GetChildren=lambda: [])

    fake_uia2 = types.SimpleNamespace(GetRootControl=failing_get_root)
    monkeypatch.setitem(sys.modules, "uiautomation", fake_uia2)

    with pytest.raises(ValueError, match="pattern"):
        query_mod.find_chrome_tab_impl("")

    assert call_log == [], "GetRootControl must not be called for empty pattern"


def test_find_chrome_tab_empty_regex_raises(monkeypatch):
    """find_chrome_tab_impl('', regex=True) must also raise ValueError."""
    call_log: list[str] = []

    def failing_get_root():
        call_log.append("GetRootControl called")
        return types.SimpleNamespace(GetChildren=lambda: [])

    fake_uia = types.SimpleNamespace(GetRootControl=failing_get_root)
    monkeypatch.setitem(sys.modules, "uiautomation", fake_uia)

    with pytest.raises(ValueError, match="pattern"):
        query_mod.find_chrome_tab_impl("", regex=True)

    assert call_log == [], "GetRootControl must not be called for empty pattern"


def test_find_chrome_tab_includes_chrome_window_with_vscode_page_title(monkeypatch):
    """Regression #24: a Chrome window whose page title contains 'Visual Studio Code'
    mid-string (e.g. 'Visual Studio Code - Download - Google Chrome') must NOT be
    excluded by _classify.  The old unanchored 'in' check would drop it silently."""
    chrome_win = _make_fake_window_with_tabs(
        CHROME_CLASS,
        "Visual Studio Code - Download - Google Chrome",
        ["Visual Studio Code - Download"],
        hwnd=7001,
    )
    monkeypatch.setitem(sys.modules, "uiautomation", _make_fake_uia([chrome_win]))
    monkeypatch.setattr(query_mod.REGISTRY, "find_by_hwnd", lambda hwnd: None)
    monkeypatch.setattr(query_mod.REGISTRY, "register", mock.MagicMock())

    results = query_mod.find_chrome_tab_impl("Visual Studio Code - Download")

    hwnds = [r["hwnd"] for r in results]
    assert 7001 in hwnds, (
        "Chrome window titled about VS Code must be included, not silently dropped"
    )


def test_find_chrome_tab_includes_chrome_window_with_edge_page_title(monkeypatch):
    """Regression #24: a Chrome window whose page title contains 'Microsoft Edge'
    mid-string must NOT be excluded by _classify."""
    chrome_win = _make_fake_window_with_tabs(
        CHROME_CLASS,
        "Microsoft Edge - Browser Download - Google Chrome",
        ["Microsoft Edge - Browser Download"],
        hwnd=7002,
    )
    monkeypatch.setitem(sys.modules, "uiautomation", _make_fake_uia([chrome_win]))
    monkeypatch.setattr(query_mod.REGISTRY, "find_by_hwnd", lambda hwnd: None)
    monkeypatch.setattr(query_mod.REGISTRY, "register", mock.MagicMock())

    results = query_mod.find_chrome_tab_impl("Microsoft Edge - Browser")

    hwnds = [r["hwnd"] for r in results]
    assert 7002 in hwnds, (
        "Chrome window titled about Edge must be included, not silently dropped"
    )


def test_find_chrome_tab_fallback_no_register(monkeypatch):
    """When UIA tab enumeration fails (fallback to window-title match),
    register must never be called and handle_id must be None for untracked."""
    # _make_fake_window raises LookupError from TabControl — triggers fallback
    chrome_win = _make_fake_window(
        CHROME_CLASS, "Python - Google Chrome", hwnd=6001
    )
    monkeypatch.setitem(sys.modules, "uiautomation", _make_fake_uia([chrome_win]))

    monkeypatch.setattr(query_mod.REGISTRY, "find_by_hwnd", lambda hwnd: None)
    mock_register = mock.MagicMock()
    monkeypatch.setattr(query_mod.REGISTRY, "register", mock_register)

    results = query_mod.find_chrome_tab_impl("Python")

    assert len(results) == 1
    assert results[0]["hwnd"] == 6001
    assert results[0]["handle_id"] is None
    assert results[0]["tab_index"] == -1
    mock_register.assert_not_called()
