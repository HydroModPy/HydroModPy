"""The local frame is a fixed 1 km translation, exact both ways; the sampler reads the field in it."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.engines.voronoi.frame import LocalFrame, SizeSampler, local_frame
from hydromodpy.spatial.mesh.request import MeshRequest
from hydromodpy.spatial.mesh.sizing.size_field import sample_size_field
from tests.unit.mesh.engines.voronoi.core_pipeline import WKT, X0, Y0, size_field

DOMAIN = box(X0 + 120.0, Y0 + 40.0, X0 + 1730.0, Y0 + 980.0)


def test_the_origin_is_the_kilometre_nearest_the_bounding_box_centre() -> None:
    frame = local_frame(DOMAIN)
    assert frame.origin == (X0 + 1000.0, Y0 + 1000.0)
    reversed_ring = Polygon(list(DOMAIN.exterior.coords)[::-1])
    assert local_frame(reversed_ring).origin == frame.origin


def test_points_go_to_the_local_frame_and_back_bit_for_bit() -> None:
    rng = np.random.default_rng(3)
    world = np.column_stack([X0 + 2000.0 * rng.random(1000), Y0 + 2000.0 * rng.random(1000)])
    frame = local_frame(DOMAIN)
    local = frame.to_local(world)
    assert np.abs(local).max() < 1500.0
    assert np.array_equal(frame.to_world(local), world)


def test_a_geometry_is_translated_whole() -> None:
    frame = local_frame(DOMAIN)
    local = frame.to_local(DOMAIN)
    assert local.bounds == (-880.0, -960.0, 730.0, -20.0)
    assert shapely.equals_exact(frame.to_world(local), DOMAIN, tolerance=0.0)


def test_a_frame_refuses_a_non_finite_origin_and_bad_points() -> None:
    with pytest.raises(MeshRequestError):
        LocalFrame((float("nan"), 0.0))
    with pytest.raises(ValueError):
        LocalFrame((0.0, 0.0)).to_local(np.zeros(3))


def test_the_sampler_reads_the_size_field_at_local_points() -> None:
    xmin, ymin, xmax, ymax = DOMAIN.bounds
    ncol = int(np.ceil((xmax - xmin) / 10.0))
    field = size_field(DOMAIN, 10.0, 20.0 + np.arange(ncol, dtype=float))
    frame = local_frame(DOMAIN)
    sampler = SizeSampler(field, frame)
    world = np.array([[X0 + 300.0, Y0 + 500.0], [X0 + 1700.0, Y0 + 100.0]])
    assert np.array_equal(sampler(frame.to_local(world)), sample_size_field(field, world))
    assert sampler.h_min == 20.0
    assert sampler.h_max == 20.0 + ncol - 1


def test_a_request_without_a_size_field_samples_its_nominal_size() -> None:
    field = size_field(DOMAIN, 50.0, 1.0)
    request = MeshRequest(domain=DOMAIN, crs_wkt=WKT, grid=field.grid, nominal_size_m=35.0)
    sampler = SizeSampler.of_request(request, local_frame(DOMAIN))
    assert np.allclose(sampler(np.zeros((4, 2))), 35.0, rtol=1e-15)
    assert sampler.h_min == sampler.h_max == 35.0


def test_pixel_centres_are_local_row_zero_north() -> None:
    field = size_field(DOMAIN, 100.0, 30.0)
    frame = local_frame(DOMAIN)
    centres, area = SizeSampler(field, frame).pixel_centres()
    grid = field.grid
    assert area == 100.0 * 100.0
    assert len(centres) == grid.nrow * grid.ncol
    first = frame.to_world(centres[:1])[0]
    assert tuple(first) == (grid.xmin + 50.0, grid.ymax - 50.0)
