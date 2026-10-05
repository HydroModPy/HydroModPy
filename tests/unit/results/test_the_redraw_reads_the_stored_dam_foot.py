"""The heads redraw of a run takes the dam foot the run stored as a head.

The results layer never sees the model: it reads ``run.descent.dam_foot``, the
cells the build stored with D. A run whose D carries none draws as it did before
the feet were stored. On the 5 x 3 valley a hillside cell of the north row stands
for the foot of a dam.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from hydromodpy.results.derive.network_heads_view import network_heads_view_from_run
from hydromodpy.results.derive.stream_network import network_comparison_from_run
from hydromodpy.results.run.descent import RunDescent
from tests.unit.display._network_comparison_run import comparison_run

HILLSIDE = 10  # column 0 of the north row: it drains along the row to the axis


def _run_with_dam_foot(cells):
    run = comparison_run()
    stored = replace(run.descent.view(), dam_foot=np.asarray(cells, dtype=np.int64))
    run.descent = RunDescent(lambda: stored)
    return run


def _redraw(run):
    return network_comparison_from_run(
        run, tau_specific_ratio=0.0, observed_rasterization="heads", heads_min_drained_area_km2=0.0
    )


def test_a_stored_dam_foot_is_traced_as_a_forced_head() -> None:
    comparison = _redraw(_run_with_dam_foot([HILLSIDE]))

    trace = comparison.geometry.heads
    assert trace is not None
    assert trace.forced_cell.tolist() == [HILLSIDE]
    assert comparison.geometry.observed[HILLSIDE]
    assert comparison.geometry.diagnostics["n_forced_heads"] == 1.0


def test_a_run_whose_descent_stores_no_foot_draws_as_before() -> None:
    plain = _redraw(comparison_run())
    empty = _redraw(_run_with_dam_foot([]))

    assert not plain.geometry.observed[HILLSIDE]
    np.testing.assert_array_equal(empty.geometry.observed, plain.geometry.observed)
    assert empty.geometry.diagnostics["n_forced_heads"] == 0.0


def test_the_heads_view_carries_the_forced_heads_apart() -> None:
    view = network_heads_view_from_run(_run_with_dam_foot([HILLSIDE]))

    assert view.full.forced_xy.shape == (1, 2)
    assert view.full.indices["n_forced_heads"] == 1.0
    assert view.full.head_xy.shape[0] == 1
