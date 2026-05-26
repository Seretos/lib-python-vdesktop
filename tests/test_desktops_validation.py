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


# ---------------------------------------------------------------------------
# Helpers for resolve_desktop and create_desktop_impl tests
# ---------------------------------------------------------------------------


def _make_fake_pyvda_with_create(desktops_list: list[FakeDesktop], current_index: int = 0):
    """Like _make_fake_pyvda but also exposes VirtualDesktop.create() for create_desktop_impl tests."""
    ns = types.SimpleNamespace()
    ns.get_virtual_desktops = lambda: list(desktops_list)

    class FakeVirtualDesktop:
        @staticmethod
        def current():
            return desktops_list[current_index]

        @staticmethod
        def create():
            new_d = FakeDesktop("")
            desktops_list.append(new_d)
            return new_d

    ns.VirtualDesktop = FakeVirtualDesktop
    return ns


# ---------------------------------------------------------------------------
# Bug 1 — synthesised fallback name resolution
# ---------------------------------------------------------------------------


def test_resolve_desktop_synthesised_name_first(monkeypatch):
    """Single desktop with falsy name; resolve_desktop('Desktop 1') must return it."""
    d0 = FakeDesktop("")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    result = desktops_mod.resolve_desktop("Desktop 1")
    assert result is d0


def test_resolve_desktop_synthesised_name_third(monkeypatch):
    """Three desktops; third has falsy name (effective 'Desktop 3'); must resolve."""
    d0 = FakeDesktop("Work")
    d1 = FakeDesktop("Play")
    d2 = FakeDesktop("")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0, d1, d2]))

    result = desktops_mod.resolve_desktop("Desktop 3")
    assert result is d2


def test_resolve_desktop_explicit_name_still_works(monkeypatch):
    """Control: explicit .name still resolves correctly (no regression)."""
    d0 = FakeDesktop("Work")
    d1 = FakeDesktop("Play")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0, d1]))

    assert desktops_mod.resolve_desktop("Play") is d1


# ---------------------------------------------------------------------------
# Bug 2 — GUID quote stripping
# ---------------------------------------------------------------------------


def test_resolve_desktop_guid_double_quoted(monkeypatch):
    """GUID wrapped in double quotes must resolve (quote chars stripped before comparison)."""
    guid_str = "afa42f05-1234-5678-abcd-000000000001"
    d0 = FakeDesktop("Work", guid=guid_str)
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    # str(uuid.UUID(guid_str)) == guid_str (no braces); wrap it in double quotes.
    result = desktops_mod.resolve_desktop(f'"{guid_str}"')
    assert result is d0


def test_resolve_desktop_guid_single_quoted(monkeypatch):
    """GUID wrapped in single quotes must resolve (quote chars stripped before comparison)."""
    guid_str = "afa42f05-1234-5678-abcd-000000000002"
    d0 = FakeDesktop("Work", guid=guid_str)
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    result = desktops_mod.resolve_desktop(f"'{guid_str}'")
    assert result is d0


def test_resolve_desktop_guid_unquoted_still_works(monkeypatch):
    """Bare GUID (without extra quotes) still resolves (no regression)."""
    guid_str = "afa42f05-1234-5678-abcd-000000000003"
    d0 = FakeDesktop("Work", guid=guid_str)
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    result = desktops_mod.resolve_desktop(guid_str)
    assert result is d0


# ---------------------------------------------------------------------------
# Bug 3 — duplicate-name guard in create_desktop_impl
# ---------------------------------------------------------------------------


def test_create_desktop_rejects_duplicate_explicit_name(monkeypatch):
    """create_desktop_impl must raise ValueError when name matches an existing explicit name."""
    d0 = FakeDesktop("Work")
    d1 = FakeDesktop("Play")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda_with_create([d0, d1]))

    with pytest.raises(ValueError, match="desktop.name-already-exists"):
        desktops_mod.create_desktop_impl("Play")


def test_create_desktop_rejects_duplicate_synthesised_name(monkeypatch):
    """create_desktop_impl must raise ValueError when name matches the synthesised 'Desktop N' name."""
    d0 = FakeDesktop("")  # effective name: "Desktop 1"
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda_with_create([d0]))

    with pytest.raises(ValueError, match="desktop.name-already-exists"):
        desktops_mod.create_desktop_impl("Desktop 1")


def test_create_desktop_unique_name_succeeds(monkeypatch):
    """create_desktop_impl with a unique name must not raise."""
    d0 = FakeDesktop("Work")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda_with_create([d0]))

    result = desktops_mod.create_desktop_impl("NewDesk")
    assert result["name"] == "NewDesk"


def test_create_desktop_no_name_succeeds(monkeypatch):
    """create_desktop_impl(name=None) must not raise even when an unnamed desktop exists."""
    d0 = FakeDesktop("")  # effective name "Desktop 1"
    desktops_list = [d0]
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda_with_create(desktops_list))

    result = desktops_mod.create_desktop_impl(name=None)
    # No name passed, so _rename is not called; effective name is synthesised.
    assert result is not None
    # The result dict must have the standard desktop info keys.
    assert "name" in result
    assert "guid" in result
    assert "index" in result
    # A new desktop was appended to the list.
    assert len(desktops_list) == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_resolve_desktop_unknown_reference_raises(monkeypatch):
    """Unmatched name still raises ValueError with 'Unknown desktop reference'."""
    d0 = FakeDesktop("Work")
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    with pytest.raises(ValueError, match="Unknown desktop reference"):
        desktops_mod.resolve_desktop("NonExistent")


def test_resolve_desktop_strip_whitespace_and_quotes_combined(monkeypatch):
    """Input with surrounding whitespace AND double quotes must still resolve."""
    guid_str = "afa42f05-1234-5678-abcd-000000000004"
    d0 = FakeDesktop("Work", guid=guid_str)
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    result = desktops_mod.resolve_desktop(f'  "{guid_str}"  ')
    assert result is d0


# ---------------------------------------------------------------------------
# Regression: Blocking finding 1 — quote-stripping must NOT affect name lookups
# ---------------------------------------------------------------------------


def test_resolve_desktop_name_with_embedded_quotes(monkeypatch):
    """Desktop whose .name literally contains surrounding quote chars must be
    reachable by passing the exact quoted name — quote-stripping must not
    corrupt the name comparison path.

    Regression for: resolve_desktop('"Ops"') stripping quotes then failing to
    match the desktop actually named '"Ops"' (with embedded quotes).
    """
    # The desktop's name really does start and end with double-quote characters.
    d0 = FakeDesktop('"Ops"')
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0]))

    result = desktops_mod.resolve_desktop('"Ops"')
    assert result is d0, (
        "resolve_desktop should match the explicit name '\"Ops\"' without stripping quotes"
    )


# ---------------------------------------------------------------------------
# Regression: Blocking finding 2 — explicit name beats synthesised fallback
# ---------------------------------------------------------------------------


def test_resolve_desktop_explicit_name_beats_synthesised_fallback(monkeypatch):
    """When desktop 0 has no name (effective 'Desktop 1') and desktop 1 has
    explicit name 'Desktop 1', resolve_desktop('Desktop 1') must return
    desktop 1 — the explicitly-named one.

    Regression for: the old single-pass loop returned desktop 0 first because
    it computed the effective fallback name and compared it before seeing the
    explicit match on desktop 1.
    """
    d0 = FakeDesktop("")          # no explicit name → synthesised "Desktop 1"
    guid1 = "00000000-0000-0000-0000-000000000099"
    d1 = FakeDesktop("Desktop 1", guid=guid1)  # explicit name "Desktop 1"
    monkeypatch.setattr(desktops_mod, "pyvda", _make_fake_pyvda([d0, d1]))

    result = desktops_mod.resolve_desktop("Desktop 1")
    assert result is d1, (
        "resolve_desktop('Desktop 1') should prefer the desktop with the explicit "
        "name 'Desktop 1' over the one whose synthesised fallback name is 'Desktop 1'"
    )
