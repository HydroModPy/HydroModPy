"""Share of water released at the land surface, from the depth of the water table in m."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.assembly.surface import partition_release_share
from tests._helpers.boussinesq_mesh_doubles import line_mesh


@pytest.mark.parametrize("radius_m", [0.0, -0.05])
def test_refuses_a_radius_that_is_not_a_depth(radius_m: float) -> None:
    with pytest.raises(ValueError, match="strictly positive depth"):
        partition_release_share(line_mesh([0.0]), np.asarray([5.0]), regularization_radius=radius_m)
