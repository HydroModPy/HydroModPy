"""A source the maximal and the minimal maps both draw is traced as one head.

The maximal map is traced from the heads of both maps. A permanent reach often
starts where the full network does, and a duplicate would count twice in the
published head indices.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.stream_heads import concat_candidates
from tests.unit.core._heads_valley import AXIS, N_ROWS, candidates, centre


def test_a_source_both_maps_draw_is_one_head() -> None:
    shared, other = centre(5, AXIS), centre(8, AXIS + 4)
    outlet_end = centre(N_ROWS - 1, AXIS)
    maximal = candidates([(shared, outlet_end), (other, outlet_end)])
    minimal = candidates([(shared, outlet_end)])

    union = concat_candidates(maximal, minimal)

    assert union.n_candidates == 2
    np.testing.assert_allclose(union.head_xy, [shared, other])
