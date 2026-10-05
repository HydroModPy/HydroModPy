"""A road embankment marked as a gap is interpolated, not a bump that raises the bed.

Read as a measurement, a 3 m embankment across a straight bed is a rise the
fit pools with the reach above it, lifting that reach. Marked as a gap, its
value is replaced by the line between its measured neighbours and the
measured bed is left as it was.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import regularize_bed_on_tree

N_NODES = 11
LENGTH_M = 25.0
BED_SLOPE = 0.01
EMBANKMENT = [5, 6]


def _straight_bed_with_embankment() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    distance_to_root = LENGTH_M * np.arange(N_NODES - 1, -1, -1)
    bed = BED_SLOPE * distance_to_root
    values = bed.copy()
    values[EMBANKMENT] += 3.0
    receiver = np.r_[np.arange(1, N_NODES), -1]
    return bed, values, receiver


def test_a_road_embankment_gap_is_interpolated_not_pooled() -> None:
    bed, values, receiver = _straight_bed_with_embankment()
    gap = np.zeros(N_NODES, dtype=bool)
    gap[EMBANKMENT] = True

    as_bump = regularize_bed_on_tree(values, receiver, np.full(N_NODES, LENGTH_M))
    as_gap = regularize_bed_on_tree(values, receiver, np.full(N_NODES, LENGTH_M), gap=gap)

    assert as_bump.values[4] > bed[4] + 1.0
    np.testing.assert_allclose(as_gap.values, bed, atol=1e-9)
    assert (as_gap.raised, as_gap.lowered) == (0, 0)
    assert as_gap.violations_before == 0
    assert as_gap.blocks == ()
