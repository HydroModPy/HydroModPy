"""Without a raster, one soil column is one SAFRAN cell, in (y, x) order.

``compute_soil_forcings`` flattens the precipitation grid row-major: the
column at ``cell_index = iy * nx + ix`` carries the coordinates and the daily
series of the grid cell ``(iy, ix)``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil_recharge import compute_soil_forcings

_CRS = "EPSG:2154"
_NY, _NX = 2, 3


def _grid_result(variable: str, values: np.ndarray, *, days, x, y) -> LoadResult:
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)},
        coords={"time": days, "y": y, "x": x},
    )
    record = FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(x.min(), y.min(), x.max(), y.max()),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    return LoadResult(fields=[record])


def _forcings():
    days = pd.date_range("2015-01-01", periods=20, freq="D")
    x = np.array([0.0, 100.0, 200.0])
    y = np.array([500.0, 300.0])
    # Every cell carries a distinct, time-constant precipitation, so a
    # column's series identifies the cell it came from.
    cell_value = np.arange(_NY * _NX, dtype=np.float64).reshape(_NY, _NX)
    precipitation = np.broadcast_to(cell_value, (len(days), _NY, _NX)).copy()
    etp = np.zeros((len(days), _NY, _NX))
    precip_result = _grid_result("precipitation", precipitation, days=days, x=x, y=y)
    etp_result = _grid_result("etp", etp, days=days, x=x, y=y)
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    config = SoilReservoirConfig(ru=100.0, spinup="none")
    forcings = compute_soil_forcings(
        precipitation=precip_result, etp=etp_result, config=config, window=window, model_crs=_CRS
    )
    return forcings, x, y, cell_value


def test_the_column_count_is_the_cell_count() -> None:
    forcings, *_ = _forcings()
    assert forcings.columns.cell_index.size == _NY * _NX
    np.testing.assert_array_equal(forcings.columns.cell_index, np.arange(_NY * _NX))


def test_a_columns_coordinates_are_its_cells_centre() -> None:
    forcings, x, y, _cell_value = _forcings()
    for iy in range(_NY):
        for ix in range(_NX):
            n = iy * _NX + ix
            assert forcings.columns.x[n] == x[ix]
            assert forcings.columns.y[n] == y[iy]


def test_a_columns_series_is_its_cells_precipitation() -> None:
    forcings, _x, _y, cell_value = _forcings()
    for iy in range(_NY):
        for ix in range(_NX):
            n = iy * _NX + ix
            np.testing.assert_array_equal(forcings.precipitation[:, n], cell_value[iy, ix])
