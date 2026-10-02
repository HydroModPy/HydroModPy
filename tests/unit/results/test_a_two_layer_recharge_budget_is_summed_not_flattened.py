"""The recharge budget of a two-layer run sums onto the cell index.

``network_comparison_from_run`` sizes the seepage threshold from the mean
recharge rate the solver's budget wrote. MODFLOW stores a budget component as
``(time, layer, cell)`` even when only one layer carries it (recharge applies
to the top layer, the rest zero); reading it back and reshaping ``(time, -1)``
without summing the layer axis doubles the row width instead of collapsing it,
so the next array op against a ``(cell,)`` array of areas breaks. That is the
``(72930,) (36465,)`` broadcast a two-layer Flume run hit.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.results.derive.stream_network import network_comparison_from_run
from tests.unit.display._network_comparison_run import (
    CELL_RECHARGE_M3_S,
    NX,
    NY,
    comparison_run,
)


def test_recharge_split_over_two_layers_scores_the_same_threshold() -> None:
    single = comparison_run(seepage_cells=[7])
    layered = comparison_run(seepage_cells=[7])

    per_cell = np.full(NX * NY, CELL_RECHARGE_M3_S)
    two_layers = np.stack([per_cell, np.zeros_like(per_cell)])
    original_field = layered.field

    def field(variable, **kwargs):
        if variable == "recharge":
            return two_layers
        return original_field(variable, **kwargs)

    layered.field = field

    one_layer = network_comparison_from_run(single)
    two_layer = network_comparison_from_run(layered)

    assert two_layer.geometry.mean_recharge_m_s == pytest.approx(
        one_layer.geometry.mean_recharge_m_s, rel=1e-12
    )
