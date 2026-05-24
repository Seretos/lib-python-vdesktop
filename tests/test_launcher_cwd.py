"""Tests for the launch working-directory guard, `_common._validate_cwd`.

Note: `_common` transitively imports ctypes.windll, so these tests are
Windows-only (the project's CI environment). They exercise only the pure
validation logic — nothing is spawned.
"""
from __future__ import annotations

import pytest

from lib_python_vdesktop.launchers._common import _validate_cwd


def test_validate_cwd_none_is_allowed():
    _validate_cwd(None)  # must not raise — inherits the process cwd


def test_validate_cwd_existing_directory_passes(tmp_path):
    _validate_cwd(str(tmp_path))  # must not raise


def test_validate_cwd_nonexistent_path_raises_naming_path(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ValueError, match="does not exist") as exc:
        _validate_cwd(str(missing))
    # The offending path must appear in the message (repr'd, like the other
    # launcher validators).
    assert repr(str(missing)) in str(exc.value)


def test_validate_cwd_file_is_not_a_directory(tmp_path):
    file_path = tmp_path / "a_file.txt"
    file_path.write_text("not a dir")
    with pytest.raises(ValueError, match="not a directory") as exc:
        _validate_cwd(str(file_path))
    assert repr(str(file_path)) in str(exc.value)
