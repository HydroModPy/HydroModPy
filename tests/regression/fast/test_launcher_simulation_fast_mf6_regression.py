"""Fast regression test for launcher_simulation with MODFLOW 6 / GWT."""

from __future__ import annotations

import pytest

from tests.regression.launcher_simulation_helpers import run_launcher_simulation_regression


@pytest.mark.regression
@pytest.mark.fast
@pytest.mark.mf6
@pytest.mark.xfail(
    reason="MF6 golden MODFLOW signatures drift after G04/G05 DuckDB schema "
    "refactor; regeneration tracked as v0.6 regression-golden-refresh.",
    strict=True,
    raises=AssertionError,
)
def test_launcher_simulation_fast_mf6_regression(update_goldens) -> None:
    run_launcher_simulation_regression(
        test_file=__file__,
        config_name="run_fast_mf6.toml",
        golden_filename="launcher_simulation_fast_mf6_npy_signatures.json",
        run_name="launcher_simulation_fast_mf6_outputs",
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
        transport_solver="mf6",
        update_goldens=update_goldens,
        timeout=3600,
    )
