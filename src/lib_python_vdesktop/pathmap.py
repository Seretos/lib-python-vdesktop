"""POSIX <-> Windows path conversion for the WSL bridge.

The MCP server always runs as a Windows process. When the calling agent is
inside WSL, it may pass POSIX paths like ``/home/test`` or ``/mnt/c/foo``;
these need to become Windows paths before being handed to Windows apps.
"""
from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache

_POSIX_DRIVE_RE = re.compile(r"^/mnt/([a-z])(?=/|$)", re.IGNORECASE)
_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_WIN_UNC_RE = re.compile(r"^\\\\")
_WSL_UNC_RE = re.compile(r"^\\\\(?:wsl\.localhost|wsl\$)\\([^\\]+)", re.IGNORECASE)


@lru_cache(maxsize=1)
def default_wsl_distro() -> str:
    """Best-effort discovery of the default WSL distribution name.

    Used when converting plain POSIX paths like ``/home/test`` into a
    ``\\\\wsl$\\<distro>\\home\\test`` UNC path that Windows apps can open.
    """
    env = os.environ.get("WSL_DEFAULT_DISTRO")
    if env:
        return env
    try:
        # `wsl.exe -l -q` lists installed distros, default first. Output is UTF-16-LE.
        result = subprocess.run(
            ["wsl.exe", "-l", "-q"],
            capture_output=True,
            timeout=3,
            check=False,
        )
        text = result.stdout.decode("utf-16-le", errors="replace")
        for line in text.splitlines():
            line = line.strip().replace("\x00", "")
            if line:
                return line
    except (OSError, subprocess.SubprocessError):
        pass
    return "Ubuntu"


def calling_wsl_distro() -> str:
    """Identify the WSL distro that spawned this Windows process.

    Priority chain (deliberately NOT cached — CWD can change across calls):

    1. Parse the CWD as a UNC path of the form ``\\\\wsl.localhost\\<distro>\\``
       or the older ``\\\\wsl$\\<distro>\\`` — the Windows process CWD is set to
       such a path when launched from inside WSL.
    2. ``WSL_DISTRO_NAME`` environment variable, if set and non-empty.
    3. Fall back to :func:`default_wsl_distro`.
    """
    cwd = os.getcwd()
    m = _WSL_UNC_RE.match(cwd)
    if m:
        return m.group(1)
    env_distro = os.environ.get("WSL_DISTRO_NAME")
    if env_distro:
        return env_distro
    return default_wsl_distro()


def to_windows(path: str, *, wsl_distro: str | None = None) -> str:
    """Convert an arbitrary path into a Windows-style path.

    - ``C:\\foo`` / ``C:/foo`` / ``\\\\server\\share`` → returned (slashes normalized)
    - ``/mnt/c/foo`` → ``C:\\foo``
    - ``/home/user`` → ``\\\\wsl$\\<distro>\\home\\user``
    - relative or empty → returned as-is
    """
    if not path:
        return path
    if _WIN_DRIVE_RE.match(path) or _WIN_UNC_RE.match(path):
        return path.replace("/", "\\")
    m = _POSIX_DRIVE_RE.match(path)
    if m:
        drive = m.group(1).upper()
        rest = path[len(m.group(0)):]
        if not rest:
            return f"{drive}:\\"
        return f"{drive}:" + rest.replace("/", "\\")
    if path.startswith("/"):
        distro = wsl_distro or calling_wsl_distro()
        return f"\\\\wsl$\\{distro}" + path.replace("/", "\\")
    # Relative path — convert slashes for Windows.
    return path.replace("/", "\\")


def to_posix(path: str) -> str:
    """Convert a Windows path into a POSIX path for WSL shells.

    Used for ``launch_terminal`` tabs where ``shell == 'wsl'``: the cwd
    needs to be a path inside the WSL filesystem.
    """
    if not path:
        return path
    if path.startswith("/"):
        return path
    if _WIN_UNC_RE.match(path):
        # \\wsl$\<distro>\... → drop UNC prefix.
        rest = path[2:].split("\\", 2)
        if len(rest) >= 3 and rest[0].lower().startswith("wsl"):
            return "/" + rest[2].replace("\\", "/")
        return path
    m = _WIN_DRIVE_RE.match(path)
    if m:
        drive = path[0].lower()
        rest = path[2:].replace("\\", "/")
        if not rest:
            return f"/mnt/{drive}"
        if not rest.startswith("/"):
            rest = "/" + rest
        return f"/mnt/{drive}{rest}"
    return path.replace("\\", "/")
