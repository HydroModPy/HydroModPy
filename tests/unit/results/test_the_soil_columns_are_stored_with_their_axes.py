"""``write_soil_columns`` persists the soil reservoir under ``forcing/soil``."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from hydromodpy.results import field_registry
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

_DAYS = np.array(
    ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05"],
    dtype="datetime64[ns]",
)
_T, _N = 5, 3

_SERIES = {
    "etr": (
        np.full((_T, _N), 1.0),
        "mm/day",
        "time: mean",
        "Actual evapotranspiration of the soil",
    ),
    "recharge": (
        np.full((_T, _N), 2.0),
        "mm/day",
        "time: mean",
        "Recharge sent to the water table",
    ),
    "soil_storage": (
        np.full((_T, _N), 3.0),
        "mm",
        "time: point",
        "Soil water storage at the end of the day",
    ),
}

_COLUMNS = {
    "cell_index": np.array([0, 1, 2], dtype="int32"),
    "class_index": np.array([0, 0, 0], dtype="int32"),
    "x": np.array([0.0, 100.0, 200.0]),
    "y": np.array([0.0, 0.0, 0.0]),
    "ru_mm": np.array([120.0, 150.0, 100.0]),
    "cell_fraction": np.array([1.0, 1.0, 1.0]),
    "basin_weight": np.array([1 / 3, 1 / 3, 1 / 3]),
}

_ATTRS = {
    "source": "soil_reservoir",
    "crs": "EPSG:2154",
    "ru_mm": 120.0,
    "alpha": 0.6,
    "kc": 1.0,
    "impervious_fraction": 0.0,
    "bypass_fraction": 0.0,
    "transit_time_days": 0.0,
    "spinup": "first_year",
    "spinup_cycles": 2,
    "never_full_columns": 0,
    "n_cells": 3,
    "n_columns": 3,
}


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "sim.zarr"
    sz = SimulationZarr.create(path, n_cells=4, n_layers=1)
    sz.write_soil_columns(timestamps=_DAYS, series=_SERIES, columns=_COLUMNS, attrs=_ATTRS)
    sz.close()
    return path


def test_the_daily_series_carry_the_record_and_soil_column_axes(tmp_path: Path) -> None:
    path = _write(tmp_path)
    sz = SimulationZarr(path)
    try:
        soil = sz.root["forcing"]["soil"]
        assert soil["timestamps"].metadata.dimension_names == (field_registry.AXIS_RECORD,)
        for name in ("etr", "recharge", "soil_storage"):
            assert soil[name].metadata.dimension_names == (
                field_registry.AXIS_RECORD,
                field_registry.AXIS_SOIL_COLUMN,
            )
        for name in _COLUMNS:
            assert soil[name].metadata.dimension_names == (field_registry.AXIS_SOIL_COLUMN,)
    finally:
        sz.close()


def test_each_series_array_carries_its_own_units_and_cell_methods(tmp_path: Path) -> None:
    path = _write(tmp_path)
    sz = SimulationZarr(path)
    try:
        soil = sz.root["forcing"]["soil"]
        assert dict(soil["etr"].attrs)["units"] == "mm/day"
        assert dict(soil["etr"].attrs)["cell_methods"] == "time: mean"
        assert dict(soil["soil_storage"].attrs)["units"] == "mm"
        assert dict(soil["soil_storage"].attrs)["cell_methods"] == "time: point"
        assert dict(soil["ru_mm"].attrs)["units"] == "mm"
        assert dict(soil["cell_index"].attrs)["units"] == "1"
    finally:
        sz.close()


def test_the_group_carries_the_soil_configuration_as_attributes(tmp_path: Path) -> None:
    path = _write(tmp_path)
    sz = SimulationZarr(path)
    try:
        attrs = dict(sz.root["forcing"]["soil"].attrs)
        assert attrs["source"] == "soil_reservoir"
        assert attrs["spinup_cycles"] == 2
        assert attrs["never_full_columns"] == 0
        assert attrs["n_cells"] == 3
        assert attrs["n_columns"] == 3
    finally:
        sz.close()


def test_xarray_opens_the_soil_group_directly(tmp_path: Path) -> None:
    path = _write(tmp_path)

    ds = xr.open_zarr(str(path), group="forcing/soil")
    assert set(ds.sizes) == {"record", "soil_column"}
    assert ds.sizes["record"] == _T
    assert ds.sizes["soil_column"] == _N
    assert np.array_equal(ds["timestamps"].values, _DAYS)
