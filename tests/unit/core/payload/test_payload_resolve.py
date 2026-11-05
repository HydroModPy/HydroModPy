"""Tests of `core.payload.resolve`: the data files a project's TOML files name."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.payload.resolve import authored_configs, authored_files, project_data

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


# ---------------------------------------------------------- authored files


def test_a_project_ships_what_its_author_wrote_and_not_scratch_files(tmp_path: Path) -> None:
    for name in ("run.toml", "notes.md", "plot.py", "_scratch.toml", ".local.toml", "data.csv"):
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "sub.toml").mkdir()  # a folder named like a config is not a file

    assert [p.name for p in authored_files(tmp_path)] == ["notes.md", "plot.py", "run.toml"]
    assert [p.name for p in authored_configs(tmp_path)] == ["run.toml"]


# ------------------------------------------------------------ data sources


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
source = "custom"
path = "{path}"
{extra}
"""


def test_a_station_folder_source_ships_the_station_files_and_registry_rows(tmp_path: Path) -> None:
    data = tmp_path / "data"
    folder = data / "discharge"
    folder.mkdir(parents=True)
    for station in ("A1", "B2", "C3"):
        (folder / _station_name("discharge", station)).write_text("", encoding="utf-8")
    _write_registry(
        data,
        "discharge",
        [{"id": s, "x": str(i), "unit": "m3/s"} for i, s in enumerate(("A1", "B2", "C3"))],
    )
    project = tmp_path / "project"
    _config(
        project,
        SOURCE.format(variable="discharge", path="discharge", extra='station_ids = ["B2", "A1"]'),
    )

    files, stations = project_data(project, data)

    assert [p.name for p in files] == [
        _station_name("discharge", "A1"),
        _station_name("discharge", "B2"),
    ]
    assert [s.id for s in stations] == ["A1", "B2"]  # sorted, one row per station
    assert stations[0].dest == "data/discharge/discharge_custom_LOC.csv"
    assert dict(stations[1].row) == {"id": "B2", "x": "1", "unit": "m3/s"}


def test_a_source_without_station_ids_reads_the_gauge_of_the_site(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "discharge").mkdir(parents=True)
    (data / "discharge" / _station_name("discharge", "G9")).write_text("", encoding="utf-8")
    _write_registry(data, "discharge", [{"id": "G9", "x": "0"}])
    project = tmp_path / "project"
    _config(
        project,
        '[site]\ngauge = "G9"\n' + SOURCE.format(variable="discharge", path="discharge", extra=""),
    )

    files, stations = project_data(project, data)

    assert [p.name for p in files] == [_station_name("discharge", "G9")]
    assert [s.id for s in stations] == ["G9"]


def test_a_file_source_is_found_in_the_project_first_then_in_the_variable_folder(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    (data / "recharge").mkdir(parents=True)
    (data / "recharge" / "r.csv").write_text("", encoding="utf-8")
    project = tmp_path / "project"
    _config(project, SOURCE.format(variable="recharge", path="r.csv", extra=""), "a.toml")
    (project / "mine.csv").write_text("", encoding="utf-8")
    _config(project, SOURCE.format(variable="recharge", path="mine.csv", extra=""), "b.toml")

    files, stations = project_data(project, data)

    assert sorted(p.parent.name for p in files) == ["project", "recharge"]
    assert stations == ()


@pytest.mark.parametrize(
    "body",
    [
        "[data]\nfoo = 1\n",
        "[[data.recharge.sources]]\n",
        '[data.recharge]\n[[data.recharge.sources]]\nsource = "api"\npath = "x.csv"\n',
        '[data.recharge]\n[[data.recharge.sources]]\nsource = "custom"\n',
        '[data.recharge]\nsources = ["not a table"]\n',
    ],
    ids=["scalar-variable", "no-data-table", "other-provider", "no-path", "non-table-source"],
)
def test_what_is_not_a_custom_file_source_ships_nothing(tmp_path: Path, body: str) -> None:
    project = tmp_path / "project"
    _config(project, body)

    assert project_data(project, tmp_path / "data") == ([], ())


def test_the_regional_dem_is_located_by_name_under_the_data_root(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "dem").mkdir(parents=True)
    (data / "dem" / "regional.tif").write_bytes(b"")
    project = tmp_path / "project"
    _config(project, '[geographic.catchment]\ndem_init_path = "elsewhere/regional.tif"\n')

    files, _ = project_data(project, data)

    assert [p.name for p in files] == ["regional.tif"]


# ------------------------------------------------------------------- errors


def _station_tree(tmp_path: Path, *, files: list[str], registry: list[dict] | None) -> Path:
    data = tmp_path / "data"
    (data / "discharge").mkdir(parents=True)
    for name in files:
        (data / "discharge" / name).write_text("", encoding="utf-8")
    if registry is not None:
        _write_registry(data, "discharge", registry)
    return data


_FOLDER = SOURCE.format(variable="discharge", path="discharge", extra='station_ids = ["A1"]')


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
            SOURCE.format(variable="discharge", path="discharge", extra=""),
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
            '[geographic.catchment]\ndem_init_path = "ghost.tif"\n',
            r"names 'ghost.tif': 0 file\(s\) carry that name",
        ),
    ],
    ids=[
        "station-file-missing",
        "station-file-ambiguous",
        "registry-missing",
        "station-not-in-registry",
        "folder-without-station",
        "file-not-in-folder",
        "dem-not-found",
    ],
)
def test_a_reference_that_does_not_resolve_to_exactly_one_file_is_an_error_not_a_pick(
    tmp_path: Path, files: list[str], registry: list[dict] | None, body: str, match: str
) -> None:
    data = _station_tree(tmp_path, files=files, registry=registry)
    project = tmp_path / "project"
    _config(project, body)

    with pytest.raises(ConfigError, match=match):
        project_data(project, data)


def test_a_dem_name_carried_by_two_folders_is_ambiguous(tmp_path: Path) -> None:
    data = tmp_path / "data"
    for folder in ("dem", "other"):
        (data / folder).mkdir(parents=True)
        (data / folder / "regional.tif").write_bytes(b"")
    project = tmp_path / "project"
    _config(project, '[geographic.catchment]\ndem_init_path = "regional.tif"\n')

    with pytest.raises(ConfigError, match="2 file"):
        project_data(project, data)
