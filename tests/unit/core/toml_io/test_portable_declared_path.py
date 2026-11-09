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
    has_url_scheme,
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


def test_each_path_is_written_in_the_form_that_resolves_back_to_it(tmp_path: Path) -> None:
    workspace, project = _workspace(tmp_path)
    data = workspace / "data"

    assert _round_trip(data / "dem" / "DEM_armorican_massif.tif", "dem", project, data) == (
        "../../data/dem/DEM_armorican_massif.tif"
    )
    assert _round_trip(data / "hydrometry", "hydrometry", project, data) == "../../data/hydrometry"
    assert _round_trip(project / "inputs" / "zones.shp", "zones", project, data) == (
        "inputs/zones.shp"
    )
    assert _round_trip(data / "geology" / "map.gpkg", "dem", project, data) == (
        "../../data/geology/map.gpkg"
    )


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


def test_has_url_scheme_recognizes_schemes_and_allows_drive_letters() -> None:
    assert has_url_scheme("https://example.com/dem.tif") is True
    assert has_url_scheme("http://example.com") is True
    assert has_url_scheme("ftp://ftp.example.com/data") is True
    assert has_url_scheme("file:///etc/hosts") is True
    # Single letter drive prefix is not a scheme
    assert has_url_scheme("C:\\data\\dem.tif") is False
    assert has_url_scheme("D:/data/dem.tif") is False
    assert has_url_scheme("c:/dem.tif") is False
    assert has_url_scheme("inputs/dem.tif") is False
    assert has_url_scheme("dem.tif") is False


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


def test_resolve_declared_path_without_fallback_only_uses_base_dir(tmp_path: Path) -> None:
    workspace, project = _workspace(tmp_path)

    # Bare name present at project root
    (project / "local.tif").write_bytes(b"local")
    assert resolve_declared_path("local.tif", base_dir=project) == (project / "local.tif").resolve()

    # Bare name absent at project root does NOT resolve to workspace data
    resolved = resolve_declared_path("DEM_armorican_massif.tif", base_dir=project)
    assert resolved == (project / "DEM_armorican_massif.tif").resolve()
    assert not resolved.exists()
