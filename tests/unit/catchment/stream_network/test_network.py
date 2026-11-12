"""The simulated stream network of a mesh and its seepage threshold (m3/s, per cell area in m2).

A cell seeps when its flux passes the threshold of the cell. The threshold of a
cell is a share of the recharge that its own area receives.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.catchment.stream_network.network import (
    build_simulated_network,
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
