"""Tests for F7: invalid regex in find_window_by_title_impl and
find_chrome_tab_impl surfaces the argument name in the error message.

Both functions are tested with an invalid regex pattern.  The EnumWindows
Win32 call and uiautomation are not invoked in these tests — the ValueError
is raised before any OS interaction.
"""
from __future__ import annotations

import types

import pytest

import lib_python_vdesktop.query as query_mod


# ---------------------------------------------------------------------------
# find_window_by_title_impl — invalid regex raises ValueError before
# EnumWindows is called.
# ---------------------------------------------------------------------------


def test_find_window_by_title_invalid_regex(monkeypatch):
    """Passing regex=True with an invalid pattern must raise ValueError containing
    'pattern' in the message before any Win32 call."""
    # Monkeypatch EnumWindows as a no-op — it must NOT be reached.
    call_log: list[str] = []

    def spy_enum(proc, lparam):
        call_log.append("EnumWindows called")

    monkeypatch.setattr(query_mod._user32, "EnumWindows", spy_enum)
    # Also stub pyvda-dependent helpers so no COM calls happen if the code
    # somehow reaches them.
    import lib_python_vdesktop.desktops as desktops_mod
    monkeypatch.setattr(desktops_mod, "pyvda", None)

    with pytest.raises(ValueError, match="pattern"):
        query_mod.find_window_by_title_impl("[invalid", regex=True)

    assert call_log == [], "EnumWindows must not be called when regex is invalid"


def test_find_window_by_title_invalid_regex_message_detail(monkeypatch):
    """The ValueError message must mention 'invalid regex'."""
    monkeypatch.setattr(query_mod._user32, "EnumWindows", lambda *a: None)

    with pytest.raises(ValueError, match="invalid regex"):
        query_mod.find_window_by_title_impl("[bad", regex=True)


def test_find_window_by_title_valid_regex_no_error(monkeypatch):
    """A valid regex must not raise — EnumWindows gets called (or returns empty)."""
    # Monkeypatch EnumWindows to be a no-op; no windows will be enumerated.
    monkeypatch.setattr(query_mod._user32, "EnumWindows", lambda proc, lp: None)
    import lib_python_vdesktop.desktops as desktops_mod
    monkeypatch.setattr(desktops_mod, "pyvda", None)

    result = query_mod.find_window_by_title_impl("\\w+", regex=True)
    assert result == []


# ---------------------------------------------------------------------------
# find_chrome_tab_impl — invalid regex raises ValueError before UIA access.
# ---------------------------------------------------------------------------


def test_find_chrome_tab_invalid_regex(monkeypatch):
    """find_chrome_tab_impl with regex=True and an invalid pattern must raise
    ValueError containing 'pattern' — before importing uiautomation."""
    # Prevent the real uiautomation import from running.
    # We do this by patching the import inside find_chrome_tab_impl:
    # the easiest approach is to provide a fake uiautomation module.
    fake_uia = types.SimpleNamespace()
    fake_uia.GetRootControl = lambda: types.SimpleNamespace(GetChildren=lambda: [])
    import sys
    monkeypatch.setitem(sys.modules, "uiautomation", fake_uia)

    with pytest.raises(ValueError, match="pattern"):
        query_mod.find_chrome_tab_impl("[invalid", regex=True)


def test_find_chrome_tab_invalid_regex_message_detail(monkeypatch):
    """The ValueError message from find_chrome_tab_impl must mention 'invalid regex'."""
    fake_uia = types.SimpleNamespace()
    fake_uia.GetRootControl = lambda: types.SimpleNamespace(GetChildren=lambda: [])
    import sys
    monkeypatch.setitem(sys.modules, "uiautomation", fake_uia)

    with pytest.raises(ValueError, match="invalid regex"):
        query_mod.find_chrome_tab_impl("[bad", regex=True)
