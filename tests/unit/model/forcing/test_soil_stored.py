"""The soil codec writes and reads ``SoilForcings`` bit for bit.

``write_soil_forcings`` drops a ``SoilForcings`` into a directory as
``soil.npz`` (every array, with its dtype) and ``soil.json`` (the scalar
fields). ``read_soil_forcings`` rebuilds the object, the kernel parameters
recomputed from the config and the three records rebuilt by
``grid_field_record`` on the loaded precipitation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.model.forcing.soil_columns import SoilColumns
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.forcing.soil_forcing import SoilForcings, soil_parameters
from hydromodpy.model.forcing.soil_grids import grid_field_record
from hydromodpy.model.forcing.soil_stored import read_soil_forcings, write_soil_forcings
from hydromodpy.model.soil.kernel import SoilFluxes, SoilState

_CRS = "EPSG:2154"

_FLUX_SERIES = (
    "etr",
    "residual_etp",
    "recharge",
    "runoff",
    "runoff_cn",
    "soil_storage",
    "transit_storage",
    "cn_storage",
    "lag_storage",
)
_FLUX_STARTS = (
    "soil_storage_start",
    "transit_storage_start",
    "cn_storage_start",
    "lag_storage_start",
)
_COLUMN_ARRAYS = (
    "cell_index",
    "class_index",
    "x",
    "y",
    "ru_shape",
    "cell_fraction",
    "basin_weight",
)


def _like():
    days = pd.date_range("2015-01-01", periods=10, freq="D").values
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([100.0, 0.0])
    dataset = xr.Dataset(
        {"precipitation": (("time", "y", "x"), np.zeros((len(days), y.size, x.size)))},
        coords={"time": days, "y": y, "x": x},
    )
    record = FieldRecord(
        variable="precipitation",
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 100.0, 100.0),
        crs=_CRS,
        date_start=pd.Timestamp(days[0]),
        date_end=pd.Timestamp(days[-1]),
    )
    return LoadResult(fields=[record]), days, x, y, record


def _columns(with_capacity: bool, x: np.ndarray, y: np.ndarray) -> SoilColumns:
    n_cells = x.size * y.size
    col_x = np.tile(x, y.size)
    col_y = np.repeat(y, x.size)
    if with_capacity:
        cell_index = np.repeat(np.arange(n_cells), 3).astype(np.int64)
        class_index = np.tile(np.arange(3), n_cells).astype(np.int64)
        cell_fraction = np.full(n_cells * 3, 1.0 / 3.0)
        return SoilColumns(
            cell_index=cell_index,
            class_index=class_index,
            x=np.repeat(col_x, 3),
            y=np.repeat(col_y, 3),
            ru_shape=np.full(n_cells * 3, 0.8),
            cell_fraction=cell_fraction,
            basin_weight=cell_fraction / n_cells,
            raster_mean_mm=120.0,
        )
    return SoilColumns(
        cell_index=np.arange(n_cells).astype(np.int64),
        class_index=np.zeros(n_cells, dtype=np.int64),
        x=col_x,
        y=col_y,
        ru_shape=np.ones(n_cells),
        cell_fraction=np.ones(n_cells),
        basin_weight=np.full(n_cells, 1.0 / n_cells),
        raster_mean_mm=None,
    )


def _soil_forcings(*, with_capacity, cycles, never_full):
    like, days, x, y, record = _like()
    columns = _columns(with_capacity, x, y)
    config = SoilReservoirConfig(ru=150.0)
    parameters = soil_parameters(config, config.ru * columns.ru_shape)

    n_days = len(days)
    n_columns = columns.cell_index.size
    rng = np.random.default_rng(2)
    precipitation = rng.gamma(2.0, 2.0, size=(n_days, n_columns))
    etp = np.full((n_days, n_columns), 2.0)
    series = {name: rng.random((n_days, n_columns)) for name in _FLUX_SERIES}
    starts = {name: rng.random(n_columns) for name in _FLUX_STARTS}
    fluxes = SoilFluxes(
        **series,
        **starts,
        end=SoilState(
            soil_mm=rng.random(n_columns),
            transit_mm=rng.random(n_columns),
            cn_storage_mm=rng.random(n_columns),
        ),
    )

    n_cells = x.size * y.size
    recharge_grid = rng.random((n_days, y.size, x.size))
    residual_etp_grid = rng.random((n_days, y.size, x.size))
    runoff_grid = rng.random((n_days, y.size, x.size))
    holding = LoadResult
    forcings = SoilForcings(
        recharge=holding(
            fields=[
                grid_field_record(
                    "recharge",
                    recharge_grid.reshape(n_days, n_cells),
                    x=x,
                    y=y,
                    days=days,
                    like=record,
                )
            ]
        ),
        residual_etp=holding(
            fields=[
                grid_field_record(
                    "etp",
                    residual_etp_grid.reshape(n_days, n_cells),
                    x=x,
                    y=y,
                    days=days,
                    like=record,
                )
            ]
        ),
        runoff=holding(
            fields=[
                grid_field_record(
                    "runoff",
                    runoff_grid.reshape(n_days, n_cells),
                    x=x,
                    y=y,
                    days=days,
                    like=record,
                )
            ]
        ),
        days=days,
        precipitation=precipitation,
        etp=etp,
        fluxes=fluxes,
        columns=columns,
        config=config,
        parameters=parameters,
        spinup_cycles=cycles,
        never_full_columns=never_full,
        crs=_CRS,
    )
    return forcings, like, config


def _assert_same_arrays(left: np.ndarray, right: np.ndarray) -> None:
    np.testing.assert_array_equal(left, right)
    assert left.dtype == right.dtype


def _assert_same(left: SoilForcings, right: SoilForcings) -> None:
    _assert_same_arrays(left.days, right.days)
    _assert_same_arrays(left.precipitation, right.precipitation)
    _assert_same_arrays(left.etp, right.etp)
    for name in _FLUX_SERIES + _FLUX_STARTS:
        _assert_same_arrays(getattr(left.fluxes, name), getattr(right.fluxes, name))
    for name in ("soil_mm", "transit_mm", "cn_storage_mm"):
        _assert_same_arrays(getattr(left.fluxes.end, name), getattr(right.fluxes.end, name))
    for name in _COLUMN_ARRAYS:
        _assert_same_arrays(getattr(left.columns, name), getattr(right.columns, name))
    assert left.columns.raster_mean_mm == right.columns.raster_mean_mm
    for left_result, right_result in (
        (left.recharge, right.recharge),
        (left.residual_etp, right.residual_etp),
        (left.runoff, right.runoff),
    ):
        assert type(right_result) is type(left_result)
        assert len(right_result.fields) == 1
        left_field = left_result.fields[0]
        right_field = right_result.fields[0]
        assert type(right_field) is type(left_field)
        assert right_field.variable == left_field.variable
        assert right_field.unit == left_field.unit
        assert right_field.bbox == left_field.bbox
        assert right_field.crs == left_field.crs
        _assert_same_arrays(
            right_field.data[right_field.variable].values,
            left_field.data[left_field.variable].values,
        )
        for coord in ("x", "y", "time"):
            _assert_same_arrays(right_field.data[coord].values, left_field.data[coord].values)
    assert left.spinup_cycles == right.spinup_cycles
    assert left.never_full_columns == right.never_full_columns
    assert left.crs == right.crs
    _assert_same_arrays(left.parameters.ru_mm, right.parameters.ru_mm)
    for name in (
        "alpha",
        "kc",
        "impervious_fraction",
        "bypass_fraction",
        "transit_time_days",
        "curve_number",
        "runoff_time_days",
        "runoff_lag_days",
    ):
        assert getattr(left.parameters, name) == getattr(right.parameters, name)


def _roundtrip(tmp_path, forcings, like, config):
    write_soil_forcings(forcings, tmp_path)
    return read_soil_forcings(tmp_path, like=like, config=config)


ROUND_TRIPS = [
    pytest.param(False, 0, 0, id="uniform soil"),
    pytest.param(True, 7, 3, id="capacity classes with spinup counts"),
]


@pytest.mark.parametrize(("with_capacity", "cycles", "never_full"), ROUND_TRIPS)
def test_round_trip(tmp_path, with_capacity, cycles, never_full) -> None:
    forcings, like, config = _soil_forcings(
        with_capacity=with_capacity, cycles=cycles, never_full=never_full
    )
    _assert_same(forcings, _roundtrip(tmp_path, forcings, like, config))


def test_truncated_product_is_refused(tmp_path) -> None:
    forcings, like, config = _soil_forcings(with_capacity=False, cycles=0, never_full=0)
    write_soil_forcings(forcings, tmp_path)
    stored = tmp_path / "soil.npz"
    stored.write_bytes(stored.read_bytes()[:100])
    with pytest.raises(ValueError, match="unreadable"):
        read_soil_forcings(tmp_path, like=like, config=config)
