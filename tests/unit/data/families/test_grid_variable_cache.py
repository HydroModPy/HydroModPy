"""What a grid variable leaves in the data folder: one NetCDF and one sidecar per box and period."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.families.grids import GridVariable
from hydromodpy.data.provenance.sidecars import CacheIndex, scan

PERIOD = (datetime(2020, 1, 1), datetime(2020, 12, 31))
BIG = (0.0, 0.0, 10.0, 10.0)
SMALL = (2.0, 2.0, 4.0, 4.0)


class _Recharge(GridVariable):
    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/day"


def _grid(bbox: tuple, *, start=PERIOD[0], end=PERIOD[1], value: float = 1.0) -> FieldRecord:
    data = xr.Dataset(
        {"recharge": (("y", "x"), np.full((2, 2), value))}, coords={"y": [0, 1], "x": [0, 1]}
    )
    return FieldRecord(
        variable="recharge",
        source="sim2",
        unit="mm/day",
        data=data,
        bbox=bbox,
        crs="EPSG:2154",
        date_start=start,
        date_end=end,
        frequency="D",
        source_unit="mm/j",
    )


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


def _variable(data_root: Path) -> _Recharge:
    folder = data_root / "recharge"
    folder.mkdir(parents=True, exist_ok=True)
    return _Recharge(
        config=None, index=CacheIndex(data_root), project_period=PERIOD, data_dir=folder
    )


def test_a_bigger_grid_removes_the_smaller_one_it_contains(data_root: Path) -> None:
    variable = _variable(data_root)
    variable._persist_field_records([_grid(SMALL)], "sim2")
    small = scan(data_root).rows[0].path

    variable._persist_field_records([_grid(BIG)], "sim2")

    (row,) = scan(data_root).rows
    assert row.bbox == BIG
    assert not small.exists() and not Path(str(small) + ".json").exists()


def test_a_smaller_grid_does_not_remove_the_bigger_one(data_root: Path) -> None:
    variable = _variable(data_root)
    variable._persist_field_records([_grid(BIG)], "sim2")

    variable._persist_field_records([_grid(SMALL)], "sim2")

    assert sorted(row.bbox for row in scan(data_root).rows) == [BIG, SMALL]


def test_the_bigger_grid_answers_for_the_smaller_box(data_root: Path) -> None:
    _variable(data_root)._persist_field_records([_grid(BIG)], "sim2")

    found = _variable(data_root)._find_cached_fields(
        source="sim2", variable_names=["recharge"], bbox=SMALL
    )

    assert found is not None and found[0].bbox == BIG
    assert found[0].source_unit == "mm/j"


def test_a_grid_file_edited_by_hand_is_fetched_again(data_root: Path) -> None:
    _variable(data_root)._persist_field_records([_grid(BIG)], "sim2")
    (row,) = scan(data_root).rows
    row.path.write_bytes(b"not a grid")

    found = _variable(data_root)._find_cached_fields(
        source="sim2", variable_names=["recharge"], bbox=BIG
    )

    assert found is None
    assert scan(data_root).rows == ()


def test_a_file_a_source_keeps_outside_the_data_folder_is_no_row(
    data_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere" / "recharge_own_cache.nc"
    outside.parent.mkdir()
    _grid(BIG).data.to_netcdf(outside)
    record = FieldRecord(
        variable="recharge",
        source="own",
        unit="mm/day",
        data=outside,
        bbox=BIG,
        crs="EPSG:2154",
        date_start=PERIOD[0],
        date_end=PERIOD[1],
    )

    _variable(data_root)._persist_field_records([record], "own")

    assert scan(data_root).rows == ()
    assert record.metadata["source_path"] == str(outside)
    assert outside.is_file()
