"""Fast regression test for launcher_simulation with MODFLOW-NWT."""

from __future__ import annotations

import pytest

from tests.regression.launcher_simulation_helpers import run_launcher_simulation_regression


@pytest.mark.regression
@pytest.mark.fast
@pytest.mark.nwt
@pytest.mark.xfail(
    reason="NWT particle-tracking seepage_clip raster pipeline disabled "
    "after the F04 display env-var purge and G06 display refactor; "
    "rewire tracked as v0.6 nwt-particle-seepage-refresh.",
    strict=True,
    raises=AssertionError,
)
def test_launcher_simulation_fast_nwt_regression(update_goldens) -> None:
    run_launcher_simulation_regression(
        test_file=__file__,
        config_name="run_fast_nwt.toml",
        golden_filename="launcher_simulation_fast_nwt_npy_signatures.json",
        run_name="launcher_simulation_fast_nwt_outputs",
        require_modflow=True,
        require_modflow6=False,
        require_modpath=True,
        require_mt3dms=True,
        transport_solver="mt3dms",
        update_goldens=update_goldens,
        timeout=3600,
    )
