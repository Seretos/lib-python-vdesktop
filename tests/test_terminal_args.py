"""Tests for lib_python_vdesktop.launchers.terminal — pure argv builders.

Note: terminal.py transitively imports ctypes.windll via _common, so these
tests are Windows-only (they cannot run on Linux/macOS). That's the expected
CI environment for this project.
"""
from __future__ import annotations

import pytest

from lib_python_vdesktop.launchers import terminal as terminal_mod
from lib_python_vdesktop.launchers.terminal import (
    _shell_command_tokens,
    _tab_args,
    _validate_safe_name,
    build_wt_args,
)


# --- _validate_safe_name -----------------------------------------------------


@pytest.mark.parametrize("name", [
    "Ubuntu",
    "Ubuntu-22.04",
    "My Profile",
    "PowerShell",
    "name_with_underscore",
    "with.dots",
    "x",  # one char
])
def test_validate_safe_name_accepts_normal_identifiers(name):
    _validate_safe_name(name, "field")  # must not raise


@pytest.mark.parametrize("name", [
    "; rm -rf /",
    "Ubuntu; whoami",
    'bad"quote',
    "with'quote",
    "back`tick",
    "$(echo pwned)",
    "with/slash",
    "with\\backslash",
    "",            # empty
    "a" * 129,     # too long
])
def test_validate_safe_name_rejects_dangerous(name):
    with pytest.raises(ValueError):
        _validate_safe_name(name, "field")


# --- _shell_command_tokens ---------------------------------------------------


def test_shell_command_tokens_wsl():
    tokens = _shell_command_tokens("wsl", "echo hi", "Ubuntu")
    assert tokens == ["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", "echo hi"]


def test_shell_command_tokens_wsl_without_distro():
    tokens = _shell_command_tokens("wsl", "echo hi", None)
    assert tokens == ["wsl.exe", "--", "bash", "-lc", "echo hi"]


def test_shell_command_tokens_powershell():
    tokens = _shell_command_tokens("powershell", "Get-Process", None)
    assert tokens == ["powershell.exe", "-NoExit", "-Command", "Get-Process"]


def test_shell_command_tokens_cmd():
    tokens = _shell_command_tokens("cmd", "dir", None)
    assert tokens == ["cmd.exe", "/K", "dir"]


def test_shell_command_tokens_default_shell():
    tokens = _shell_command_tokens(None, "ls", None)
    assert tokens == ["ls"]


# --- _tab_args ---------------------------------------------------------------


def test_tab_args_first_tab_has_no_separator():
    parts = _tab_args({"shell": "powershell"}, is_first=True)
    assert parts[0] != ";"


def test_tab_args_non_first_tab_starts_with_separator():
    parts = _tab_args({"shell": "powershell"}, is_first=False)
    assert parts[:2] == [";", "new-tab"]


def test_tab_args_powershell_uses_profile():
    parts = _tab_args({"shell": "powershell"}, is_first=True)
    assert "-p" in parts
    assert parts[parts.index("-p") + 1] == "PowerShell"


def test_tab_args_cmd_uses_profile():
    parts = _tab_args({"shell": "cmd"}, is_first=True)
    assert "-p" in parts
    assert parts[parts.index("-p") + 1] == "Command Prompt"


def test_tab_args_wsl_uses_distro_as_profile():
    parts = _tab_args(
        {"shell": "wsl", "wsl_distro": "Ubuntu-22.04"},
        is_first=True,
    )
    assert parts[parts.index("-p") + 1] == "Ubuntu-22.04"


def test_tab_args_wsl_default_distro_when_none_given(monkeypatch):
    monkeypatch.setattr(terminal_mod, "calling_wsl_distro", lambda: "claude-agents")
    parts = _tab_args({"shell": "wsl"}, is_first=True)
    assert parts[parts.index("-p") + 1] == "claude-agents"


def test_tab_args_wsl_command_uses_inferred_distro(monkeypatch):
    """Regression: wsl.exe -d in the command tokens must use the same distro
    as the WT profile when no explicit wsl_distro is given in the tab dict.

    Before the fix, profile used calling_wsl_distro() but the command tokens
    received the raw tab value (None), so wsl.exe omitted -d entirely and ran
    the command in the Windows-default distro instead of the inferred one.
    """
    monkeypatch.setattr(terminal_mod, "calling_wsl_distro", lambda: "claude-agents")
    parts = _tab_args(
        {"shell": "wsl", "command": "claude --dangerously-skip-permissions"},
        is_first=True,
    )
    # Profile must name the inferred distro.
    assert parts[parts.index("-p") + 1] == "claude-agents"
    # wsl.exe command tokens must also include -d <inferred-distro>.
    assert "wsl.exe" in parts
    wsl_idx = parts.index("wsl.exe")
    assert parts[wsl_idx + 1] == "-d"
    assert parts[wsl_idx + 2] == "claude-agents"


def test_tab_args_explicit_profile_overrides_shell_dispatch():
    parts = _tab_args(
        {"shell": "powershell", "profile": "My Profile"},
        is_first=True,
    )
    # Explicit profile wins, no PowerShell auto-pick.
    assert parts[parts.index("-p") + 1] == "My Profile"


def test_tab_args_with_command_powershell():
    parts = _tab_args(
        {"shell": "powershell", "command": "claude"},
        is_first=True,
    )
    # The command tokens should be the tail of parts.
    assert parts[-4:] == ["powershell.exe", "-NoExit", "-Command", "claude"]


def test_tab_args_with_cwd_windows_path():
    parts = _tab_args(
        {"shell": "powershell", "cwd": "C:\\Users\\me"},
        is_first=True,
    )
    assert parts[parts.index("-d") + 1] == "C:\\Users\\me"


def test_tab_args_with_cwd_posix_wsl():
    parts = _tab_args(
        {"shell": "wsl", "wsl_distro": "Ubuntu", "cwd": "/home/test"},
        is_first=True,
    )
    cwd_arg = parts[parts.index("-d") + 1]
    assert cwd_arg == "\\\\wsl$\\Ubuntu\\home\\test"


# --- Validation in _tab_args ------------------------------------------------


def test_tab_args_rejects_profile_with_semicolon():
    with pytest.raises(ValueError, match="profile"):
        _tab_args({"profile": "; rm -rf /"}, is_first=True)


def test_tab_args_rejects_wsl_distro_with_semicolon():
    with pytest.raises(ValueError, match="wsl_distro"):
        _tab_args(
            {"shell": "wsl", "wsl_distro": "Ubuntu; whoami"},
            is_first=True,
        )


def test_tab_args_rejects_wsl_distro_with_quote():
    with pytest.raises(ValueError, match="wsl_distro"):
        _tab_args(
            {"shell": "wsl", "wsl_distro": 'bad"name'},
            is_first=True,
        )


# --- build_wt_args -----------------------------------------------------------


def test_build_wt_args_prefix():
    args = build_wt_args([{"shell": "powershell"}], "title-x")
    assert args[:5] == ["wt.exe", "--window", "new", "--title", "title-x"]


def test_build_wt_args_without_title():
    args = build_wt_args([{"shell": "powershell"}], "")
    assert "--title" not in args


def test_build_wt_args_multiple_tabs_have_separator():
    args = build_wt_args(
        [{"shell": "powershell"}, {"shell": "cmd"}],
        "x",
    )
    # Second tab should introduce '; new-tab' somewhere.
    sep_index = args.index(";")
    assert args[sep_index : sep_index + 2] == [";", "new-tab"]


def test_build_wt_args_full_pipeline():
    args = build_wt_args(
        [{"shell": "powershell", "command": "claude"}],
        "title-x",
    )
    assert args == [
        "wt.exe", "--window", "new", "--title", "title-x",
        "-p", "PowerShell",
        "powershell.exe", "-NoExit", "-Command", "claude",
    ]
