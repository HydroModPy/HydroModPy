from __future__ import annotations

import pandas as pd

from hydromodpy.core.time import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
    validate_recharge_coverage,
)
from hydromodpy.core.time.steady_initialization import (
    single_period_mean_forcing_time_grid,
)
from hydromodpy.spatial.mesh.cartesian_grid._sgrid_field_grid_utils import (
    stress_period_bounds,
)


def test_single_period_mean_forcing_time_grid_spans_full_source_window() -> None:
    source_window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01"),
        end=pd.Timestamp("2003-02-28"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )
    source_grid = type(
        "SourceGrid",
        (),
        {
            "window": source_window,
            "period_lengths_seconds": (31 * 86400.0, 28 * 86400.0),
        },
    )()

    steady_grid = single_period_mean_forcing_time_grid(source_grid)

    assert steady_grid.period_lengths_seconds.tolist() == [59 * 86400.0]
    assert steady_grid.window.start == pd.Timestamp("2003-01-01")
    assert steady_grid.window.end == pd.Timestamp("2003-02-28")
    assert steady_grid.window.coverage_policy == "error"
    assert build_simulation_time_boundaries(steady_grid.window) == [
        pd.Timestamp("2003-01-01"),
        pd.Timestamp("2003-03-01"),
    ]
    assert stress_period_bounds(1, steady_grid.window) == [
        (pd.Timestamp("2003-01-01"), pd.Timestamp("2003-03-01"))
    ]

    recharge = pd.Series(
        [1.0, 2.0],
        index=pd.DatetimeIndex([pd.Timestamp("2003-01-01"), pd.Timestamp("2003-02-28")]),
    )
    validate_recharge_coverage(recharge, steady_grid.window)
