"""A free end is judged by the talweg within its radius, not by its nearest cell.

A mapped line runs beside the model talweg, so the cell nearest to a
confluence is often a hillside cell. Here the reach end sits three cells off
the axis: its nearest cell drains less than the head's axis cell, and a
nearest-cell rule would drop the head. Within the 50 m radius the end reads
the axis further down, which drains more, so the head is kept.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from tests.unit.core._heads_valley import (
    AXIS,
    CELL,
    N_COLS,
    N_ROWS,
    candidates,
    cell,
    centre,
    valley_geometry,
)


def test_a_head_reads_the_drained_area_within_its_radius() -> None:
    head, junction = centre(5, AXIS), centre(20, AXIS + 3)

    geometry = valley_geometry(candidates([(head, junction)]), snap_radius_m=50.0)

    drained = accumulate_on_downhill_graph(
        geometry.metric.graph, np.full(N_ROWS * N_COLS, CELL * CELL)
    )
    assert drained[cell(20, AXIS + 3)] < drained[cell(5, AXIS)]
    assert geometry.heads is not None
    np.testing.assert_allclose(geometry.heads.head_xy, [head])
    assert geometry.observed[cell(5, AXIS)]
