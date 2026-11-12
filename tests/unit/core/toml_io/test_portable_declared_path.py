"""A resolved config path is written in the form that resolves back to it in any workspace.

The frozen ``config.toml`` of a run and the ``declared_path`` of its seal both
use it: a path relative to the project root, ``../../data/...`` for another file
of the workspace, and an absolute path only for a place outside the workspace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.toml_io.paths import (
    former_bare_name_location,
    is_bare_filename,
    portable_declared_path,
    resolve_declared_path,
)


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "ws"
    project = workspace / "projects" / "nancon"
    project.mkdir(parents=True)
    for relative in (
        "data/dem/DEM_armorican_massif.tif",
        "data/hydrography/nancon_stream_network.gpkg",
        "data/geology/map.gpkg",
    ):
        (workspace / relative).parent.mkdir(parents=True, exist_ok=True)
        (workspace / relative).write_bytes(b"x")
    (workspace / "data" / "hydrometry").mkdir(parents=True)
    (project / "inputs").mkdir()
    (project / "inputs" / "zones.shp").write_bytes(b"x")
    return workspace, project


def _round_trip(path: Path, role: str, project: Path, data: Path) -> str:
    written = portable_declared_path(path, role=role, project_root=project, data_dir=data)
    resolved = resolve_declared_path(written, base_dir=project)
    assert resolved == path.resolve(), written
    return written


def test_a_place_outside_the_workspace_stays_absolute_and_a_relative_value_is_kept(
    tmp_path: Path,
) -> None:
    workspace, project = _workspace(tmp_path)
    outside = tmp_path / "shared" / "dem.tif"

    written = portable_declared_path(
        outside, role="dem", project_root=project, data_dir=workspace / "data"
    )

    assert written == str(outside.resolve())
    assert (
        portable_declared_path(
            "inputs/DEM.tif", role="dem", project_root=project, data_dir=workspace / "data"
        )
        == "inputs/DEM.tif"
    )


def test_former_bare_name_location_finds_old_data_file(tmp_path: Path) -> None:
    workspace, project = _workspace(tmp_path)
    data = workspace / "data"

    found = former_bare_name_location("DEM_armorican_massif.tif", data, role="dem")
    assert found == (data / "dem" / "DEM_armorican_massif.tif").resolve()

    found_fallback = former_bare_name_location("map.gpkg", data, role="other")
    assert found_fallback is None

    found_in_data = former_bare_name_location("map.gpkg", data / "geology")
    assert found_in_data == (data / "geology" / "map.gpkg").resolve()

    missing = former_bare_name_location("absent.tif", data, role="dem")
    assert missing is None
