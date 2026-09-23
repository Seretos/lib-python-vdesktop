#!/usr/bin/env python3
"""Pick the previous release tag for `gh release create --notes-start-tag`.

release.yml's release tags are orphaned stamp commits (each `vX.Y.Z` tag
points at a fresh commit built off `main`, never an ancestor of the previous
tag's commit), so `gh release create --generate-notes` cannot walk history to
find the previous tag on its own and falls back to the whole project history.
This script computes v<prev> — the highest existing tag whose SemVer 2.0
precedence is strictly below the new version — so the workflow can pass it
explicitly.

Stdlib only, Python 3.10-compatible (matches the release job's ubuntu-22.04
system `python3`, no setup-python step needed).

CLI contract (what release.yml relies on):
    git tag -l 'v*' | python3 scripts/prev_release_tag.py <new_version>
Tag names are read from stdin, one per line. The target version is argv[1].
Prints the previous tag to stdout, or nothing if none exists (first
release). Exits 0 in both cases — "no previous tag" is not an error.

Note on the `v*` filter: it is applied by the caller (`git tag -l 'v*'` in
release.yml), not here — `_VERSION_RE` below treats the leading `v` as
optional so a non-`v`-prefixed string would still parse if it reached this
script directly. That is intentional: filtering by tag naming convention is
the shell's job, and SemVer precedence comparison is this script's job.
"""
from __future__ import annotations

import re
import sys
from typing import Iterable, List, Optional, Tuple

# Same grammar shape as release.yml's "Validate version is semver" step
# (`^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$`), with an optional leading
# `v` for tag names. Used as the single source of truth within this script:
# both the target version and every candidate tag are parsed through this
# one regex (via `_parse_version`) rather than each keeping its own copy.
# It cannot reasonably be shared with the workflow's copy — that one lives
# in bash/YAML, this one in Python — so this is the one Python-side
# definition.
_VERSION_RE = re.compile(
    r"^v?(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$"
)

_ParsedVersion = Tuple[int, int, int, Optional[str]]


def _parse_version(version: str) -> Optional[_ParsedVersion]:
    """Parse `v?MAJOR.MINOR.PATCH[-PRERELEASE]`, or None if it doesn't match."""
    match = _VERSION_RE.match(version)
    if match is None:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        match.group("prerelease"),
    )


def _prerelease_precedence_key(prerelease: Optional[str]) -> tuple:
    """SemVer 2.0 precedence key for the optional prerelease component.

    A release (no prerelease) always outranks any prerelease of the same
    MAJOR.MINOR.PATCH. Among prereleases, dot-separated identifiers compare
    left to right: numeric identifiers compare as integers, numeric
    identifiers always have lower precedence than alphanumeric ones, and a
    shorter identifier list has lower precedence than a longer one that is
    otherwise equal (Python's tuple comparison gives us that last rule for
    free, since a shorter tuple that is a prefix of a longer one sorts
    below it).
    """
    if prerelease is None:
        return (1,)
    identifier_keys = []
    for identifier in prerelease.split("."):
        if identifier.isdigit():
            identifier_keys.append((0, int(identifier), ""))
        else:
            identifier_keys.append((1, 0, identifier))
    return (0, tuple(identifier_keys))


def _precedence_key(parsed: _ParsedVersion) -> tuple:
    major, minor, patch, prerelease = parsed
    return (major, minor, patch, _prerelease_precedence_key(prerelease))


def previous_tag(new_version: str, tags: Iterable[str]) -> Optional[str]:
    """Return the highest tag in `tags` with SemVer precedence strictly below
    `new_version`, or None if no such tag exists (first release).

    Tags that don't parse as `v?MAJOR.MINOR.PATCH[-PRERELEASE]` are ignored,
    never used as a fallback.
    """
    target = _parse_version(new_version)
    if target is None:
        raise ValueError(f"not a valid semver version: {new_version!r}")
    target_key = _precedence_key(target)

    best_tag: Optional[str] = None
    best_key: Optional[tuple] = None
    for tag in tags:
        parsed = _parse_version(tag)
        if parsed is None:
            continue
        key = _precedence_key(parsed)
        if key >= target_key:
            continue
        if best_key is None or key > best_key:
            best_key = key
            best_tag = tag

    return best_tag


def _main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("usage: prev_release_tag.py <new_version>", file=sys.stderr)
        return 1

    new_version = argv[1]
    tags = [line.strip() for line in sys.stdin if line.strip()]
    result = previous_tag(new_version, tags)
    if result:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
