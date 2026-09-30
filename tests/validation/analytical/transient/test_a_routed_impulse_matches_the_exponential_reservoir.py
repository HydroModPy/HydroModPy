"""A 50 mm pulse through the soil reservoir, driven end to end by the orchestrator.

Same closed form as the kernel-level unit test
(``tests/unit/physics/test_an_impulse_through_the_transit_store_follows_the_exponential_reservoir.py``),
but reached the way a run reaches it: through ``compute_soil_forcings``, with
a single SAFRAN cell's precipitation and ETP passed in as ``FieldRecord`` and
the recharge read back from the ``FieldRecord`` it returns.

``spinup = "none"`` starts the soil full - "the state of a soil in a wet
winter", its own description says - which is exactly the soil a year of rain
has already filled. Section 7 gives the closed form for a pulse landing on
that full soil and then routed through a linear reservoir of time constant
``k``: ``Q(0) = 50(1 - k a)``, ``Q(t>=1) = 50 k a^2 exp(-(t-1)/k)`` with
``a = 1 - exp(-1/k)``. ``t95``, the day the cumulative recharge first reaches
95 % of the 50 mm pulse, follows the continuous crossing ``-k ln(0.05)``
within the one day the discretisation can miss it by.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil_recharge import compute_soil_forcings
from tests._helpers.tolerances import tol

_CRS = "EPSG:2154"
_TRANSIT_TIMES_DAYS = (2.0, 5.0, 20.0)


def _closed_form(transit_time_days: float, n_days: int) -> np.ndarray:
    k = transit_time_days
    a = 1.0 - np.exp(-1.0 / k)
    t = np.arange(n_days)
    return np.where(t == 0, 50.0 * (1.0 - k * a), 50.0 * k * a * a * np.exp(-(t - 1) / k))


def _single_cell_result(variable: str, values: np.ndarray, *, days: pd.DatetimeIndex) -> LoadResult:
    """One ``FieldRecord`` on a single SAFRAN cell, the orchestrator's own input shape."""
    x = np.array([0.0])
    y = np.array([0.0])
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values.reshape(-1, 1, 1))},
        coords={"time": days, "y": y, "x": x},
    )
    record = FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 0.0, 0.0),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    return LoadResult(fields=[record])


def _t95(recharge: np.ndarray) -> int:
    """First day whose cumulative recharge reaches 95 % of the 50 mm pulse."""
    cumulative = np.cumsum(recharge)
    return int(np.argmax(cumulative >= 0.95 * 50.0))


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.parametrize("transit_time_days", _TRANSIT_TIMES_DAYS)
def test_a_routed_impulse_matches_the_exponential_reservoir(transit_time_days: float) -> None:
    n_days = int(60 * transit_time_days) + 10
    days = pd.date_range("2015-01-01", periods=n_days, freq="D")
    precipitation = np.zeros(n_days)
    precipitation[0] = 50.0
    etp = np.zeros(n_days)

    precip_result = _single_cell_result("precipitation", precipitation, days=days)
    etp_result = _single_cell_result("etp", etp, days=days)
    window = ResolvedSimulationTimeWindow(
        start=days[0],
        end=days[-1],
        step_value=1,
        step_unit="day",
        coverage_policy="error",
    )
    config = SoilReservoirConfig(ru=120.0, transit_time=transit_time_days, spinup="none")

    forcings = compute_soil_forcings(
        precipitation=precip_result,
        etp=etp_result,
        config=config,
        window=window,
        model_crs=_CRS,
    )

    recharge = np.asarray(forcings.recharge.fields[0].data["recharge"].values).reshape(-1)
    expected = _closed_form(transit_time_days, n_days)
    max_error = tol(
        "soil_transit_store_impulse__max_absolute_error_against_q_0_50_1_k_a_q_t_1_50_k_a_2_exp_"
        "t_1_k_mm"
    )
    volume_error = tol("soil_transit_store_impulse_volume")
    t95_tolerance_days = tol("routed_impulse_validation_case__t95_against_k_ln_0_05_days")

    assert np.max(np.abs(recharge - expected)) < max_error
    assert abs(recharge.sum() - 50.0) < volume_error

    expected_t95 = -transit_time_days * np.log(0.05)
    assert abs(_t95(recharge) - expected_t95) <= t95_tolerance_days
