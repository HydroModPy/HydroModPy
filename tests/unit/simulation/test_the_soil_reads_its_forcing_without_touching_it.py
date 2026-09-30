"""The orchestrator opens a forcing file itself, never through the shared cache.

``FieldRecord.dataset`` opens a path and caches the result on the shared
record (spec section 4.3, before the guard table). ``compute_soil_forcings``
must not go through it: a ``FieldRecord`` whose ``data`` is a path stays a
path after the call, and the precipitation array handed to the kernel is
never mutated by the reservoir.
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


def _write_grid(tmp_path, variable: str, values: np.ndarray, *, days, x, y):
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)}, coords={"time": days, "y": y, "x": x}
    )
    path = tmp_path / f"{variable}.nc"
    dataset.to_netcdf(path)
    return path


def test_a_file_backed_record_stays_a_path_after_the_run(tmp_path) -> None:
    days = pd.date_range("2015-01-01", periods=15, freq="D")
    x = np.array([0.0, 100.0])
    y = np.array([100.0, 0.0])
    precip_values = np.full((len(days), 2, 2), 5.0)
    etp_values = np.full((len(days), 2, 2), 2.0)

    precip_path = _write_grid(tmp_path, "precipitation", precip_values, days=days, x=x, y=y)
    etp_path = _write_grid(tmp_path, "etp", etp_values, days=days, x=x, y=y)

    precip_record = FieldRecord(
        variable="precipitation",
        source="sim2",
        unit="mm/day",
        data=precip_path,
        bbox=(0.0, 0.0, 100.0, 100.0),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    etp_record = FieldRecord(
        variable="etp",
        source="sim2",
        unit="mm/day",
        data=etp_path,
        bbox=(0.0, 0.0, 100.0, 100.0),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    config = SoilReservoirConfig(ru=100.0, spinup="none")

    compute_soil_forcings(
        precipitation=LoadResult(fields=[precip_record]),
        etp=LoadResult(fields=[etp_record]),
        config=config,
        window=window,
        model_crs=_CRS,
    )

    assert precip_record.data == precip_path
    assert etp_record.data == etp_path


def test_the_kernel_never_sees_a_mutated_precipitation_array() -> None:
    days = pd.date_range("2015-01-01", periods=15, freq="D")
    x = np.array([0.0, 100.0])
    y = np.array([100.0, 0.0])
    precip_values = np.full((len(days), 2, 2), 5.0)
    etp_values = np.full((len(days), 2, 2), 2.0)
    original_precip = precip_values.copy()
    original_etp = etp_values.copy()

    precip_record = FieldRecord(
        variable="precipitation",
        source="sim2",
        unit="mm/day",
        data=xr.Dataset(
            {"precipitation": (("time", "y", "x"), precip_values)},
            coords={"time": days, "y": y, "x": x},
        ),
        bbox=(0.0, 0.0, 100.0, 100.0),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    etp_record = FieldRecord(
        variable="etp",
        source="sim2",
        unit="mm/day",
        data=xr.Dataset(
            {"etp": (("time", "y", "x"), etp_values)}, coords={"time": days, "y": y, "x": x}
        ),
        bbox=(0.0, 0.0, 100.0, 100.0),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    config = SoilReservoirConfig(ru=100.0, spinup="none")

    compute_soil_forcings(
        precipitation=LoadResult(fields=[precip_record]),
        etp=LoadResult(fields=[etp_record]),
        config=config,
        window=window,
        model_crs=_CRS,
    )

    np.testing.assert_array_equal(precip_record.data["precipitation"].values, original_precip)
    np.testing.assert_array_equal(etp_record.data["etp"].values, original_etp)
