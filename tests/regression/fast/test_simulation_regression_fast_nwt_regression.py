"""Fast regression test for simulation_regression with MODFLOW-NWT."""

from __future__ import annotations

import pytest

from tests.regression.simulation_regression_helpers import run_simulation_regression


@pytest.mark.regression
@pytest.mark.fast
@pytest.mark.nwt
def test_simulation_regression_fast_nwt_regression(update_goldens) -> None:
    run_simulation_regression(
        test_file=__file__,
        config_name="run_fast_nwt.toml",
        golden_filename="simulation_regression_fast_nwt_npy_signatures.json",
        run_name="simulation_regression_fast_nwt_outputs",
        require_modflow=True,
        require_modflow6=False,
        require_modpath=True,
        require_mt3dms=True,
        transport_solver="mt3dms",
        update_goldens=update_goldens,
        timeout=3600,
    )
