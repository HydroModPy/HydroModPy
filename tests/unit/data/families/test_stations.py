"""Station variables: the periods still to fetch, the merge of two chronicles, the files left in
the data folder (one file and one sidecar per station) and the watershed mask.
Dates are calendar days, flows are in m3/s (source unit L/s), coordinates are lon/lat degrees.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataSourceError, FrozenDataError
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.families.common import VariableBase
from hydromodpy.data.families.stations import StationVariable
from hydromodpy.data.provenance.lockfile import read_locked_inputs, write_lockfile
from hydromodpy.data.provenance.sidecars import CacheIndex, scan
from hydromodpy.data.variables.piezometry.config import PiezometrySourceConfig
from hydromodpy.data.variables.piezometry.variable import PiezometryVariable
from tests._helpers.data_climatic_builders import _make_point_record

JANUARY = (datetime(2020, 1, 1), datetime(2020, 1, 31))


class _Hydrometry(StationVariable):
    VARIABLE_NAME = "hydrometry"
    INTERNAL_UNIT = "m3/s"


def _record(station: str, start: str, end: str, *, location: bool = False) -> PointRecord:
    dates = pd.date_range(start, end, freq="D")
    return PointRecord(
        station_id=station,
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        source_unit="L/s",
        data=pd.DataFrame({"datetime": dates, "value": np.arange(len(dates), dtype=float)}),
        date_start=datetime.fromisoformat(start),
        date_end=datetime.fromisoformat(end),
        location=StationLocation(id=station, x=-1.7, y=48.1, crs="EPSG:4326") if location else None,
    )


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


def _variable(data_root: Path, *, period=JANUARY, locked=None) -> _Hydrometry:
    folder = data_root / "hydrometry"
    folder.mkdir(parents=True, exist_ok=True)
    return _Hydrometry(
        config=SimpleNamespace(),
        index=CacheIndex(data_root, locked=locked),
        project_period=period,
        data_dir=folder,
    )


def _files(data_root: Path) -> list[str]:
    # The hidden lock files stay out.
    return sorted(
        p.name for p in (data_root / "hydrometry").iterdir() if not p.name.startswith(".")
    )


# Periods of the project that the cached chronicle does not cover.
MISSING_PERIODS = [
    pytest.param(
        (datetime(2020, 1, 1), datetime(2020, 12, 31)),
        (datetime(2020, 6, 1), datetime(2020, 12, 31)),
        [(datetime(2020, 1, 1), datetime(2020, 5, 31))],
        id="gap before",
    ),
    pytest.param(
        (datetime(2019, 1, 1), datetime(2023, 12, 31)),
        (datetime(2020, 1, 1), datetime(2022, 12, 31)),
        [
            (datetime(2019, 1, 1), datetime(2019, 12, 31)),
            (datetime(2023, 1, 1), datetime(2023, 12, 31)),
        ],
        id="gap both sides",
    ),
    pytest.param(None, (datetime(2020, 1, 1), datetime(2020, 12, 31)), [], id="no project period"),
]


@pytest.mark.parametrize(("project_period", "cached", "gaps"), MISSING_PERIODS)
def test_missing_periods(project_period, cached, gaps):
    variable = _Hydrometry(config=None, index=CacheIndex(None), project_period=project_period)

    assert variable._compute_missing_periods(*cached) == gaps


# Second chronicle (start, end) merged into a first one from 2020-01-01 to 2020-01-10 or 2020-01-05.
MERGES = [
    pytest.param(("2020-01-01", "2020-01-10"), ("2020-01-08", "2020-01-15"), 15, id="overlap"),
    pytest.param(("2020-01-01", "2020-01-05"), ("2020-01-10", "2020-01-15"), 11, id="no overlap"),
]


@pytest.mark.parametrize(("first", "second", "n_days"), MERGES)
def test_merge_of_two_chronicles(first, second, n_days):
    variable = _Hydrometry(config=None, index=CacheIndex(None))

    merged = variable._merge_into_record(_record("ST01", *first), _record("ST01", *second))

    assert merged.station_id == "ST01"
    assert merged.date_start == datetime(2020, 1, 1)
    assert merged.date_end == datetime(2020, 1, 15)
    assert len(merged.data) == n_days  # days counted once
    assert merged.data["datetime"].is_monotonic_increasing
    assert merged.source_unit == "L/s"


def test_new_product_replaces_chronicle(data_root: Path) -> None:
    variable = _variable(data_root)
    variable._persist_api_records(
        [_record("X1", "2020-01-01", "2020-01-31")], "hubeau", product="QIXM"
    )

    assert (
        variable._load_cached_api_record(source="hubeau", station_id="X1", product="QIXJ") is None
    )
    variable._persist_api_records(
        [_record("X1", "2020-01-01", "2020-01-31")], "hubeau", product="QIXJ"
    )

    (row,) = scan(data_root).rows
    assert row.product == "QIXJ"


def test_empty_answer_and_chronicle_swap(
    data_root: Path,
) -> None:
    variable = _variable(data_root)
    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")

    variable._register_empty_api_stations(["X1"], "hubeau")
    (row,) = scan(data_root).rows
    assert row.empty and row.sha256 is None and row.bytes is None
    assert row.path.name == "hydrometry_hubeau_X1_empty.csv" and not row.path.exists()
    assert _files(data_root) == ["hydrometry_hubeau_X1_empty.csv.json"]

    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")
    (row,) = scan(data_root).rows
    assert not row.empty and row.path.is_file()
    assert not (data_root / "hydrometry" / "hydrometry_hubeau_X1_empty.csv.json").exists()


def test_edited_file_is_fetched_again(data_root: Path) -> None:
    variable = _variable(data_root)
    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")
    (row,) = scan(data_root).rows
    row.path.write_text("datetime,value\n2020-01-01,99\n")

    assert _variable(data_root)._load_cached_api_record(source="hubeau", station_id="X1") is None
    assert scan(data_root).rows == (), "its sidecar left with the stale row"


def test_frozen_run_refuses_changed_file(data_root: Path, tmp_path: Path) -> None:
    variable = _variable(data_root)
    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")
    project = tmp_path / "project"
    project.mkdir()
    write_lockfile(project / "hydromodpy.lock", data_root, project_root=project)
    (row,) = scan(data_root).rows
    row.path.write_text("datetime,value\n2020-01-01,99\n")

    locked = read_locked_inputs(project)
    with pytest.raises(FrozenDataError, match="SHA-256 mismatch"):
        _variable(data_root, locked=locked)._load_cached_api_record(
            source="hubeau", station_id="X1"
        )
    assert [r.path for r in scan(data_root).rows] == [row.path], "a frozen run deletes nothing"


def test_location_file_gathers_stations(data_root: Path) -> None:
    variable = _variable(data_root)

    variable._persist_api_records(
        [
            _record("X1", "2020-01-01", "2020-01-10", location=True),
            _record("X2", "2020-01-01", "2020-01-10", location=True),
        ],
        "hubeau",
    )

    loc = pd.read_csv(data_root / "hydrometry" / "hydrometry_hubeau_LOC.csv")
    assert sorted(loc["id"]) == ["X1", "X2"]
    names = [p.name for p in (data_root / "hydrometry").iterdir()]
    assert not [n for n in names if n.endswith(".part")]
    # A lock file is hidden, and the scan never reads a location file as a row.
    assert len(scan(data_root).rows) == 2


def test_no_data_folder_writes_nothing(tmp_path: Path) -> None:
    variable = _Hydrometry(
        config=SimpleNamespace(), index=CacheIndex(None), project_period=JANUARY, data_dir=None
    )

    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")
    variable._register_empty_api_stations(["X2"], "hubeau")

    assert variable._load_cached_api_record(source="hubeau", station_id="X1") is None
    assert not variable._is_empty_sentinel("hubeau", "X2")
    assert list(tmp_path.iterdir()) == []


def test_no_index_writes_no_sidecar(data_root: Path) -> None:
    folder = data_root / "hydrometry"
    folder.mkdir(parents=True)
    variable = _Hydrometry(
        config=SimpleNamespace(), index=None, project_period=JANUARY, data_dir=folder
    )

    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")

    assert _files(data_root) == ["hydrometry_hubeau_X1_20200101_20200131_D.csv"]


def _mask(tmp_path: Path) -> Path:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    path = tmp_path / "watershed.geojson"
    gpd.GeoDataFrame(geometry=[box(-1.3, 48.3, -1.1, 48.4)], crs="EPSG:4326").to_file(path)
    return path


def _station_at(station_id: str, lon: float, lat: float):
    location = StationLocation(id=station_id, x=lon, y=lat, crs="EPSG:4326")
    return replace(_make_point_record(station_id), location=location)


# The mask is the box lon -1.3 to -1.1, lat 48.3 to 48.4. IN lies inside, FAR north of it.
IN = (-1.2, 48.35)
FAR = (-1.2, 48.5)


@pytest.mark.fast
def test_named_station_outside_mask_kept(tmp_path):
    variable = PiezometryVariable(config=None, index=None)
    source = PiezometrySourceConfig(
        source="hubeau", product="level", station_ids=["FAR"], mask_path=_mask(tmp_path)
    )

    kept = variable._apply_mask([_station_at("FAR", *FAR)], source)

    assert [r.station_id for r in kept] == ["FAR"]


@pytest.mark.fast
def test_found_station_outside_mask_dropped(tmp_path):
    variable = PiezometryVariable(config=None, index=None)
    source = PiezometrySourceConfig(source="hubeau", product="level", mask_path=_mask(tmp_path))

    kept = variable._apply_mask([_station_at("IN", *IN), _station_at("FAR", *FAR)], source)

    assert [r.station_id for r in kept] == ["IN"]


@pytest.mark.fast
def test_search_all_outside_is_empty(tmp_path, caplog):
    # A search by extent finds candidates. None inside is no station, not an error.
    variable = PiezometryVariable(config=None, index=None)
    source = PiezometrySourceConfig(source="hubeau", product="level", mask_path=_mask(tmp_path))

    with caplog.at_level(logging.WARNING):
        kept = variable._apply_mask([_station_at("FAR", *FAR)], source)

    assert kept == []
    assert "dropped: ['FAR']" in caplog.text
    assert "the variable is empty" in caplog.text


@pytest.mark.fast
def test_listed_stations_outside_refused(tmp_path):
    # The mask filter of a variable that does not exempt listed stations refuses them.
    variable = PiezometryVariable(config=None, index=None)
    source = PiezometrySourceConfig(
        source="hubeau", product="level", station_ids=["FAR"], mask_path=_mask(tmp_path)
    )

    with pytest.raises(DataSourceError, match=r"every station .* outside the mask.*\['FAR'\]"):
        VariableBase._apply_mask(variable, [_station_at("FAR", *FAR)], source)


@pytest.mark.fast
def test_file_stations_outside_refused(tmp_path):
    # A custom file lists its stations: none inside is a variable that cannot be read.
    variable = PiezometryVariable(config=None, index=None)
    source = SimpleNamespace(source="file", station_ids=None, mask_path=_mask(tmp_path))

    with pytest.raises(DataSourceError, match="No station is left to load"):
        variable._apply_mask([_station_at("FAR", *FAR)], source)
