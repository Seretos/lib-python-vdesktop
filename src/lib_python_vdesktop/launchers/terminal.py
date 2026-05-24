"""Windows Terminal launcher.

`wt.exe` is a stub that forwards to a singleton WindowsTerminal.exe. The spawn
PID exits immediately, so we always identify the resulting window by a unique
``--title`` tag that we assign at launch time.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Optional, Union

from .._window_classes import TERMINAL_CLASS
from ..pathmap import to_windows
from ._common import launch_and_register

log = logging.getLogger("vdesktop.launcher.terminal")


# Identifier-like fields that wt.exe / wsl.exe accept as flag values. These
# are NOT shell inputs — they get passed as separate argv elements. We still
# constrain them to a safe charset so a stray quote/semicolon can't escape the
# arg boundary in odd CLI parsers. The `command` and `cwd` fields are
# deliberately NOT validated here: they have legitimately broad charsets and
# `command` is shell-executed by design (see SECURITY.md).
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]{1,128}$")


def _validate_safe_name(value: str, field: str) -> None:
    if not _SAFE_NAME_RE.match(value):
        raise ValueError(
            f"{field} must match {_SAFE_NAME_RE.pattern!r} (got {value!r})"
        )


# Built-in Windows Terminal profile names for the shell shortcuts.
_SHELL_PROFILES: dict[str, str] = {
    "powershell": "PowerShell",
    "cmd": "Command Prompt",
}


def _shell_command_tokens(
    shell: Optional[str], command: str, wsl_distro: Optional[str]
) -> list[str]:
    """Return the argv tokens that wt.exe forwards to launch a shell which
    immediately executes `command`. Shell-specific quoting rules are the
    shell's responsibility — we just hand it the string."""
    if shell == "wsl":
        cmd = ["wsl.exe"]
        if wsl_distro:
            cmd.extend(["-d", wsl_distro])
        cmd.extend(["--", "bash", "-lc", command])
        return cmd
    if shell == "powershell":
        return ["powershell.exe", "-NoExit", "-Command", command]
    if shell == "cmd":
        return ["cmd.exe", "/K", command]
    # Profile-default shell — best-effort raw append.
    return [command]


def _tab_args(tab: dict, *, is_first: bool) -> list[str]:
    """Build the wt.exe command tokens for a single tab.

    Each non-first tab begins with the subcommand separator ';' and 'new-tab'.
    """
    parts: list[str] = []
    if not is_first:
        parts.extend([";", "new-tab"])

    shell = (tab.get("shell") or "").lower() or None
    profile = tab.get("profile")
    cwd = tab.get("cwd")
    command = tab.get("command")
    wsl_distro = tab.get("wsl_distro")

    if profile is not None:
        _validate_safe_name(profile, "profile")
    if wsl_distro is not None:
        _validate_safe_name(wsl_distro, "wsl_distro")

    if profile:
        parts.extend(["-p", profile])
    elif shell == "wsl":
        parts.extend(["-p", wsl_distro or "Ubuntu"])
    elif shell in _SHELL_PROFILES:
        parts.extend(["-p", _SHELL_PROFILES[shell]])

    if cwd:
        if shell == "wsl":
            # WSL tab: cwd must be a Windows path that maps into the WSL filesystem.
            if cwd.startswith("/"):
                # POSIX path under the WSL distro → \\wsl$\<distro>\...
                cwd_arg = to_windows(cwd, wsl_distro=wsl_distro)
            else:
                cwd_arg = to_windows(cwd)
        else:
            cwd_arg = to_windows(cwd)
        parts.extend(["-d", cwd_arg])

    if command:
        parts.extend(_shell_command_tokens(shell, command, wsl_distro))

    return parts


def build_wt_args(tabs: list[dict], window_title: str) -> list[str]:
    """Compose the full wt.exe argv: window-creation + per-tab subcommands."""
    args: list[str] = ["wt.exe", "--window", "new"]
    if window_title:
        args.extend(["--title", window_title])
    for i, tab in enumerate(tabs):
        args.extend(_tab_args(tab, is_first=(i == 0)))
    return args


def launch_terminal_impl(
    tabs: list[dict],
    slot: Optional[str] = None,
    desktop: Optional[Union[int, str]] = None,
    label: Optional[str] = None,
    window_title: Optional[str] = None,
) -> dict:
    if not tabs:
        raise ValueError("launch_terminal requires at least one tab")
    if window_title is not None:
        _validate_safe_name(window_title, "window_title")
    title = window_title or f"vdesktop-term-{uuid.uuid4().hex[:6]}"
    args = build_wt_args(tabs, title)
    return launch_and_register(
        args=args,
        app_type="terminal",
        label=label,
        slot=slot,
        desktop=desktop,
        title_hint=title,
        class_filter=TERMINAL_CLASS,
        resolve_timeout_ms=10000,
        pre_spawn_snapshot=True,
    )
