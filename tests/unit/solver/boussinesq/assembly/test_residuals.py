"""Cell residuals of the Boussinesq balance, in m3/s."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.assembly.residuals import assemble_transient_residual
from tests._helpers.boussinesq_mesh_doubles import line_mesh


@pytest.mark.parametrize("dt_seconds", [0.0, -86_400.0])
def test_refuses_a_step_without_duration(dt_seconds: float) -> None:
    mesh = line_mesh([0.0, 0.0], storage_coefficient=0.1)
    head = np.asarray([5.0, 5.0])

    with pytest.raises(ValueError, match="dt_seconds must be strictly positive"):
        assemble_transient_residual(mesh, head_m=head, head_prev_m=head, dt_seconds=dt_seconds)
