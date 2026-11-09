"""The index of a data folder: rows found, recorded, forgotten and subsumed.

Each case of the former DuckDB catalog keeps its question here, asked of the
sidecars. The seven side tables of the database (stations, coverage,
artifacts, provenance, failures, validation reports, API coverage) left
without a replacement, with the cases that only checked they existed.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.families.grids import GridVariable
from hydromodpy.data.families.stations import StationVariable
from hydromodpy.data.provenance.lockfile import set_frozen_mode
from hydromodpy.data.provenance.sidecars import (
    CacheIndex,
    CacheRow,
    empty_path_for,
    load_sidecar,
    scan,
    sidecar_path_for,
    write_sidecar,
)
from hydromodpy.data.provenance.sidecars import Sidecar as _Sidecar

BOX = (0.0, 0.0, 10.0, 10.0)


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "ws" / "data"
    root.mkdir(parents=True)
    return root


def _file(data_root: Path, relative: str, body: bytes = b"data") -> Path:
    path = data_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _record(index: CacheIndex, relative: str, **fields: object) -> CacheRow:
    assert index.data_root is not None
    variable = str(fields.pop("variable", relative.split("/")[0]))
    source = str(fields.pop("source", "src"))
    body = fields.pop("body", b"data")
    path = _file(index.data_root, relative, body)  # type: ignore[arg-type]
    return index.record(path, variable=variable, source=source, **fields)


# -- record and rows ----------------------------------------------------------


def test_a_record_is_a_row_read_back_by_a_new_index(data_root: Path) -> None:
    index = CacheIndex(data_root)
    row = _record(index, "hydrometry/h_src_A.csv", station_id="A", source_unit="L/s")

    again = CacheIndex(data_root).rows()

    assert again == [row]
    assert again[0].source_unit == "L/s"
    assert again[0].bytes == 4


def test_rows_filter_on_variable_source_and_station(data_root: Path) -> None:
    index = CacheIndex(data_root)
    _record(index, "hydrometry/a.csv", station_id="A")
    _record(index, "hydrometry/b.csv", station_id="B")
    _record(index, "dem/d.tif", source="ign")

    assert [r.station_id for r in index.rows(variable="hydrometry")] == ["A", "B"]
    assert [r.variable for r in index.rows(source="ign")] == ["dem"]
    assert [r.path.name for r in index.rows(station_id="B")] == ["b.csv"]


def test_rows_come_sorted_so_a_page_is_stable(data_root: Path) -> None:
    index = CacheIndex(data_root)
    for name in ("c", "a", "b"):
        _record(index, f"dem/{name}.tif")
    assert [r.path.name for r in index.rows()] == ["a.tif", "b.tif", "c.tif"]
    assert [r.path.name for r in index.rows()[1:2]] == ["b.tif"]


def test_two_records_of_one_station_leave_one_row(data_root: Path) -> None:
    index = CacheIndex(data_root)
    first = _record(index, "hydrometry/h_src_A_2020.csv", station_id="A")
    second = _record(index, "hydrometry/h_src_A_2021.csv", station_id="A", body=b"longer")

    assert index.rows() == [second]
    assert not first.path.exists()
    assert scan(data_root).rows == (second,)


def test_two_stations_keep_two_rows(data_root: Path) -> None:
    index = CacheIndex(data_root)
    _record(index, "hydrometry/a.csv", station_id="A")
    _record(index, "hydrometry/b.csv", station_id="B")
    assert len(index.rows()) == 2


def test_two_grids_of_one_source_keep_two_rows(data_root: Path) -> None:
    index = CacheIndex(data_root)
    _record(index, "recharge/r1.nc", bbox=(0, 0, 1, 1))
    _record(index, "recharge/r2.nc", bbox=(5, 5, 6, 6))
    assert len(index.rows(variable="recharge")) == 2


def test_a_record_of_a_missing_file_is_refused(data_root: Path) -> None:
    with pytest.raises(DataCacheError, match="not a file"):
        CacheIndex(data_root).record(data_root / "dem" / "gone.tif", variable="dem", source="ign")


def test_a_file_outside_the_data_folder_is_refused(data_root: Path, tmp_path: Path) -> None:
    # The user cache of the machine is no data folder: nothing is cached there.
    elsewhere = tmp_path / "user-cache" / "dem" / "dem.tif"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_bytes(b"tif")
    with pytest.raises(DataCacheError, match="outside the data folder"):
        CacheIndex(data_root).record(elsewhere, variable="dem", source="ign")


def test_an_index_without_a_data_folder_finds_nothing_and_writes_nothing(tmp_path: Path) -> None:
    index = CacheIndex(None)
    path = tmp_path / "dem.tif"
    path.write_bytes(b"tif")
    assert index.rows() == []
    assert index.find("dem", "ign") is None
    with pytest.raises(DataCacheError, match="no data folder"):
        index.record(path, variable="dem", source="ign")


# -- find -----------------------------------------------------------------------

_FINDS = {
    "by station": ({"station_id": "A"}, True),
    "an absent station": ({"station_id": "Z"}, False),
    "a period inside": ({"date_start": "2020-02-01", "date_end": "2020-11-30"}, True),
    "a period that starts before": ({"date_start": "2019-12-01", "date_end": "2020-06-30"}, False),
    "a period that ends after": ({"date_start": "2020-02-01", "date_end": "2021-01-31"}, False),
    "a period given as datetimes": (
        {"date_start": datetime(2020, 3, 1), "date_end": datetime(2020, 4, 1)},
        True,
    ),
    "the start alone": ({"date_start": "2020-01-01"}, True),
    "a box inside": ({"bbox": (1.0, 1.0, 2.0, 2.0)}, True),
    "the same box": ({"bbox": BOX}, True),
    "a box that overflows": ({"bbox": (-1.0, 1.0, 2.0, 2.0)}, False),
    "an inverted box": ({"bbox": (2.0, 2.0, 1.0, 1.0)}, False),
    "the product": ({"product": "QmnJ"}, True),
    "another product": ({"product": "QmM"}, False),
    "the version": ({"product_version": "2"}, True),
    "another version": ({"product_version": "3"}, False),
    "another source": ({"source": "other"}, False),
}


@pytest.mark.parametrize(("ask", "found"), _FINDS.values(), ids=_FINDS.keys())
def test_find_answers_with_a_superset(data_root: Path, ask: dict, found: bool) -> None:
    index = CacheIndex(data_root)
    _record(
        index,
        "hydrometry/h_src_A.csv",
        station_id="A",
        bbox=BOX,
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 12, 31),
        product="QmnJ",
        product_version="2",
    )
    source = ask.pop("source", "src")
    assert (index.find("hydrometry", source, **ask) is not None) is found


def test_a_row_without_a_period_answers_a_search_without_one(data_root: Path) -> None:
    index = CacheIndex(data_root)
    _record(index, "dem/d.tif", bbox=BOX)
    assert index.find("dem", "src") is not None
    assert index.find("dem", "src", date_start="2020-01-01") is None


def test_the_most_recently_fetched_row_wins(data_root: Path) -> None:
    index = CacheIndex(data_root)
    old = _record(index, "dem/old.tif", bbox=BOX)
    new = _record(index, "dem/new.tif", bbox=BOX, body=b"new data")
    for row, when in (
        (old, datetime(2020, 1, 1, tzinfo=UTC)),
        (new, datetime(2024, 1, 1, tzinfo=UTC)),
    ):
        sidecar = load_sidecar(row.path).model_copy(update={"fetched_at": when})
        write_sidecar(row.path, sidecar)

    found = CacheIndex(data_root).find("dem", "src", bbox=(1, 1, 2, 2))

    assert found is not None and found.path == new.path


def test_an_empty_row_answers_its_station_and_its_window_only(data_root: Path) -> None:
    index = CacheIndex(data_root)
    folder = data_root / "hydrometry"
    folder.mkdir()
    index.record_empty(
        empty_path_for(folder, "hydrometry_src_B"),
        variable="hydrometry",
        source="src",
        station_id="B",
        asked_window=(datetime(2000, 1, 1), datetime(2000, 1, 31)),
    )

    assert index.find("hydrometry", "src") is None
    row = index.find("hydrometry", "src", station_id="B")
    assert row is not None and row.empty
    assert row.window() == (datetime(2000, 1, 1), datetime(2000, 1, 31))
    assert index.find(
        "hydrometry", "src", station_id="B", date_start="2000-01-10", date_end="2000-01-20"
    )
    assert (
        index.find(
            "hydrometry", "src", station_id="B", date_start="2000-01-01", date_end="2000-03-01"
        )
        is None
    )


def test_an_empty_answer_and_a_chronicle_replace_each_other(data_root: Path) -> None:
    index = CacheIndex(data_root)
    chronicle = _record(index, "hydrometry/hydrometry_src_C_2000.csv", station_id="C")
    folder = data_root / "hydrometry"
    with index.chronicle(folder, "hydrometry_src_C"):
        empty = index.record_empty(
            empty_path_for(folder, "hydrometry_src_C"),
            variable="hydrometry",
            source="src",
            station_id="C",
        )
    assert not chronicle.path.exists()
    assert index.rows() == [empty]

    with index.chronicle(folder, "hydrometry_src_C"):
        again = _record(index, "hydrometry/hydrometry_src_C_2001.csv", station_id="C")
    assert not empty.sidecar_path.exists()
    assert scan(data_root).rows == (again,)


def test_a_chronicle_reads_its_rows_again_from_the_disk(data_root: Path) -> None:
    index = CacheIndex(data_root)
    _ = index.rows()
    other = CacheIndex(data_root)
    written = _record(other, "hydrometry/hydrometry_src_D_2000.csv", station_id="D")

    with index.chronicle(data_root / "hydrometry", "hydrometry_src_D") as rows:
        assert rows == [written]
    assert index.find("hydrometry", "src", station_id="D") == written


def test_a_chronicle_lock_is_taken_again_by_its_thread(data_root: Path) -> None:
    index = CacheIndex(data_root)
    folder = data_root / "hydrometry"
    with index.chronicle(folder, "hydrometry_src_E"), index.chronicle(folder, "hydrometry_src_E"):
        _record(index, "hydrometry/hydrometry_src_E_1.csv", station_id="E")
    assert len(index.rows()) == 1


# -- paths ------------------------------------------------------------------------


def test_a_path_does_not_depend_on_the_cwd(
    data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = data_root.parent / "projects" / "demo"
    project.mkdir(parents=True)
    monkeypatch.chdir(project)
    index = CacheIndex(data_root)
    row = _record(index, "hydrometry/hydrometry_hubeau_X1.csv", station_id="X1")

    assert index.relative(row.path) == "hydrometry/hydrometry_hubeau_X1.csv"
    assert index.resolve("hydrometry/hydrometry_hubeau_X1.csv") == row.path
    assert index.row_for("hydrometry/hydrometry_hubeau_X1.csv") == row
    assert index.row_for(row.path) == row


# -- forget, orphans, subsume ---------------------------------------------------------


def test_forgetting_rows_by_variable(data_root: Path) -> None:
    index = CacheIndex(data_root)
    _record(index, "hydrometry/a.csv", station_id="A")
    kept = _record(index, "dem/d.tif")
    for row in index.rows(variable="hydrometry"):
        index.forget(row)
    assert index.rows() == [kept]


def test_forgetting_with_the_file_deletes_it(data_root: Path) -> None:
    index = CacheIndex(data_root)
    row = _record(index, "geology/geology_brgm_1m_abc.gpkg", source="brgm_1m")
    index.forget(row, delete_file=True)
    assert not row.path.exists()
    assert not sidecar_path_for(row.path).exists()


def test_orphans_leave_and_rows_with_files_stay(data_root: Path) -> None:
    index = CacheIndex(data_root)
    kept = _record(index, "hydrometry/kept.csv", station_id="K")
    gone = _record(index, "hydrometry/gone.csv", station_id="G")
    gone.path.unlink()

    removed = index.forget_orphans()

    assert removed == [gone.sidecar_path]
    assert index.rows() == [kept]
    assert CacheIndex(data_root).rows() == [kept]


def test_forgetting_orphans_leaves_user_files(data_root: Path) -> None:
    user = _file(data_root, "hydrometry/mine.csv")
    sidecar_path_for(user).write_text('{"source": "file", "sha256": "' + "0" * 64 + '"}')
    assert CacheIndex(data_root).forget_orphans() == []
    assert sidecar_path_for(user).exists()


_SUBSUMED = {
    "a smaller grid": ((2, 2, 3, 3), {}, True),
    "an equal grid": (BOX, {}, True),
    "a grid outside": ((20, 20, 30, 30), {}, False),
    "a grid that overflows": ((-1, 2, 3, 3), {}, False),
    "a station": ((2, 2, 2, 2), {"station_id": "S"}, False),
    "another source": ((2, 2, 3, 3), {"source": "other"}, False),
    "a longer period": (
        (2, 2, 3, 3),
        {"date_start": "1990-01-01", "date_end": "2020-12-31"},
        False,
    ),
    "a shorter period": (
        (2, 2, 3, 3),
        {"date_start": "2001-01-01", "date_end": "2002-12-31"},
        True,
    ),
}


@pytest.mark.parametrize(("box", "fields", "gone"), _SUBSUMED.values(), ids=_SUBSUMED.keys())
def test_subsume_removes_the_grids_the_kept_one_contains(
    data_root: Path, box: tuple, fields: dict, gone: bool
) -> None:
    index = CacheIndex(data_root)
    fields = {"date_start": "2000-01-01", "date_end": "2020-12-31", **fields}
    other = _record(index, "recharge/small.nc", bbox=box, body=b"small", **fields)
    keep = _record(
        index, "recharge/big.nc", bbox=BOX, date_start="2000-01-01", date_end="2020-12-31"
    )

    count = index.subsume(keep)

    assert count == int(gone)
    assert other.path.exists() is not gone
    assert keep.path.exists()


def test_subsume_never_removes_the_kept_row_nor_a_user_file(data_root: Path) -> None:
    index = CacheIndex(data_root)
    user = _file(data_root, "recharge/mine.nc")
    sidecar_path_for(user).write_text('{"source": "file", "sha256": "' + "0" * 64 + '"}')
    keep = _record(index, "recharge/big.nc", bbox=BOX)
    assert index.subsume(keep) == 0
    assert keep.path.exists() and user.exists()


def test_a_kept_row_without_a_box_subsumes_nothing(data_root: Path) -> None:
    index = CacheIndex(data_root)
    other = _record(index, "recharge/small.nc", bbox=(1, 1, 2, 2))
    keep = _record(index, "recharge/nobox.nc", body=b"other")
    assert index.subsume(keep) == 0
    assert other.path.exists()


def test_subsume_leaves_a_grid_another_process_wrote_after_it_opened(data_root: Path) -> None:
    """A sibling prepare child may still read the grid it has just written."""
    index = CacheIndex(data_root)
    other = _record(CacheIndex(data_root), "recharge/small.nc", bbox=(1, 1, 2, 2))
    later = time.time_ns() + 10**9
    os.utime(sidecar_path_for(other.path), ns=(later, later))
    keep = _record(index, "recharge/big.nc", bbox=BOX, body=b"big")

    assert index.subsume(keep) == 0
    assert other.path.exists()

    earlier = time.time_ns() - 10**9
    os.utime(sidecar_path_for(other.path), ns=(earlier, earlier))
    fresh = CacheIndex(data_root)
    keep = _record(fresh, "recharge/big.nc", bbox=BOX, body=b"big")
    assert fresh.subsume(keep) == 1
    assert not other.path.exists()


# -- freshness --------------------------------------------------------------------------


def test_a_file_untouched_is_fresh(data_root: Path) -> None:
    index = CacheIndex(data_root)
    assert not index.is_stale(_record(index, "dem/d.tif"))


def test_a_file_copied_later_with_the_same_bytes_is_fresh(data_root: Path) -> None:
    index = CacheIndex(data_root)
    row = _record(index, "dem/d.tif")
    later = time.time() + 60
    os.utime(row.path, (later, later))
    assert not index.is_stale(row)


def test_a_file_of_other_bytes_is_stale(data_root: Path) -> None:
    index = CacheIndex(data_root)
    row = _record(index, "dem/d.tif")
    row.path.write_bytes(b"other bytes")
    assert index.is_stale(row)


def test_a_file_rewritten_later_with_the_same_size_is_stale(data_root: Path) -> None:
    index = CacheIndex(data_root)
    row = _record(index, "dem/d.tif")
    row.path.write_bytes(b"atad")
    later = time.time() + 60
    os.utime(row.path, (later, later))
    assert index.is_stale(row)


def test_a_missing_file_is_stale_and_an_empty_row_never(data_root: Path) -> None:
    index = CacheIndex(data_root)
    row = _record(index, "dem/d.tif")
    row.path.unlink()
    assert index.is_stale(row)
    folder = data_root / "hydrometry"
    folder.mkdir()
    empty = index.record_empty(
        empty_path_for(folder, "hydrometry_src_Z"),
        variable="hydrometry",
        source="src",
        station_id="Z",
    )
    assert not index.is_stale(empty)


# -- what the cache deletes ---------------------------------------------------------------


def test_a_derived_copy_under_blobs_is_no_row(data_root: Path) -> None:
    copy = _file(data_root, "blobs/geology/file/mine_clip_1.gpkg")
    write_sidecar(
        copy,
        _Sidecar(source="brgm_1m", variable="geology", sha256="0" * 64, bytes=4),
    )
    index = CacheIndex(data_root)
    assert index.rows() == []
    assert copy.exists()


def test_a_file_is_one_row_whatever_records_it(data_root: Path) -> None:
    index = CacheIndex(data_root)
    first = _record(index, "geology/shared.gpkg", source="brgm_1m")
    second = index.record(first.path, variable="geology", source="brgm_50k")

    assert index.rows() == [second]
    index.forget(second, delete_file=True)
    assert not first.path.exists()


# -- the station and grid variables read back their own writes ----------------------------
# These cases run through the variables of hydromodpy/data/families, which take
# the index of their store as ``index``.


class _Stations(StationVariable):
    VARIABLE_NAME = "hydrometry"
    INTERNAL_UNIT = "m3/s"

    def _fetch_from_source(self, source_cfg):
        raise AssertionError("the cache must answer")


class _Grids(GridVariable):
    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/day"

    def _fetch_from_source(self, source_cfg):
        raise AssertionError("the cache must answer")


def _station_record(station: str, start: str, end: str) -> PointRecord:
    dates = pd.date_range(start, end, freq="D")
    return PointRecord(
        station_id=station,
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": np.arange(len(dates), dtype=float)}),
        date_start=datetime.fromisoformat(start),
        date_end=datetime.fromisoformat(end),
    )


def test_a_station_download_is_read_back_from_the_cache(data_root: Path) -> None:
    index = CacheIndex(data_root)
    variable = _Stations(config=None, index=index, data_dir=data_root / "hydrometry")
    record = _station_record("X1", "2020-01-01", "2020-01-03")
    variable._persist_api_records([record], "hubeau")

    cached = _Stations(
        config=None, index=CacheIndex(data_root), data_dir=data_root / "hydrometry"
    )._load_cached_api_record(source="hubeau", station_id="X1")

    assert cached is not None
    assert cached.data["value"].tolist() == [0.0, 1.0, 2.0]
    # The record names the file it was read from: the seal records it as an input.
    assert record.file_path == cached.file_path
    assert cached.file_path.parent == data_root / "hydrometry"
    assert cached.file_path.name.startswith("hydrometry_hubeau_X1_")


def test_a_grid_download_is_read_back_from_the_cache(data_root: Path) -> None:
    bbox = (0.0, 0.0, 1.0, 1.0)
    grid = xr.Dataset(
        {"recharge": (("y", "x"), np.ones((2, 2)))}, coords={"y": [0, 1], "x": [0, 1]}
    )
    record = FieldRecord(
        variable="recharge",
        source="sim2",
        unit="mm/day",
        data=grid,
        bbox=bbox,
        crs="EPSG:2154",
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 12, 31),
    )
    variable = _Grids(
        config=None,
        index=CacheIndex(data_root),
        data_dir=data_root / "recharge",
        project_period=(datetime(2020, 1, 1), datetime(2020, 12, 31)),
    )
    variable._persist_field_records([record], "sim2")
    cached = variable._find_cached_fields(source="sim2", variable_names=["recharge"], bbox=bbox)

    assert cached is not None
    assert float(cached[0].data["recharge"].sum()) == 4.0
    stored = Path(cached[0].metadata["source_path"])
    assert stored.parent == data_root / "recharge"
    assert record.metadata["source_path"] == str(stored)


def test_a_river_network_download_is_read_back_from_the_cache(data_root: Path) -> None:
    import geopandas as gpd
    from shapely.geometry import LineString

    from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

    bbox = (0.0, 0.0, 1.0, 1.0)
    network = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:4326")
    # The constructor starts a Whitebox backend the cache path never uses.
    variable = object.__new__(HydrographyVariable)
    variable._index = CacheIndex(data_root)
    variable._data_dir = data_root / "hydrography"
    variable._persist_and_register(network, "bdtopage", bbox)
    cached = variable._try_load_cached("bdtopage", bbox)

    assert cached is not None
    assert len(cached) == 1


# -- a frozen run never downloads a gap ----------------------------------------------------
# The missing days used to be fetched, merged into the cached chronicle and
# written under a new name, which deleted the file the lockfile pins.


def _no_download(*_args):
    raise AssertionError("a frozen run reached the network")


def _project(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    project = workspace / "projects" / "demo"
    project.mkdir(parents=True)
    (workspace / "data" / "hydrometry").mkdir(parents=True)
    (project / "project.toml").write_text("# placeholder\n")
    return workspace, project


def _stations(workspace: Path, period: tuple[datetime, datetime]) -> _Stations:
    return _Stations(
        config=SimpleNamespace(),
        index=CacheIndex(workspace / "data"),
        project_period=period,
        data_dir=workspace / "data" / "hydrometry",
    )


def _lock(project: Path) -> None:
    from hydromodpy.project.data_cache import lock_data

    lock_data(project=str(project))


@pytest.fixture
def frozen_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, Path]]:
    """A workspace with one cached chronicle, its lockfile, and frozen mode on."""
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, project = _project(tmp_path)
    _stations(workspace, (datetime(2000, 1, 1), datetime(2000, 1, 31)))._persist_api_records(
        [_station_record("A", "2000-01-01", "2000-01-31")], "hubeau"
    )
    _lock(project)
    set_frozen_mode(True, project_root=project)
    try:
        yield workspace, workspace / "data" / "hydrometry"
    finally:
        set_frozen_mode(False)


def test_a_longer_period_is_refused_before_the_download(frozen_project: tuple[Path, Path]) -> None:
    workspace, data_dir = frozen_project
    before = sorted(p.name for p in data_dir.iterdir())
    variable = _stations(workspace, (datetime(2000, 1, 1), datetime(2000, 2, 28)))
    cfg = SimpleNamespace(station_ids=["A"], force_refresh=False)

    with pytest.raises(DataCacheError, match="Frozen data mode forbids a download") as info:
        variable._fetch_with_station_cache(cfg, _no_download, source_name="hubeau")

    assert "cached from 2000-01-01 to 2000-01-31" in str(info.value)
    assert "asks for 2000-01-01 to 2000-02-28" in str(info.value)
    assert sorted(p.name for p in data_dir.iterdir()) == before


def test_a_search_by_extent_is_refused_before_the_download(
    frozen_project: tuple[Path, Path],
) -> None:
    workspace, _ = frozen_project
    variable = _stations(workspace, (datetime(2000, 1, 1), datetime(2000, 1, 31)))
    cfg = SimpleNamespace(station_ids=[], force_refresh=False)

    with pytest.raises(DataCacheError, match="asked for by extent or with force_refresh"):
        variable._fetch_with_station_cache(cfg, _no_download, source_name="hubeau")


def test_a_covered_period_is_served_from_the_cache(frozen_project: tuple[Path, Path]) -> None:
    workspace, _ = frozen_project
    variable = _stations(workspace, (datetime(2000, 1, 5), datetime(2000, 1, 20)))
    cfg = SimpleNamespace(station_ids=["A"], force_refresh=False, mask_path=None)

    records = variable._fetch_with_station_cache(cfg, _no_download, source_name="hubeau")

    assert [r.station_id for r in records] == ["A"]


def _short_station_project(tmp_path: Path, window: tuple[datetime, datetime] | None) -> Path:
    """A workspace whose station B has no value on the last day of the window."""
    workspace, project = _project(tmp_path)
    variable = _stations(workspace, (datetime(2000, 1, 1), datetime(2000, 1, 31)))
    if window is None:
        # A normal run asks for the window; the provider has nothing after the 30th.
        cfg = SimpleNamespace(station_ids=["B"], force_refresh=False, mask_path=None)
        variable._fetch_with_station_cache(
            cfg,
            lambda ids, start, end: [_station_record("B", "2000-01-01", "2000-01-30")],
            source_name="hubeau",
        )
    else:
        variable._persist_api_records(
            [_station_record("B", "2000-01-01", "2000-01-30")], "hubeau", window=window
        )
    _lock(project)
    return project


def test_a_station_shorter_than_its_window_replays_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ONDE campaigns and sparse gauges never fill the window they were asked for."""
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    project = _short_station_project(tmp_path, window=None)
    workspace = project.parent.parent
    set_frozen_mode(True, project_root=project)
    try:
        variable = _stations(workspace, (datetime(2000, 1, 1), datetime(2000, 1, 31)))
        cfg = SimpleNamespace(station_ids=["B"], force_refresh=False, mask_path=None)
        records = variable._fetch_with_station_cache(cfg, _no_download, source_name="hubeau")
    finally:
        set_frozen_mode(False)
    assert [r.station_id for r in records] == ["B"]
    assert records[0].date_end == datetime(2000, 1, 30)


def test_an_empty_gap_is_asked_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gap the provider has nothing for is recorded as asked, then never asked again."""
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    project = _short_station_project(tmp_path, window=(datetime(2000, 1, 1), datetime(2000, 1, 30)))
    workspace = project.parent.parent
    asked: list[tuple[datetime, datetime]] = []

    def provider(ids, start, end):
        asked.append((start, end))
        return []

    cfg = SimpleNamespace(station_ids=["B"], force_refresh=False, mask_path=None)
    for _ in range(2):
        variable = _stations(workspace, (datetime(2000, 1, 1), datetime(2000, 1, 31)))
        records = variable._fetch_with_station_cache(cfg, provider, source_name="hubeau")
        assert [r.station_id for r in records] == ["B"]
    assert asked == [(datetime(2000, 1, 31), datetime(2000, 1, 31))]


def test_an_empty_station_answers_for_its_window_only(tmp_path: Path) -> None:
    (tmp_path / "data" / "d").mkdir(parents=True)
    january = (datetime(2000, 1, 1), datetime(2000, 1, 31))
    variable = _Stations(
        config=SimpleNamespace(),
        index=CacheIndex(tmp_path / "data"),
        project_period=january,
        data_dir=tmp_path / "data" / "d",
    )
    variable._register_empty_api_stations(["B"], "hubeau")

    assert variable._is_empty_sentinel("hubeau", "B")
    variable.project_period = (datetime(2000, 1, 10), datetime(2000, 1, 20))
    assert variable._is_empty_sentinel("hubeau", "B")
    variable.project_period = (datetime(2000, 1, 1), datetime(2000, 3, 1))
    assert not variable._is_empty_sentinel("hubeau", "B")
