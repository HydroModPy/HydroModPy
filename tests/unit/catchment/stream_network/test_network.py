"""Tests of `stream_network.network`: the simulated network, its closure and its threshold."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.catchment.stream_network.network import (
    build_simulated_network,
    specific_seepage_threshold,
)
from tests._helpers.v_valley import N_CELLS, build_bench, simulated_network


@pytest.fixture(scope="module")
def bench():
    return build_bench()


def _network_from_threshold(bench, threshold: float):
    """Build a simulated network from the bench pattern, through the real path."""
    pattern = simulated_network(bench, float(threshold))
    flux = np.where(pattern, 1.0, 0.0)
    return build_simulated_network(
        flux,
        threshold_m3_s=np.full(N_CELLS, 0.5),
        metric=bench.metric,
    )


class TestSimulatedNetwork:
    def test_a_mismatched_cell_count_is_refused(self, bench) -> None:
        with pytest.raises(ValueError, match="the mesh holds"):
            build_simulated_network(np.zeros(7), threshold_m3_s=np.zeros(7), metric=bench.metric)


class TestSpecificThreshold:
    def test_it_scales_with_the_cell_area(self) -> None:
        threshold = specific_seepage_threshold(np.array([100.0, 900.0]), 1e-8, ratio=1e-4)
        # A cell nine times larger carries a threshold nine times larger, so the
        # mask follows the physics rather than the mesh refinement.
        assert threshold[1] / threshold[0] == pytest.approx(9.0)

    def test_a_negative_ratio_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            specific_seepage_threshold(np.array([1.0]), 1e-8, ratio=-1.0)
