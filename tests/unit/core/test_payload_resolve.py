"""Tests of `core.payload.resolve`: the data files a project's TOML files name."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.payload.resolve import project_data

CALIBRATION = """
[calibration.outputs.net]
support = "network"
{maps}
"""


@pytest.mark.parametrize(
    ("maps", "shipped"),
    [
        pytest.param(
            'map.complete = "streams.gpkg"\nmap.permanent = "permanent.gpkg"\n'
            'map.calibrate_on = "permanent"',
            ["permanent.gpkg", "streams.gpkg"],
            id="both_maps_travel",
        ),
        pytest.param('map.complete = "data.hydrography"', [], id="a_named_source_ships_no_file"),
        pytest.param(
            'map.complete = "streams.gpkg"\nmap.permanent = "data.hydrography"\n'
            'map.calibrate_on = "permanent"',
            ["streams.gpkg"],
            id="one_file_and_one_source",
        ),
    ],
)
def test_the_mapped_networks_of_an_output_ship_with_the_project(
    tmp_path: Path, maps: str, shipped: list[str]
) -> None:
    folder = tmp_path / "data" / "hydrography"
    folder.mkdir(parents=True)
    for name in ("streams.gpkg", "permanent.gpkg"):
        (folder / name).write_bytes(b"")
    project = tmp_path / "project"
    project.mkdir()
    (project / "calibration.toml").write_text(CALIBRATION.format(maps=maps), encoding="utf-8")

    files, stations = project_data(project, tmp_path / "data")

    assert [path.name for path in files] == shipped
    assert stations == ()


@pytest.mark.parametrize("key", ["stream_geometry_path", "minimal_stream_geometry_path"])
def test_an_output_with_an_old_map_key_is_refused_not_shipped_empty(
    tmp_path: Path, key: str
) -> None:
    (tmp_path / "calibration.toml").write_text(
        CALIBRATION.format(maps=f'{key} = "streams.gpkg"'), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="hmp doctor --fix-config"):
        project_data(tmp_path, tmp_path / "data")
