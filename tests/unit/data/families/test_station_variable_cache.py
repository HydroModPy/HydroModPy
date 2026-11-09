"""What a station variable leaves in the data folder: one file and one sidecar per station."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import FrozenDataError
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.families.stations import StationVariable
from hydromodpy.data.provenance.lockfile import set_frozen_mode, write_lockfile
from hydromodpy.data.provenance.sidecars import CacheIndex, load_sidecar, scan

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


def _variable(data_root: Path, *, period=JANUARY) -> _Hydrometry:
    folder = data_root / "hydrometry"
    folder.mkdir(parents=True, exist_ok=True)
    return _Hydrometry(
        config=SimpleNamespace(),
        index=CacheIndex(data_root),
        project_period=period,
        data_dir=folder,
    )


def _files(data_root: Path) -> list[str]:
    """The names a reader sees: the hidden lock files stay out."""
    return sorted(
        p.name for p in (data_root / "hydrometry").iterdir() if not p.name.startswith(".")
    )


def test_a_chronicle_leaves_its_file_and_a_sidecar_that_says_what_it_is(data_root: Path) -> None:
    variable = _variable(data_root)

    variable._persist_api_records(
        [_record("X1", "2020-01-02", "2020-01-20", location=True)], "hubeau", product="QIXM"
    )

    (row,) = scan(data_root).rows
    assert row.path.name == "hydrometry_hubeau_X1_20200102_20200120_D.csv"
    assert (row.variable, row.source, row.station_id, row.product) == (
        "hydrometry",
        "hubeau",
        "X1",
        "QIXM",
    )
    assert (row.date_start, row.date_end) == ("2020-01-02T00:00:00", "2020-01-20T00:00:00")
    # The window asked is the hull of the data and the window of the call.
    assert row.asked_window == ("2020-01-01T00:00:00", "2020-01-31T00:00:00")
    assert (row.unit, row.source_unit, row.frequency) == ("m3/s", "L/s", "D")
    assert row.bbox == (-1.7, 48.1, -1.7, 48.1) and row.crs == "EPSG:4326"
    assert row.bytes == row.path.stat().st_size and row.sha256
    assert load_sidecar(row.path).license  # the registry of sources names a licence


def test_the_window_asked_is_what_a_second_run_does_not_ask_again(data_root: Path) -> None:
    _variable(data_root)._persist_api_records([_record("X1", "2020-01-02", "2020-01-30")], "hubeau")

    def no_download(*_args):
        raise AssertionError("the provider was asked again")

    cfg = SimpleNamespace(station_ids=["X1"], force_refresh=False, mask_path=None)
    records = _variable(data_root)._fetch_with_station_cache(cfg, no_download, source_name="hubeau")

    # The data stop on the 30th and start on the 2nd, the window asked is the whole month.
    assert [r.station_id for r in records] == ["X1"]
    assert records[0].date_end == datetime(2020, 1, 30)


def test_a_station_keeps_one_file_when_its_period_grows(data_root: Path) -> None:
    variable = _variable(data_root)
    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-10")], "hubeau")

    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")

    assert _files(data_root) == [
        "hydrometry_hubeau_X1_20200101_20200131_D.csv",
        "hydrometry_hubeau_X1_20200101_20200131_D.csv.json",
    ]


def test_two_stations_whose_ids_start_alike_keep_their_own_files(data_root: Path) -> None:
    variable = _variable(data_root)

    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-10")], "hubeau")
    variable._persist_api_records([_record("X1_2", "2020-01-01", "2020-01-10")], "hubeau")

    assert sorted(row.station_id for row in scan(data_root).rows) == ["X1", "X1_2"]


def test_a_new_product_replaces_the_chronicle_of_the_old_one(data_root: Path) -> None:
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


def test_an_empty_answer_replaces_the_chronicle_and_a_chronicle_replaces_the_empty_answer(
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


def test_a_file_edited_by_hand_is_fetched_again(data_root: Path) -> None:
    variable = _variable(data_root)
    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")
    (row,) = scan(data_root).rows
    row.path.write_text("datetime,value\n2020-01-01,99\n")

    assert _variable(data_root)._load_cached_api_record(source="hubeau", station_id="X1") is None
    assert scan(data_root).rows == (), "its sidecar left with the stale row"


def test_a_file_copied_with_a_new_date_is_not_fetched_again(data_root: Path) -> None:
    import os

    variable = _variable(data_root)
    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")
    (row,) = scan(data_root).rows
    later = row.path.stat().st_mtime + 3600
    os.utime(row.path, (later, later))  # same bytes, newer date: what a copy does

    record = _variable(data_root)._load_cached_api_record(source="hubeau", station_id="X1")

    assert record is not None and len(record.data) == 31


def test_a_frozen_run_refuses_a_file_that_changed_after_the_lock(
    data_root: Path, tmp_path: Path
) -> None:
    variable = _variable(data_root)
    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")
    project = tmp_path / "project"
    project.mkdir()
    write_lockfile(project / "hydromodpy.lock", data_root, project_root=project)
    (row,) = scan(data_root).rows
    row.path.write_text("datetime,value\n2020-01-01,99\n")

    set_frozen_mode(True, project_root=project)
    try:
        with pytest.raises(FrozenDataError, match="SHA-256 mismatch"):
            _variable(data_root)._load_cached_api_record(source="hubeau", station_id="X1")
    finally:
        set_frozen_mode(False)
    assert [r.path for r in scan(data_root).rows] == [row.path], "a frozen run deletes nothing"


def test_the_location_file_gathers_every_station_and_leaves_no_part_file(data_root: Path) -> None:
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


def test_a_variable_without_a_data_folder_writes_nothing(tmp_path: Path) -> None:
    variable = _Hydrometry(
        config=SimpleNamespace(), index=CacheIndex(None), project_period=JANUARY, data_dir=None
    )

    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")
    variable._register_empty_api_stations(["X2"], "hubeau")

    assert variable._load_cached_api_record(source="hubeau", station_id="X1") is None
    assert not variable._is_empty_sentinel("hubeau", "X2")
    assert list(tmp_path.iterdir()) == []


def test_a_variable_without_an_index_writes_the_file_and_no_sidecar(data_root: Path) -> None:
    folder = data_root / "hydrometry"
    folder.mkdir(parents=True)
    variable = _Hydrometry(
        config=SimpleNamespace(), index=None, project_period=JANUARY, data_dir=folder
    )

    variable._persist_api_records([_record("X1", "2020-01-01", "2020-01-31")], "hubeau")

    assert _files(data_root) == ["hydrometry_hubeau_X1_20200101_20200131_D.csv"]
