"""The local frame is a fixed 1 km translation, exact both ways; the sampler reads the field in it."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.engines.voronoi.local_coords import (
    LocalFrame,
    SizeSampler,
    local_frame,
)
from tests._helpers.mesh_cases import L93_ORIGIN, grid_over, mesh_request

X0, Y0 = L93_ORIGIN
DOMAIN = box(X0 + 120.0, Y0 + 40.0, X0 + 1730.0, Y0 + 980.0)


def test_frame_refusals() -> None:
    with pytest.raises(MeshRequestError):
        LocalFrame((float("nan"), 0.0))
    with pytest.raises(ValueError):
        LocalFrame((0.0, 0.0)).to_local(np.zeros(3))


def test_empty_domain_has_no_frame() -> None:
    with pytest.raises(MeshRequestError, match="non-empty domain"):
        local_frame(Polygon())


def test_sampler_without_a_size_field() -> None:
    request = mesh_request(grid_over(DOMAIN), domain=DOMAIN, nominal_size_m=35.0)
    sampler = SizeSampler.of_request(request, local_frame(DOMAIN))
    assert np.allclose(sampler(np.zeros((4, 2))), 35.0, rtol=1e-15)
    assert sampler.h_min == sampler.h_max == 35.0
