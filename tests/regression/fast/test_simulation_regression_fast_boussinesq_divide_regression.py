"""Fast regression test for simulation_regression with Boussinesq divide case."""

from __future__ import annotations

import pytest

from tests.regression.simulation_regression_helpers import (
    run_simulation_regression_boussinesq,
)


@pytest.mark.regression
@pytest.mark.fast
def test_simulation_regression_fast_boussinesq_divide_regression(update_goldens) -> None:
    run_simulation_regression_boussinesq(
        test_file=__file__,
        golden_filename="simulation_regression_fast_boussinesq_divide_npy_signatures.json",
        run_name="simulation_regression_fast_boussinesq_divide_outputs",
        update_goldens=update_goldens,
        timeout=1800,
        config_stem="run_fast_boussinesq_divide",
        simulation_run_id="simulation_regression_fast_boussinesq_divide",
        process_id="flow_main",
        simulation_name="Launcher fast Boussinesq divide regression",
        simulation_description="Fast steady Boussinesq divide regression on a precomputed strip bundle",
        initial_head_m=7.0,
        west_head_m=None,
        east_head_m=5.0,
        recharge_mm_day=1.0,
    )
