"""The linear reservoir against the RK4 reference, played once.

The case runs the backend's solver of the metadata's recipe (one storm of
5 days at 5 mm/day, then 20 dry days, tau 30 days) through the exact kernel
the backend solves with, alongside the RK4 runs of the reference of the
case. The tolerance is the one `tests/TOLERANCES.md` row 188 carries.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests._helpers.tolerances import tol
from tests.validation.helpers import assert_metric_below, record_metric
from validation_cases.analytical.linear_reservoir.case import (
    compute_linear_reservoir_reference,
    rain_of,
)

NOT_APPLICABLE = {
    "*": (
        "The case runs the kernel of the linear reservoir, a one-cell global model that is "
        "not a column of the matrix. No MODFLOW or Boussinesq backend solves this recession."
    ),
}

TAU_DAYS = 30.0
SECONDS_PER_DAY = 86400.0
RAIN_RATE_M_PER_S = 5.0e-8
RAIN_DAYS = 5
DRY_DAYS = 20
AREA_M2 = 1.0e6
TOLERANCE = tol("the_linear_reservoir_on_the_one_cell_mesh")


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
def test_the_linear_reservoir_of_one_cell_matches_the_rk4_reference() -> None:
    """The backend's discharge and state answer the RK4 within 1e-4 of the peak."""
    rates = rain_of(RAIN_DAYS + DRY_DAYS, RAIN_DAYS, RAIN_RATE_M_PER_S)
    durations = np.full(rates.size, SECONDS_PER_DAY)
    tau_seconds = TAU_DAYS * SECONDS_PER_DAY
    stored_reference, released_reference = compute_linear_reservoir_reference(
        rates, durations, tau_seconds
    )
    from hydromodpy.solver.linear_reservoir.kernel import run as run_backend

    solved = run_backend(
        rates,
        durations,
        0.0,  # the state of the storm falls from the steady state of the run
        tau_seconds,
        AREA_M2,
    )
    released_depth = solved.released_m3 / AREA_M2  # m3 to m: the depth the piece released
    record_metric("tau_days", TAU_DAYS, TAU_DAYS * 2.0, op="<", unit="day")
    peak_release = float(np.max(np.abs(released_depth)))
    gap = float(np.max(np.abs(released_depth - released_reference)))
    assert_metric_below("released depth relative gap", gap / peak_release, TOLERANCE)
    state_gap = float(np.max(np.abs(solved.stored_m - stored_reference)))
    peak_state = float(np.max(np.abs(stored_reference)))
    assert_metric_below("stored depth relative gap", state_gap / peak_state, TOLERANCE)
