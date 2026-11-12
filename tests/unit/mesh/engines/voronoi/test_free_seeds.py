"""Free seeds: their count, their draw from an explicit generator, their Morton order."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.mesh.engines.voronoi import free_seeds
from hydromodpy.mesh.engines.voronoi.free_seeds import DiskSet, morton_order, sample_free_seeds
from hydromodpy.mesh.engines.voronoi.local_coords import SizeSampler, local_frame
from hydromodpy.mesh.request import SizeField
from tests._helpers.mesh_cases import L93_ORIGIN, grid_over

X0, Y0 = L93_ORIGIN
DOMAIN = box(X0, Y0, X0 + 400.0, Y0 + 300.0)


def _sampler(size: float | np.ndarray = 10.0) -> SizeSampler:
    """The sampler of a field on a 5 m grid: a constant, or one size per column."""
    grid = grid_over(DOMAIN, 5.0)
    values = np.broadcast_to(np.asarray(size, dtype=float), (grid.nrow, grid.ncol)).copy()
    return SizeSampler(SizeField(values, grid), local_frame(DOMAIN))


def test_saturated_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(free_seeds, "MAX_DRAW_BLOCKS", 2)
    h = _sampler(10.0)
    domain = h.frame.to_local(DOMAIN)
    with pytest.raises(MeshGenerationError, match="saturate"):
        sample_free_seeds(
            np.random.default_rng(0), h, domain, np.zeros((1, 2)), np.array([1.0e4]), 10
        )


def test_no_free_seed() -> None:
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


def test_morton_order_of_no_point() -> None:
    assert morton_order(np.empty((0, 2))).size == 0


def test_morton_span_refused() -> None:
    with pytest.raises(MeshGenerationError, match="span more than"):
        morton_order(np.array([[0.0, 0.0], [5000.0, 0.0]]), step=1.0e-6)


def test_disk_set_radius_per_centre() -> None:
    with pytest.raises(ValueError, match="one radius per centre"):
        DiskSet(np.zeros((2, 2)), np.array([1.0]))


def test_disk_set_projection() -> None:
    disks = DiskSet(np.array([[0.0, 0.0], [10.0, 0.0]]), np.array([2.0, 1.0]))
    points = np.array([[1.0, 0.0], [0.0, 0.0], [5.0, 5.0]])
    previous = np.array([[3.0, 0.0], [0.0, -4.0], [5.0, 5.0]])
    assert disks.contains(points).tolist() == [True, True, False]
    moved = disks.project_out(points, previous)
    assert np.allclose(moved, [[2.0, 0.0], [0.0, -2.0], [5.0, 5.0]])
