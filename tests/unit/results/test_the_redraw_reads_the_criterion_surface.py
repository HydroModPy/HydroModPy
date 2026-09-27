"""A redrawn comparison uses the recharge and the outlet the trial used.

The seepage threshold is a fraction of the mean recharge. The criterion takes
the mean over the recharge periods of the built model; a redraw that read the
last timestep alone drew, on a transient run, another network than the one the
trial scored. The outlet is placed from the snapped pour point the geographic
step persisted, as the trial places it.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.results.derive.stream_network import network_comparison_from_run
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NX,
    NY,
    cell,
    comparison_run,
)

AREA_M2 = CELL_M * CELL_M
RECHARGE_BY_STEP_M3_S = (1.0e-4, 1.0e-4, 7.0e-4)
"""Three timesteps; the last one alone is 2.3 times the time mean."""


def _transient_run(**kwargs):
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, NY - 1)], **kwargs)
    release = run.field("release_flux")
    stacks = {
        "recharge": [np.full(NX * NY, value) for value in RECHARGE_BY_STEP_M3_S],
        "release_flux": [release] * len(RECHARGE_BY_STEP_M3_S),
    }

    def field(variable, timestep=-1, **_):
        return stacks[variable][timestep]

    run.n_timesteps = len(RECHARGE_BY_STEP_M3_S)
    run.field = field
    return run


def test_the_threshold_reads_the_time_mean_recharge() -> None:
    comparison = network_comparison_from_run(_transient_run(), tau_specific_ratio=1.0e-2)

    mean_rate = float(np.mean(RECHARGE_BY_STEP_M3_S)) / AREA_M2
    last_rate = RECHARGE_BY_STEP_M3_S[-1] / AREA_M2
    assert comparison.geometry.mean_recharge_m_s == pytest.approx(mean_rate)
    assert comparison.geometry.mean_recharge_m_s != pytest.approx(last_rate)
    assert comparison.geometry.threshold_m3_s[0] == pytest.approx(1.0e-2 * mean_rate * AREA_M2)


def test_a_steady_run_reads_its_one_state() -> None:
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, NY - 1)])
    run.n_timesteps = None

    comparison = network_comparison_from_run(run, tau_specific_ratio=1.0e-2)

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(1.0e-4 / AREA_M2)


def test_the_outlet_is_placed_from_the_snapped_pour_point() -> None:
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, NY - 1)])
    # One cell up the eastern flank: the search moves it onto the axis.
    snapped = {
        "x_outlet_snapped": str((AXIS_COLUMN + 1.5) * CELL_M),
        "y_outlet_snapped": str(1.5 * CELL_M),
    }
    run._catalog.read_geographic_metadata = lambda sim_id: dict(snapped)

    comparison = network_comparison_from_run(run)

    assert comparison.geometry.outlet == cell(AXIS_COLUMN, 0)
    assert comparison.geometry.catchment.all()
    assert comparison.geometry.catchment_mismatch == pytest.approx(0.0)
