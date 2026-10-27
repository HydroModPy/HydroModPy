"""Free seeds: their count, their draw from an explicit generator, their Morton order."""

from __future__ import annotations

import random

import numpy as np
import pytest
import shapely
from shapely.geometry import box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.engines.voronoi import free_seeds
from hydromodpy.spatial.mesh.engines.voronoi.frame import SizeSampler, local_frame
from hydromodpy.spatial.mesh.engines.voronoi.free_seeds import (
    DiskSet,
    free_seed_count,
    morton_order,
    sample_free_seeds,
)
from hydromodpy.spatial.mesh.request import SizeField
from tests._helpers.mesh_cases import L93_ORIGIN, grid_over

X0, Y0 = L93_ORIGIN
DOMAIN = box(X0, Y0, X0 + 400.0, Y0 + 300.0)


def _sampler(size: float | np.ndarray = 10.0) -> SizeSampler:
    """The sampler of a field on a 5 m grid: a constant, or one size per column."""
    grid = grid_over(DOMAIN, 5.0)
    values = np.broadcast_to(np.asarray(size, dtype=float), (grid.nrow, grid.ncol)).copy()
    return SizeSampler(SizeField(values, grid), local_frame(DOMAIN))


def test_the_count_is_the_integral_of_one_over_h_squared_less_the_constraints() -> None:
    h = _sampler(10.0)
    domain = h.frame.to_local(DOMAIN)
    cells = round(DOMAIN.area / 10.0**2)
    assert free_seed_count(h, domain, 0) == cells
    assert free_seed_count(h, domain, 200) == cells - 200
    assert free_seed_count(h, domain, cells + 1) == 0


def test_free_seeds_lie_in_the_domain_out_of_every_protection_disk() -> None:
    h = _sampler(10.0)
    domain = h.frame.to_local(DOMAIN)
    centres = np.array([[-100.0, 0.0], [50.0, -20.0]])
    radius = np.array([30.0, 60.0])
    seeds = sample_free_seeds(np.random.default_rng(1), h, domain, centres, radius, 900)
    assert seeds.shape == (900, 2)
    assert shapely.contains_xy(domain, seeds[:, 0], seeds[:, 1]).all()
    distance = np.hypot(*(seeds[:, None, :] - centres[None]).transpose(2, 0, 1))
    assert np.all(distance >= radius)


def test_the_draw_follows_the_density_one_over_h_squared() -> None:
    xmin, _, xmax, _ = DOMAIN.bounds
    ncol = int((xmax - xmin) / 5.0)
    h = _sampler(np.where(np.arange(ncol) < ncol // 2, 10.0, 20.0))
    domain = h.frame.to_local(DOMAIN)
    seeds = sample_free_seeds(np.random.default_rng(2), h, domain, np.empty((0, 2)), [], 2000)
    west = np.count_nonzero(seeds[:, 0] < domain.centroid.x)
    assert 3.5 < west / (len(seeds) - west) < 4.5


def test_the_draw_ignores_the_global_random_state() -> None:
    h = _sampler(10.0)
    domain = h.frame.to_local(DOMAIN)
    draws = []
    for state in (0, 99):
        np.random.seed(state)
        random.seed(state)
        rng = np.random.Generator(np.random.PCG64(7))
        draws.append(sample_free_seeds(rng, h, domain, np.empty((0, 2)), [], 500))
    assert np.array_equal(draws[0], draws[1])


def test_a_domain_saturated_by_its_constraints_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(free_seeds, "MAX_DRAW_BLOCKS", 2)
    h = _sampler(10.0)
    domain = h.frame.to_local(DOMAIN)
    with pytest.raises(MeshGenerationError, match="saturate"):
        sample_free_seeds(
            np.random.default_rng(0), h, domain, np.zeros((1, 2)), np.array([1.0e4]), 10
        )


def test_no_free_seed_asked_gives_none() -> None:
    h = _sampler(10.0)
    seeds = sample_free_seeds(
        np.random.default_rng(0), h, h.frame.to_local(DOMAIN), np.empty((0, 2)), [], 0
    )
    assert seeds.shape == (0, 2)


def test_morton_order_follows_the_z_curve_then_x_and_y() -> None:
    points = np.array([[1.5, 1.5], [0.2, 1.1], [1.2, 0.3], [0.1, 0.1], [0.6, 0.4]])
    order = morton_order(points, step=1.0)
    assert order.tolist() == [3, 4, 2, 1, 0]
    shuffled = points[[2, 0, 4, 1, 3]]
    assert np.array_equal(shuffled[morton_order(shuffled)], points[order])


def test_morton_order_of_no_point_is_empty() -> None:
    assert morton_order(np.empty((0, 2))).size == 0


def test_points_farther_apart_than_the_morton_key_reaches_are_refused() -> None:
    with pytest.raises(MeshGenerationError, match="span more than"):
        morton_order(np.array([[0.0, 0.0], [5000.0, 0.0]]), step=1.0e-6)


def test_a_disk_set_needs_one_radius_per_centre() -> None:
    with pytest.raises(ValueError, match="one radius per centre"):
        DiskSet(np.zeros((2, 2)), np.array([1.0]))


def test_a_disk_set_projects_a_point_onto_the_circle_of_its_disk() -> None:
    disks = DiskSet(np.array([[0.0, 0.0], [10.0, 0.0]]), np.array([2.0, 1.0]))
    points = np.array([[1.0, 0.0], [0.0, 0.0], [5.0, 5.0]])
    previous = np.array([[3.0, 0.0], [0.0, -4.0], [5.0, 5.0]])
    assert disks.contains(points).tolist() == [True, True, False]
    moved = disks.project_out(points, previous)
    assert np.allclose(moved, [[2.0, 0.0], [0.0, -2.0], [5.0, 5.0]])
