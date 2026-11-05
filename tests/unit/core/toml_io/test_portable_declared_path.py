"""A resolved config path is written in the form that resolves back to it in any workspace.

The frozen ``config.toml`` of a run and the ``declared_path`` of its seal both
use it: a bare name found in ``data/``, a path relative to the project root,
``../../data/...`` for another file of the workspace, and an absolute path
only for a place outside the workspace.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.toml_io.paths import portable_declared_path, resolve_declared_path


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
    resolved = resolve_declared_path(written, base_dir=project, fallback_dirs=[data / role, data])
    assert resolved == path.resolve(), written
    return written


def test_each_path_is_written_in_the_form_that_resolves_back_to_it(tmp_path) -> None:
    workspace, project = _workspace(tmp_path)
    data = workspace / "data"

    assert _round_trip(data / "dem" / "DEM_armorican_massif.tif", "dem", project, data) == (
        "DEM_armorican_massif.tif"
    )
    assert _round_trip(data / "hydrometry", "hydrometry", project, data) == "hydrometry"
    assert _round_trip(project / "inputs" / "zones.shp", "zones", project, data) == (
        "inputs/zones.shp"
    )
    assert _round_trip(data / "geology" / "map.gpkg", "dem", project, data) == (
        "../../data/geology/map.gpkg"
    )


def test_a_place_outside_the_workspace_stays_absolute_and_a_relative_value_is_kept(
    tmp_path,
) -> None:
    workspace, project = _workspace(tmp_path)
    outside = tmp_path / "shared" / "dem.tif"

    written = portable_declared_path(
        outside, role="dem", project_root=project, data_dir=workspace / "data"
    )

    assert written == str(outside.resolve())
    assert (
        portable_declared_path(
            "DEM.tif", role="dem", project_root=project, data_dir=workspace / "data"
        )
        == "DEM.tif"
    )
