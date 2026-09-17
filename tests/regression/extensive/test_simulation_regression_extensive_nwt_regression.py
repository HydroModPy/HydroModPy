"""Extensive regression test for simulation_regression with MODFLOW-NWT.

Golden refreshed 2026-09-17, two numbers, and here is why they moved.
``concentration_seepage`` and ``mass_seepage`` declared ``nodata_count`` 1497;
they now declare 0. Nothing the model computes changed: on the produced run the
two arrays hold 6 468 cells, 2 219 finite, and ``count``, ``mean``, ``p50``,
``p95`` and ``sum`` match the 2026-07-12 golden to better than 1e-6 relative.
What changed is how an absent cell is marked. ``f62a14c62`` (2026-07-25),
published after that golden, masks MODFLOW's dry/no-flow sentinels to NaN at
the field write, so the 1 497 cells that carried ``|x| >= 1e20`` now carry NaN:
4 249 NaN = 2 752 already-NaN + 1 497. ``nodata_count`` counts sentinels and
not NaN, and ``count`` already excludes both, which is why one number moved and
no other did.

The metric keeps its place: it is now the assertion that no sentinel reaches
the store at all. What makes the new 0 fail fast rather than after a
six-minute nightly run is
``tests/unit/results/test_a_sentinel_never_reaches_the_store.py``.
"""

from __future__ import annotations

import pytest

from tests.regression.simulation_regression_helpers import run_simulation_regression


@pytest.mark.regression
@pytest.mark.extensive
@pytest.mark.slow
@pytest.mark.coverage
@pytest.mark.nwt
@pytest.mark.timeout(7200)
def test_simulation_regression_extensive_nwt_regression(update_goldens) -> None:
    run_simulation_regression(
        test_file=__file__,
        config_name="run_extensive_nwt.toml",
        golden_filename="simulation_regression_extensive_nwt_npy_signatures.json",
        run_name="simulation_regression_extensive_nwt_outputs",
        require_modflow=True,
        require_modflow6=False,
        require_modpath=True,
        require_mt3dms=True,
        transport_solver="mt3dms",
        update_goldens=update_goldens,
        timeout=7200,
    )
