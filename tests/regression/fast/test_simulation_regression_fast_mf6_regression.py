"""Fast regression test for simulation_regression with MODFLOW 6 / GWT."""

from __future__ import annotations

import pytest

from tests.regression.simulation_regression_helpers import run_simulation_regression


@pytest.mark.regression
@pytest.mark.fast
@pytest.mark.mf6
def test_simulation_regression_fast_mf6_regression(update_goldens) -> None:
    run_simulation_regression(
        test_file=__file__,
        config_name="run_fast_mf6.toml",
        golden_filename="simulation_regression_fast_mf6_npy_signatures.json",
        run_name="simulation_regression_fast_mf6_outputs",
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
        transport_solver="mf6",
        update_goldens=update_goldens,
        timeout=3600,
    )
