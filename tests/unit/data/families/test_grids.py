"""Grid variables: the NetCDF file name of a box, the file results, and what a grid variable
leaves in the data folder (one NetCDF and one sidecar per box and period).
Boxes are (xmin, ymin, xmax, ymax) in the grid CRS, recharge is in mm/day.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import xarray as xr

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.families.grids import GridVariable
from hydromodpy.data.provenance.sidecars import CacheIndex, scan
from tests._helpers.data_climatic_builders import _make_field_record

PERIOD = (datetime(2020, 1, 1), datetime(2020, 12, 31))
BIG = (0.0, 0.0, 10.0, 10.0)
SMALL = (2.0, 2.0, 4.0, 4.0)


class _Recharge(GridVariable):
    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/day"

    def _fetch_from_source(self, source_cfg):
        return []


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


@pytest.mark.fast
def test_same_box_same_file_name():
    bbox = (1.5, 2.5, 3.5, 4.5)

    assert GridVariable._nc_filename("etp", "sim2", bbox, None, None) == GridVariable._nc_filename(
        "etp", "sim2", bbox, None, None
    )


@pytest.mark.fast
def test_no_box_no_dates_file_name():
    assert GridVariable._nc_filename("recharge", "custom", None, None, None) == "recharge_custom.nc"


@pytest.mark.fast
def test_no_file_result():
    source_cfg = MagicMock()
    source_cfg.mask_path = None

    assert _Recharge(config=None, index=None)._handle_file_results([], source_cfg) == []


@pytest.mark.fast
def test_user_file_is_no_row():
    index = MagicMock()
    variable = _Recharge(config=None, index=index)
    source_cfg = MagicMock()
    source_cfg.mask_path = None

    result = variable._handle_file_results([_make_field_record()], source_cfg)

    assert len(result) == 1
    assert isinstance(result[0], FieldRecord)
    # The file is read where it lies: nothing is written to the index.
    assert index.mock_calls == []


def test_bigger_grid_removes_smaller(data_root: Path) -> None:
    variable = _variable(data_root)
    variable._persist_field_records([_grid(SMALL)], "sim2")
    small = scan(data_root).rows[0].path

    variable._persist_field_records([_grid(BIG)], "sim2")

    (row,) = scan(data_root).rows
    assert row.bbox == BIG
    assert not small.exists() and not Path(str(small) + ".json").exists()


def test_smaller_grid_keeps_bigger(data_root: Path) -> None:
    variable = _variable(data_root)
    variable._persist_field_records([_grid(BIG)], "sim2")

    variable._persist_field_records([_grid(SMALL)], "sim2")

    assert sorted(row.bbox for row in scan(data_root).rows) == [BIG, SMALL]


def test_bigger_grid_answers_smaller_box(data_root: Path) -> None:
    _variable(data_root)._persist_field_records([_grid(BIG)], "sim2")

    found = _variable(data_root)._find_cached_fields(
        source="sim2", variable_names=["recharge"], bbox=SMALL
    )

    assert found is not None and found[0].bbox == BIG
    assert found[0].source_unit == "mm/j"


def test_edited_grid_is_fetched_again(data_root: Path) -> None:
    _variable(data_root)._persist_field_records([_grid(BIG)], "sim2")
    (row,) = scan(data_root).rows
    row.path.write_bytes(b"not a grid")

    found = _variable(data_root)._find_cached_fields(
        source="sim2", variable_names=["recharge"], bbox=BIG
    )

    assert found is None
    assert scan(data_root).rows == ()


def test_outside_file_is_no_row(data_root: Path, tmp_path: Path) -> None:
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
