"""Extensive regression test for launcher_simulation with MODFLOW 6 / GWT."""

from __future__ import annotations

import pytest

from tests.regression.launcher_simulation_helpers import run_launcher_simulation_regression


@pytest.mark.regression
@pytest.mark.extensive
@pytest.mark.slow
@pytest.mark.coverage
@pytest.mark.mf6
def test_launcher_simulation_extensive_mf6_regression(update_goldens) -> None:
    run_launcher_simulation_regression(
        test_file=__file__,
        config_name="run_extensive_mf6.toml",
        golden_filename="launcher_simulation_extensive_mf6_npy_signatures.json",
        run_name="launcher_simulation_extensive_mf6_outputs",
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
        transport_solver="mf6",
        update_goldens=update_goldens,
        timeout=7200,
    )
