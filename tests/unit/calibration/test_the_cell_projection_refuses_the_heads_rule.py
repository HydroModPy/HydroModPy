"""The cell projection of a mapped network refuses the heads rule by name.

Under ``"heads"`` the map is drawn on the criterion graph from the free ends of
the lines, so no cell projection exists to hand back; a caller asking for one
would score a map the trial never drew.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.observations.observed_network import observed_network_mask


def test_the_cell_projection_refuses_the_heads_rule() -> None:
    with pytest.raises(ValueError, match="criterion graph"):
        observed_network_mask(
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            np.zeros((1, 4), dtype=int),
            rasterization="heads",
        )
