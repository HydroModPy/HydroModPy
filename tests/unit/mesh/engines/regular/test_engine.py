"""The regular engine: cells on the DEM grid, centers the solvers read, and what its QA says."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.mesh.request import InputTriangulation
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec, mesh_request

DEM = grid_spec(12, 20, 50.0, crs_wkt=LAMBERT93_WKT)
"""A 1 km by 600 m DEM at 50 m."""


def test_refusals() -> None:
    triangulation = InputTriangulation(
        np.array([[0.0, 0.0], [1000.0, 0.0], [0.0, 600.0]]), np.array([[0, 1, 2]]), {}
    )
    request = mesh_request(DEM, input_triangulation=triangulation)

    with pytest.raises(MeshRequestError, match="cannot use an input triangulation"):
        RegularMeshEngine().build(request)
