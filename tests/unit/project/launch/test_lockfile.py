"""The lockfile the launcher writes once, after the prepare phase, from the sidecars.

It pins every row of the shared data folder with its licence, plus the user files the
project declares. It writes nothing when there is nothing to pin, and a data folder that
still holds the database of a pre-release of 2.0 is refused by the scan, so no lockfile
follows and the launch goes on without ``--frozen``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hydromodpy.data.provenance.lockfile import (
    LOCKFILE_SCHEMA,
    read_lockfile_inputs,
    read_lockfile_meta,
    user_file_input,
)
from hydromodpy.data.provenance.sidecars import FORMER_CACHE_DATABASE, CacheIndex
from hydromodpy.project.launch.lockfile import write_project_lockfile


def _fetched(data: Path, station: str) -> Path:
    folder = data / "hydrometry"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"hydrometry_hubeau_{station}_D.csv"
    path.write_text(f"datetime,value\n2000-01-01,{station}\n", encoding="utf-8")
    CacheIndex(data).record(path, variable="hydrometry", source="hubeau", station_id=station)
    return path


def test_an_empty_data_folder_writes_no_lockfile(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "data").mkdir(parents=True)

    assert write_project_lockfile(project, project / "data") is None
    assert not (project / "hydromodpy.lock").exists()


def test_every_row_of_the_data_folder_is_pinned_with_its_licence(tmp_path: Path) -> None:
    project = tmp_path / "project"
    data = project / "data"
    _fetched(data, "A")
    _fetched(data, "B")

    written = write_project_lockfile(project, data)

    assert written == project / "hydromodpy.lock"
    inputs = read_lockfile_inputs(written)
    assert [(item.variable, item.source, item.station_id) for item in inputs] == [
        ("hydrometry", "hubeau", "A"),
        ("hydrometry", "hubeau", "B"),
    ]
    assert all(item.license == "etalab-2.0" for item in inputs)
    assert all(item.path.startswith("hydrometry/") for item in inputs)
    meta = read_lockfile_meta(written)
    assert meta["config_schema_sha256"]
    assert LOCKFILE_SCHEMA == "hydromodpy.lock.v2"


def test_the_data_folder_may_lie_outside_the_project(tmp_path: Path) -> None:
    project = tmp_path / "workspace" / "projects" / "lab"
    project.mkdir(parents=True)
    data = tmp_path / "elsewhere" / "data"
    _fetched(data, "A")

    written = write_project_lockfile(project, data)

    assert written == project / "hydromodpy.lock"
    assert [item.station_id for item in read_lockfile_inputs(written)] == ["A"]


def test_a_user_file_alone_is_pinned_and_a_refused_configuration_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    project = tmp_path / "project"
    (project / "data").mkdir(parents=True)
    dem = project / "inputs" / "dem.tif"
    dem.parent.mkdir()
    dem.write_bytes(b"a DEM")
    pinned = user_file_input(
        dem, variable="dem", project_root=project, sha256="0" * 64, license="etalab-2.0"
    )
    refused = project / "configs" / "broken.toml"
    monkeypatch.setattr(
        "hydromodpy.config.user_files.user_file_inputs",
        lambda root: ([pinned], [(refused, "no [workspace]")]),
    )

    with caplog.at_level(logging.WARNING):
        written = write_project_lockfile(project, project / "data")

    assert written is not None
    (item,) = read_lockfile_inputs(written)
    assert (item.variable, item.source, item.path) == ("dem", "file", "inputs/dem.tif")
    assert "broken.toml" in caplog.text


def test_a_data_folder_that_holds_the_former_database_is_not_locked(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    project = tmp_path / "project"
    data = project / "data"
    _fetched(data, "A")
    (data / FORMER_CACHE_DATABASE).write_bytes(b"database of a pre-release of 2.0")

    with caplog.at_level(logging.WARNING):
        written = write_project_lockfile(project, data)

    assert written is None
    assert not (project / "hydromodpy.lock").exists()
    assert "hmp workspace clean --data-cache" in caplog.text
