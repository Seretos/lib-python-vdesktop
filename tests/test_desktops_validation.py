"""Tests for rename_desktop_impl input validation — F3, F4, F5.

All tests are pure Python / no pyvda / no COM — pyvda is replaced with a
minimal fake namespace whose get_virtual_desktops() returns configurable
FakeDesktop objects.
"""
from __future__ import annotations

import types
import uuid

import pytest

import lib_python_vdesktop.desktops as desktops_mod


# ---------------------------------------------------------------------------
# Minimal pyvda fake
# ---------------------------------------------------------------------------

class FakeDesktop:
    def __init__(self, name: str, guid: str | None = None):
        self.name = name
        self.id = uuid.UUID(guid) if guid else uuid.uuid4()

    def rename(self, new_name: str) -> None:  # noqa: D102
        self.name = new_name


def _make_fake_pyvda(desktops: list[FakeDesktop], current_index: int = 0):
    ns = types.SimpleNamespace()
    ns.get_virtual_desktops = lambda: list(desktops)

    class FakeVirtualDesktop:
        @staticmethod
        def current():
            return desktops[current_index]

    ns.VirtualDesktop = FakeVirtualDesktop
    return ns


# ---------------------------------------------------------------------------
# F4 — empty and whitespace-only names
# ---------------------------------------------------------------------------


def test_rename_rejects_empty_string(monkeypatch):
    """rename_desktop_impl must raise ValueError for an empty new_name."""
    d0 = FakeDesktop("Work")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    with pytest.raises(ValueError, match="desktop.name-empty"):
        desktops_mod.rename_desktop_impl(0, "")


def test_rename_rejects_whitespace_only(monkeypatch):
    """rename_desktop_impl must raise ValueError for whitespace-only new_name."""
    d0 = FakeDesktop("Work")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    with pytest.raises(ValueError, match="desktop.name-empty"):
        desktops_mod.rename_desktop_impl(0, "   ")


# ---------------------------------------------------------------------------
# F5 — control characters in names
# ---------------------------------------------------------------------------


def test_rename_rejects_newline(monkeypatch):
    """rename_desktop_impl must raise ValueError when new_name contains \\n."""
    d0 = FakeDesktop("Work")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    with pytest.raises(ValueError, match="desktop.name-control-chars"):
        desktops_mod.rename_desktop_impl(0, "Work\nEvil")


def test_rename_rejects_tab(monkeypatch):
    """rename_desktop_impl must raise ValueError when new_name contains \\t."""
    d0 = FakeDesktop("Work")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    with pytest.raises(ValueError, match="desktop.name-control-chars"):
        desktops_mod.rename_desktop_impl(0, "Work\tTabbed")


def test_rename_rejects_null_byte(monkeypatch):
    """rename_desktop_impl must raise ValueError when new_name contains \\x00."""
    d0 = FakeDesktop("Work")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    with pytest.raises(ValueError, match="desktop.name-control-chars"):
        desktops_mod.rename_desktop_impl(0, "Work\x00")


# ---------------------------------------------------------------------------
# F3 — duplicate name across desktops
# ---------------------------------------------------------------------------


def test_rename_rejects_duplicate_name(monkeypatch):
    """Renaming desktop 0 to 'Play' when desktop 1 is already named 'Play' must
    raise ValueError with 'desktop.name-already-exists'."""
    guid0 = "00000000-0000-0000-0000-000000000001"
    guid1 = "00000000-0000-0000-0000-000000000002"
    d0 = FakeDesktop("Work", guid=guid0)
    d1 = FakeDesktop("Play", guid=guid1)
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0, d1], current_index=0))

    with pytest.raises(ValueError, match="desktop.name-already-exists"):
        desktops_mod.rename_desktop_impl(0, "Play")


def test_rename_own_name_succeeds(monkeypatch):
    """Renaming a desktop to its own current name must NOT raise — it is a no-op."""
    guid0 = "00000000-0000-0000-0000-000000000001"
    d0 = FakeDesktop("Work", guid=guid0)
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0], current_index=0))

    # Should not raise.
    result = desktops_mod.rename_desktop_impl(0, "Work")
    assert result["name"] == "Work"


def test_rename_own_name_with_whitespace_succeeds(monkeypatch):
    """Renaming with leading/trailing whitespace that strips to the own name is allowed."""
    guid0 = "00000000-0000-0000-0000-000000000001"
    d0 = FakeDesktop("Work", guid=guid0)
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0], current_index=0))

    # " Work " strips to "Work", which is the desktop's own name — no conflict.
    result = desktops_mod.rename_desktop_impl(0, " Work ")
    assert result["name"] == "Work"
