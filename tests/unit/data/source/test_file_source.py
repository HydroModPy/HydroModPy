"""The generic file data source: bounds, missing paths and frozen mode against the lockfile."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import BoundsError, FrozenDataError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.provenance import lockfile
from hydromodpy.data.source.file import DemFile
from hydromodpy.data.source.port import FetchRequest


def test_path_outside_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    outside = tmp_path / "secret" / "dem.tif"
    outside.parent.mkdir()
    outside.write_bytes(b"secret")

    source = DemFile(path=outside)
    bounds = Bounds(allowed_roots=(allowed,))
    req = FetchRequest(out_dir=tmp_path / "out", bounds=bounds)

    with pytest.raises(BoundsError, match="outside the roots"):
        source.fetch(req)


def test_absent_path(tmp_path: Path) -> None:
    absent = tmp_path / "nonexistent.tif"
    source = DemFile(path=absent)
    req = FetchRequest(out_dir=tmp_path / "out")

    with pytest.raises(FileNotFoundError, match=r"\[data\.dem\] file source path not found"):
        source.fetch(req)


@pytest.fixture
def frozen_project(tmp_path: Path) -> tuple[Path, lockfile.LockedInputs]:
    """A project with one pinned user file, and its lockfile read."""
    project = tmp_path / "project"
    inputs = project / "inputs"
    inputs.mkdir(parents=True)
    pinned = inputs / "dem.tif"
    pinned.write_bytes(b"pinned bytes")
    item = lockfile.user_file_input(
        pinned,
        variable="dem",
        project_root=project,
        sha256=hashlib.sha256(b"pinned bytes").hexdigest(),
    )
    lockfile.write_lockfile(
        project / "hydromodpy.lock", None, user_files=[item], project_root=project
    )
    return inputs, lockfile.read_locked_inputs(project)


def test_frozen_serves_a_pinned_file(
    frozen_project: tuple[Path, lockfile.LockedInputs],
) -> None:
    inputs, locked = frozen_project
    result = DemFile(path=inputs / "dem.tif", locked=locked).fetch(FetchRequest(out_dir=inputs))

    assert [record.path.name for record in result.files] == ["dem.tif"]


def test_frozen_refuses_changed_bytes(
    frozen_project: tuple[Path, lockfile.LockedInputs],
) -> None:
    inputs, locked = frozen_project
    (inputs / "dem.tif").write_bytes(b"other bytes")

    with pytest.raises(FrozenDataError, match="SHA-256 does not match"):
        DemFile(path=inputs / "dem.tif", locked=locked).fetch(FetchRequest(out_dir=inputs))
