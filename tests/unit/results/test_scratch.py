"""The scratch of an attempt leaves by removal or by a move, and a vanished entry is no error."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.storage import scratch as scratch_module
from hydromodpy.results.storage.scratch import clear_scratch


def test_a_missing_scratch_is_left_alone(tmp_path: Path) -> None:
    clear_scratch(tmp_path / "absent", kept=tmp_path / "kept")

    assert not (tmp_path / "kept").exists()


def test_a_file_leaves_the_scratch_and_replaces_a_kept_copy(tmp_path: Path) -> None:
    scratch, kept = tmp_path / "scratch", tmp_path / "kept"
    scratch.mkdir()
    kept.mkdir()
    (scratch / "a.lst").write_text("new")
    (kept / "a.lst").write_text("old")

    clear_scratch(scratch, kept=kept)
    assert (kept / "a.lst").read_text() == "new"
    assert not list(scratch.iterdir())

    (scratch / "b.lst").write_text("gone")
    clear_scratch(scratch)
    assert not list(scratch.iterdir())


def test_an_entry_removed_by_someone_else_is_no_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "folder").mkdir()

    def vanished(path: Path) -> None:
        raise FileNotFoundError(path)

    monkeypatch.setattr(scratch_module.shutil, "rmtree", vanished)
    clear_scratch(tmp_path)
