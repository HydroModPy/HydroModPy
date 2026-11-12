"""The simulated stream network of a mesh and its seepage threshold (m3/s, per cell area in m2).

A cell seeps when its flux passes the threshold of the cell. The threshold of a
cell is a share of the recharge that its own area receives.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.catchment.stream_network.network import (
    build_simulated_network,
    downstream_closure,
    specific_seepage_threshold,
)
from tests._helpers.v_valley import build_bench


def test_threshold_scales_with_cell_area() -> None:
    threshold = specific_seepage_threshold(np.array([100.0, 900.0]), 1e-8, ratio=1e-4)
    # A cell nine times larger carries a threshold nine times larger, so the
    # mask follows the physics rather than the mesh refinement.
    assert threshold[1] / threshold[0] == pytest.approx(9.0)


def test_mismatched_cell_count_is_refused() -> None:
    bench = build_bench()
    with pytest.raises(ValueError, match="the mesh holds"):
        build_simulated_network(np.zeros(7), threshold_m3_s=np.zeros(7), metric=bench.metric)


def test_negative_ratio_is_refused() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        specific_seepage_threshold(np.array([1.0]), 1e-8, ratio=-1.0)


@pytest.mark.parametrize("recharge", [-1e-8, np.nan], ids=["negative", "nan"])
def test_recharge_must_be_finite_and_positive(recharge: float) -> None:
    with pytest.raises(ValueError, match="mean recharge must be finite and positive"):
        specific_seepage_threshold(np.array([1.0]), recharge, ratio=1e-4)


def test_network_input_shapes_are_refused() -> None:
    bench = build_bench()
    n_cells = bench.metric.graph.active.size
    flat = np.zeros(n_cells)

    with pytest.raises(ValueError, match="must be .n_cells,. or .n_times, n_cells."):
        build_simulated_network(np.zeros((2, 2, n_cells)), threshold_m3_s=flat, metric=bench.metric)
    with pytest.raises(ValueError, match=f"the threshold holds 3 cells, the mesh holds {n_cells}"):
        build_simulated_network(flat, threshold_m3_s=np.zeros(3), metric=bench.metric)
    with pytest.raises(ValueError, match=f"mask must have {n_cells} cells, got 3"):
        downstream_closure(bench.metric, np.zeros(3, dtype=bool))
