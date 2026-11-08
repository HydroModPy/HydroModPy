"""The size of a path on disk, file or folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.io.filesystem import path_size


def test_the_size_of_a_file_is_its_bytes(tmp_path: Path) -> None:
    file = tmp_path / "a.bin"
    file.write_bytes(b"12345")
    assert path_size(file) == 5


def test_the_size_of_a_folder_sums_its_files_and_skips_its_folders(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.bin").write_bytes(b"123")
    (tmp_path / "sub" / "b.bin").write_bytes(b"4567")
    assert path_size(tmp_path) == 7


def test_a_path_that_is_gone_weighs_nothing(tmp_path: Path) -> None:
    assert path_size(tmp_path / "missing") == 0


def test_a_file_removed_during_the_walk_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "kept.bin").write_bytes(b"12")
    gone = tmp_path / "gone.bin"
    gone.write_bytes(b"345")
    is_file = Path.is_file

    def racing_is_file(self: Path) -> bool:
        if self == gone:
            raise OSError("removed while walked")
        return is_file(self)

    monkeypatch.setattr(Path, "is_file", racing_is_file)
    assert path_size(tmp_path) == 2
