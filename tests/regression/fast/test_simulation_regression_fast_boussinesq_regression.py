"""Fast regression test for simulation_regression with Boussinesq flow only."""

from __future__ import annotations

import pytest

from tests.regression.simulation_regression_helpers import (
    run_simulation_regression_boussinesq,
)


@pytest.mark.regression
@pytest.mark.fast
def test_simulation_regression_fast_boussinesq_regression(update_goldens) -> None:
    run_simulation_regression_boussinesq(
        test_file=__file__,
        golden_filename="simulation_regression_fast_boussinesq_npy_signatures.json",
        run_name="simulation_regression_fast_boussinesq_outputs",
        update_goldens=update_goldens,
        timeout=1800,
    )
