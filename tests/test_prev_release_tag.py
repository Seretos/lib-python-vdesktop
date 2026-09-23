"""Tests for scripts/prev_release_tag.py — previous-release-tag selection.

This is a standalone CI helper script (not part of the installable
`lib_python_vdesktop` package), so it lives outside `src/` and is loaded via
`importlib.util.spec_from_file_location` rather than an ordinary import —
`pyproject.toml`'s `pythonpath = ["src"]` stays untouched.

R1 (see .adev/41-1/plan.md): `previous_tag(new_version, tags)` returns the
highest `v*` tag whose SemVer precedence is strictly below `new_version`, or
`None` when no such tag exists. The `v*` prefix filtering itself happens in
release.yml's `git tag -l 'v*'` shell call, not in this function — its regex
makes the leading `v` optional, so unparsable/non-tag strings simply pass
through untouched by the (unrelated) prefix filter and must be ignored by
`previous_tag` on its own.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "prev_release_tag.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("prev_release_tag", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def prev_release_tag():
    return _load_module()


# Fixed tag list shared by the parametrized cases below (plan.md R1).
TAGS = [
    "v0.1.0", "v0.1.1", "v0.1.2", "v0.1.3", "v0.1.4",
    "v0.1.5", "v0.1.6", "v0.1.7", "v0.1.8",
    "v0.2.0-rc.1", "v0.2.0-rc.2",
    "not-a-tag",
]


@pytest.mark.parametrize(
    "new_version, tags, expected",
    [
        # (a) normal step: just-pushed tag itself present in the list must be
        # excluded (it is not strictly below new_version).
        ("0.1.9", TAGS + ["v0.1.9"], "v0.1.8"),
        ("0.1.8", TAGS, "v0.1.7"),
        # (b) prerelease progression
        ("0.2.0-rc.2", TAGS, "v0.2.0-rc.1"),
        ("0.2.0-rc.1", TAGS, "v0.1.8"),
        ("0.2.0", TAGS, "v0.2.0-rc.2"),
        # (c) first release — no lower tag exists
        ("0.1.0", ["v0.1.0"], None),
        ("0.1.0", [], None),
    ],
    ids=[
        "step-0.1.9-excludes-self",
        "step-0.1.8",
        "prerelease-rc2-from-rc1",
        "prerelease-rc1-from-0.1.8",
        "final-0.2.0-from-rc2",
        "first-release-only-self-tag",
        "first-release-no-tags",
    ],
)
def test_previous_tag_selection(prev_release_tag, new_version, tags, expected):
    assert prev_release_tag.previous_tag(new_version, tags) == expected


# --- additional edge-case coverage -------------------------------------------


def test_previous_tag_numeric_not_lexical_ordering(prev_release_tag):
    # Lexical string comparison would rank "v0.1.10" below "v0.1.9" (the
    # character '1' < '9' at the differing position); SemVer precedence must
    # rank it above.
    assert prev_release_tag.previous_tag("0.1.11", ["v0.1.9", "v0.1.10"]) == "v0.1.10"


def test_previous_tag_prerelease_numeric_ordering(prev_release_tag):
    # "rc.10" must outrank "rc.2" numerically, not lexically ('1' < '2').
    assert (
        prev_release_tag.previous_tag("0.2.0-rc.11", ["v0.2.0-rc.2", "v0.2.0-rc.10"])
        == "v0.2.0-rc.10"
    )


def test_previous_tag_ignores_unparsable_tags(prev_release_tag):
    assert (
        prev_release_tag.previous_tag("0.1.9", ["v0.1.8", "not-a-tag", "banana"])
        == "v0.1.8"
    )


def test_cli_prints_previous_tag(prev_release_tag):
    # Contract release.yml relies on: `git tag -l 'v*' | prev_release_tag.py
    # <version>` — tags fed on stdin, one per line.
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "0.1.9"],
        input="v0.1.7\nv0.1.8\nv0.1.9\n",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "v0.1.8"


def test_cli_prints_nothing_on_first_release(prev_release_tag):
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "0.1.0"],
        input="",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
