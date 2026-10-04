"""The downstream end of a free reach is never kept as a head.

Which end of a reach is upstream is read on the criterion graph, by the
drained area, never from the direction the line was digitised in. The outlet
end of the map drains more than its reach end, so it starts nothing.
"""

from __future__ import annotations

import numpy as np

from tests.unit.core._heads_valley import AXIS, N_ROWS, candidates, centre, valley_geometry


def test_a_free_downstream_end_is_not_a_head() -> None:
    head, outlet_end = centre(5, AXIS), centre(N_ROWS - 1, AXIS)
    # Listed outlet first, as a line digitised against the flow would be.
    heads = candidates([(outlet_end, head), (head, outlet_end)])

    geometry = valley_geometry(heads)

    assert geometry.heads is not None
    assert geometry.heads.n_candidates == 2
    np.testing.assert_allclose(geometry.heads.head_xy, [head])
