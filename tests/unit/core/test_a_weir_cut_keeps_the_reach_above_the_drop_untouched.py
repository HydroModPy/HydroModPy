"""A declared weir cuts the tree: the reach above its 2 m drop is fitted alone.

Below the weir an undeclared 5 m bump pools with the foot of the weir to a
level above the crest. Without the cut the fit pools across the weir and
raises the crest and the reach above it to that level. With the cut the reach above keeps
its raw bed, the drop is not smoothed, and the climb left at the weir is
reported. A cut changes the fit only when such a climb remains: a regression
pools across an edge only when its downstream side ends higher.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.bed_regularization import regularize_bed_on_tree

LENGTH_M = 25.0

# 0 (head) -> 1 -> 2 (weir crest) -> 3 (foot) -> 4 (bump) -> 5 (root).
WEIR, FOOT = 2, 3


def test_a_weir_cut_keeps_the_reach_above_the_drop_untouched() -> None:
    values = np.array([12.5, 12.2, 12.0, 10.0, 15.0, 9.0])
    receiver = np.array([1, 2, 3, 4, 5, -1])
    cut = np.zeros(6, dtype=bool)
    cut[WEIR] = True

    uncut = regularize_bed_on_tree(values, receiver, np.full(6, LENGTH_M))
    fit = regularize_bed_on_tree(values, receiver, np.full(6, LENGTH_M), cut=cut)

    assert uncut.values[WEIR] > values[WEIR] + 0.1
    np.testing.assert_allclose(fit.values[: WEIR + 1], values[: WEIR + 1])
    half_drop = 1.0e-4 * LENGTH_M / 2
    np.testing.assert_allclose(fit.values[[FOOT, 4]], [12.5 + half_drop, 12.5 - half_drop])
    assert fit.climbs_at_cuts == 1
    assert fit.violations_after == 0
    assert uncut.climbs_at_cuts == 0
