"""A cycle in the receivers is refused, naming a node of the cycle."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.bed_regularization import regularize_bed_on_tree


def test_a_cycle_in_the_receivers_is_refused() -> None:
    # 4 -> 1 -> 2 -> 3 -> 1 is a cycle; 0 is a separate root.
    receiver = np.array([-1, 2, 3, 1, 1])

    with pytest.raises(ValueError, match=r"cycle through node [123]\b"):
        regularize_bed_on_tree(np.arange(5.0), receiver, np.ones(5))
