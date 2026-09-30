"""A first year that never brings the soil back to the same state stops the run.

With ``spinup = "first_year"``, a climate whose net yearly flux keeps
draining a soil far too large to reach an approximate equilibrium in 20
repetitions raises X13 rather than starting the run from a moving state.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil_recharge import compute_soil_forcings

_CRS = "EPSG:2154"


def _grid_record(variable: str, values: np.ndarray, *, days, x, y) -> FieldRecord:
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)}, coords={"time": days, "y": y, "x": x}
    )
    return FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 100.0, 100.0),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )


def test_a_first_year_that_keeps_draining_a_huge_soil_is_refused() -> None:
    days = pd.date_range("2015-01-01", periods=365, freq="D")
    x = np.array([0.0])
    y = np.array([0.0])
    # A little rain most days, a touch less than the steady demand: with
    # ru = 1000 mm the soil stays in the linear ETR regime the whole year and
    # drains by only a few mm a cycle, far too slowly to settle in 20 tries.
    precipitation = np.full((len(days), 1, 1), 0.25)
    precipitation[10, 0, 0] = 5.0  # a spike so X11 does not fire instead
    etp = np.full((len(days), 1, 1), 0.30)

    precip_result = LoadResult(
        fields=[_grid_record("precipitation", precipitation, days=days, x=x, y=y)]
    )
    etp_result = LoadResult(fields=[_grid_record("etp", etp, days=days, x=x, y=y)])
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    config = SoilReservoirConfig(ru=1000.0, spinup="first_year")

    with pytest.raises(ConfigError) as excinfo:
        compute_soil_forcings(
            precipitation=precip_result,
            etp=etp_result,
            config=config,
            window=window,
            model_crs=_CRS,
        )

    message = str(excinfo.value)
    assert "still moved by" in message
    assert "after 20 repetitions of 2015-01-01 to 2015-12-31" in message
    assert 'spinup = "none"' in message
