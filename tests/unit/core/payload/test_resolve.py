"""The data files a project's TOML files name, found under the data root.

A file source names a file or a station folder, from the project root or as a
workspace name read under ``data/<variable>/``. A reference that does not
resolve to exactly one file is refused, never guessed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.payload.resolve import project_data

CALIBRATION = """
[calibration.outputs.net]
support = "network"
{maps}
"""


@pytest.mark.parametrize("key", ["stream_geometry_path", "minimal_stream_geometry_path"])
def test_old_map_key_is_refused(tmp_path: Path, key: str) -> None:
    (tmp_path / "calibration.toml").write_text(
        CALIBRATION.format(maps=f'{key} = "streams.gpkg"'), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="written by a pre-release of 2.0"):
        project_data(tmp_path, tmp_path / "data", root=ROOT_CONFIG)


def _station_name(variable: str, station: str, freq: str = "D") -> str:
    return f"{variable}_custom_{station}_20000101_20001231_{freq}.csv"


def _write_registry(data_root: Path, variable: str, rows: list[dict[str, str]]) -> None:
    folder = data_root / variable
    folder.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0])
    lines = [",".join(columns), *(",".join(r[c] for c in columns) for r in rows)]
    (folder / f"{variable}_custom_LOC.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _config(project: Path, body: str, name: str = "run.toml") -> None:
    project.mkdir(exist_ok=True)
    (project / name).write_text(body, encoding="utf-8")


SOURCE = """
[data.{variable}]
[[data.{variable}.sources]]
source = "file"
path = "{path}"
{extra}
"""


@pytest.mark.parametrize(
    "body",
    [
        "[data]\nfoo = 1\n",
        "[[data.recharge.sources]]\n",
        '[data.recharge]\n[[data.recharge.sources]]\nsource = "api"\npath = "x.csv"\n',
        '[data.recharge]\n[[data.recharge.sources]]\nsource = "file"\n',
        '[data.recharge]\nsources = ["not a table"]\n',
    ],
    ids=["scalar-variable", "no-data-table", "other-provider", "no-path", "non-table-source"],
)
def test_not_a_file_source_ships_nothing(tmp_path: Path, body: str) -> None:
    project = tmp_path / "project"
    _config(project, body)

    assert project_data(project, tmp_path / "data", root=ROOT_CONFIG) == ([], ())


def _station_tree(tmp_path: Path, *, files: list[str], registry: list[dict] | None) -> Path:
    data = tmp_path / "data"
    (data / "discharge").mkdir(parents=True)
    for name in files:
        (data / "discharge" / name).write_text("", encoding="utf-8")
    if registry is not None:
        _write_registry(data, "discharge", registry)
    return data


_FOLDER = SOURCE.format(variable="discharge", path="workspace:.", extra='station_ids = ["A1"]')


@pytest.mark.parametrize(
    ("files", "registry", "body", "match"),
    [
        ([], [{"id": "A1"}], _FOLDER, r"asks for station 'A1' in .*0 file\(s\) match"),
        (
            [_station_name("discharge", "A1", "D"), _station_name("discharge", "A1", "M")],
            [{"id": "A1"}],
            _FOLDER,
            r"2 file\(s\) match the data naming contract, expected exactly 1",
        ),
        ([_station_name("discharge", "A1")], None, _FOLDER, r"stations, and .* does not exist"),
        (
            [_station_name("discharge", "A1")],
            [{"id": "Z"}],
            _FOLDER,
            r"station 'A1', which has no row",
        ),
        (
            [],
            [{"id": "A1"}],
            SOURCE.format(variable="discharge", path="workspace:.", extra=""),
            r"with neither station_ids nor \[site\] gauge",
        ),
        (
            [],
            [{"id": "A1"}],
            SOURCE.format(variable="discharge", path="missing.csv", extra=""),
            r"names 'missing.csv', which is not at",
        ),
        (
            [],
            [{"id": "A1"}],
            SOURCE.format(variable="dem", path="ghost.tif", extra=""),
            r"names 'ghost.tif', which is not at",
        ),
    ],
    ids=[
        "station-file-missing",
        "station-file-ambiguous",
        "registry-missing",
        "station-not-in-registry",
        "folder-without-station",
        "file-not-in-folder",
        "dem-file-not-in-folder",
    ],
)
def test_unresolved_reference_is_refused(
    tmp_path: Path, files: list[str], registry: list[dict] | None, body: str, match: str
) -> None:
    data = _station_tree(tmp_path, files=files, registry=registry)
    project = tmp_path / "project"
    _config(project, body)

    with pytest.raises(ConfigError, match=match):
        project_data(project, data, root=ROOT_CONFIG)


def test_map_name_in_two_folders_is_refused(tmp_path: Path) -> None:
    data = tmp_path / "data"
    for folder in ("hydrography", "other"):
        (data / folder).mkdir(parents=True)
        (data / folder / "streams.gpkg").write_bytes(b"")
    project = tmp_path / "project"
    _config(project, CALIBRATION.format(maps='map.complete = "streams.gpkg"'))

    with pytest.raises(ConfigError, match="2 file"):
        project_data(project, data, root=ROOT_CONFIG)


def test_a_file_written_in_two_forms_ships_once(tmp_path: Path) -> None:
    data = tmp_path / "data"
    dem = data / "dem" / "regional_dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes(b"x")
    project = tmp_path / "project"
    _config(project, SOURCE.format(variable="dem", path="workspace:regional_dem.tif", extra=""))
    _config(
        project,
        SOURCE.format(variable="dem", path="../data/dem/regional_dem.tif", extra=""),
        "b.toml",
    )

    files, stations = project_data(project, data, root=ROOT_CONFIG)

    assert files == [dem]
    assert stations == ()


def test_a_station_folder_of_the_workspace_ships_its_file_and_its_row(tmp_path: Path) -> None:
    data = tmp_path / "data"
    folder = data / "discharge"
    folder.mkdir(parents=True)
    chronicle = folder / "discharge_file_A1_20000101_20001231_D.csv"
    chronicle.write_text("", encoding="utf-8")
    (folder / "discharge_file_LOC.csv").write_text("id,x,y\nA1,1,2\n", encoding="utf-8")
    project = tmp_path / "project"
    _config(project, _FOLDER)

    files, stations = project_data(project, data, root=ROOT_CONFIG)

    assert files == [chronicle]
    assert [(row.dest, row.id) for row in stations] == [
        ("data/discharge/discharge_file_LOC.csv", "A1")
    ]
