from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.jacobian.common import (
    drainage_diagonal_derivative,
)
from tests._helpers.mesh_doubles import _MiniMesh


def test_drainage_derivative_is_active_at_top_contact() -> None:
    mesh = _MiniMesh(
        z_top_m=np.asarray([2.0, 2.0, 2.0], dtype=float),
        hydraulic_conductivity_m_s=np.asarray([1.0, 1.0, 1.0], dtype=float),
        cell_area_m2=np.asarray([10.0, 10.0, 10.0], dtype=float),
    )

    derivative = drainage_diagonal_derivative(
        mesh,
        head_m=np.asarray([1.99, 2.0, 2.01], dtype=float),
        drainage_conductance_m2_s=0.2,
    )

    np.testing.assert_allclose(derivative, np.asarray([0.0, 0.2, 0.2]))
