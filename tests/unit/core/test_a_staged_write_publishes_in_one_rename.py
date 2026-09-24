"""A staged write replaces its target whole, or leaves it as it was."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.io.atomic_replace import staged_path


def test_the_staged_file_replaces_the_target(tmp_path: Path) -> None:
    target = tmp_path / "map.gpkg"
    target.write_text("old")

    with staged_path(target) as staged:
        assert staged.parent == target.parent
        assert staged.suffix == ".gpkg"
        assert target.read_text() == "old"
        staged.write_text("new")

    assert target.read_text() == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["map.gpkg"]


def test_a_failed_write_leaves_the_target_as_it_was(tmp_path: Path) -> None:
    target = tmp_path / "dem.tif"
    target.write_text("old")

    with pytest.raises(RuntimeError), staged_path(target) as staged:
        staged.write_text("half")
        raise RuntimeError("writer died")

    assert target.read_text() == "old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dem.tif"]
