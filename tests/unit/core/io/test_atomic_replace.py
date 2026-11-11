"""A staged write replaces its target whole, or leaves it as it was."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from hydromodpy.core.io import atomic_replace, filesystem
from hydromodpy.core.io.atomic_replace import rename_over_open_file, staged_path
from tests._helpers.windows_os import PatchedOs


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


def _held(source: object, target: object) -> None:
    raise PermissionError(errno.EACCES, "The file is used by another process")


@pytest.mark.parametrize(("refusals", "moved"), [(2, True), (6, False)])
def test_a_windows_rename_over_a_held_file_is_retried_then_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusals: int, moved: bool
) -> None:
    waited: list[float] = []
    monkeypatch.setattr(filesystem.time, "sleep", waited.append)
    calls: list[object] = []

    def posix_rename(source: Path, target: Path) -> None:
        calls.append(source)
        if len(calls) <= refusals:
            _held(source, target)
        os.replace(source, target)

    monkeypatch.setattr(atomic_replace, "os", PatchedOs(name="nt", replace=_held))
    monkeypatch.setattr(atomic_replace, "_rename_with_posix_semantics", posix_rename)
    source, target = tmp_path / "new.json", tmp_path / "index.json"
    source.write_text("new")
    target.write_text("old")

    if moved:
        rename_over_open_file(source, target)
    else:
        with pytest.raises(PermissionError):
            rename_over_open_file(source, target)
    assert target.read_text() == ("new" if moved else "old")
    assert len(calls) == min(refusals + 1, 6)
    assert sum(waited) == pytest.approx(0.03 if moved else 0.31)


def test_off_windows_a_refused_rename_is_raised_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waited: list[float] = []
    monkeypatch.setattr(filesystem.time, "sleep", waited.append)
    monkeypatch.setattr(atomic_replace, "os", PatchedOs(name="posix", replace=_held))
    with pytest.raises(PermissionError):
        rename_over_open_file(tmp_path / "new.json", tmp_path / "index.json")
    assert waited == []
