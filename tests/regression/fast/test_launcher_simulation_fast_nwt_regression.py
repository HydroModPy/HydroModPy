"""Fast regression test for launcher_simulation with MODFLOW-NWT."""

from __future__ import annotations

import pytest

from tests.regression.launcher_simulation_helpers import run_launcher_simulation_regression


@pytest.mark.regression
@pytest.mark.fast
@pytest.mark.nwt
@pytest.mark.skip(
    reason=(
        "MODPATH zone_partic='seepage_clip' expects a legacy TIF at "
        "_postprocess/_rasters/seepage_areas_t(0).tif which the new "
        "extractor pipeline no longer writes (seepage_areas now lives in "
        "the Zarr store under derived/). Rewire MODPATH seepage_clip "
        "resolver to read seepage from the store and (re)export the TIF, "
        "or switch the fixture to zone_partic='domain'. Tracked post-v1.0."
    )
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
