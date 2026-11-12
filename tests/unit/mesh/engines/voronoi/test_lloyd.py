"""Weighted Lloyd: centroids for h^-4, fixed constraint seeds, hard disks never entered."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Polygon, box

from hydromodpy.mesh.engines.voronoi.constraints.plan import (
    ConstraintPlan,
    ConstraintSeeds,
    FaceLineState,
)
from hydromodpy.mesh.engines.voronoi.free_seeds import DiskSet
from hydromodpy.mesh.engines.voronoi.lloyd import (
    BERGE_CIRCLE_SCALE,
    GABRIEL_SCALE,
    PROTECTION_SHARE,
    constraint_disks,
    relax,
    weighted_centroids,
)
from hydromodpy.mesh.engines.voronoi.local_coords import SizeSampler, local_frame
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain
from hydromodpy.mesh.request import SizeField
from hydromodpy.mesh.resample import positions_at_local_size
from tests._helpers.mesh_cases import L93_ORIGIN, grid_over

X0, Y0 = L93_ORIGIN
DOMAIN = box(X0, Y0, X0 + 300.0, Y0 + 200.0)


def _sampler(size: float | np.ndarray) -> SizeSampler:
    """The sampler of a field on a 5 m grid: a constant, or one size per column."""
    grid = grid_over(DOMAIN, 5.0)
    values = np.broadcast_to(np.asarray(size, dtype=float), (grid.nrow, grid.ncol)).copy()
    return SizeSampler(SizeField(values, grid), local_frame(DOMAIN))


def ring_seeds(domain: Polygon, h: SizeSampler) -> np.ndarray:
    """Fixed seeds on the ring of the local domain: its corners, then points at the local size."""
    points = []
    corners = np.asarray(domain.exterior.coords)[:-1]
    for a, b in zip(corners, np.roll(corners, -1, axis=0), strict=True):
        inner, _, _ = positions_at_local_size(LineString([a, b]), h.h_min / 4.0, h, ring=False)
        points += [a, *inner]
    return np.asarray(points, dtype=float)


def _no_disks() -> tuple[DiskSet, DiskSet]:
    empty = np.empty((0, 2))
    return DiskSet(empty, np.empty(0)), DiskSet(empty, np.empty(0))


def test_a_constant_size_gives_the_area_centroid_whatever_the_ring_orientation() -> None:
    h = _sampler(10.0)
    cell = shapely.Polygon([(0, 0), (40, 0), (40, 10), (0, 30)])
    seed = np.array([[5.0, 5.0]])
    for polygon in (cell, shapely.reverse(cell)):
        centroid = weighted_centroids(np.array([polygon]), seed, h)
        assert np.allclose(centroid[0], shapely.get_coordinates(polygon.centroid)[0])


def _plan() -> ConstraintPlan:
    """Three chain seeds, the last two on one cell, and a conformal and a yielded vertex."""
    xy = np.array([[0.0, 10.0], [8.0, 10.0], [8.0, 10.0]])
    seeds = ConstraintSeeds(
        xy=xy,
        role=np.zeros(3, dtype=np.int64),
        line_id=np.zeros(3, dtype=np.int64),
        pair_id=np.full(3, -1),
        vertex_id=np.full(3, -1),
        radius=np.array([20.0, 30.0, 30.0]),
        family=np.zeros(3, dtype=np.int16),
    )
    empty = np.empty((0, 2), dtype=np.int64)
    faces = FaceLineState(
        vertices=np.array([[0.0, 0.0], [50.0, 0.0]]),
        radius=np.array([5.0, 7.0]),
        conformal=np.array([True, False]),
        segment_nodes=empty,
        segment_seeds=empty,
        segment_conformal=np.empty(0, dtype=bool),
        segment_family=np.empty(0, dtype=np.int64),
        segment_line=np.empty(0, dtype=np.int64),
        zone_left=np.empty(0, dtype=np.int32),
        zone_right=np.empty(0, dtype=np.int32),
    )
    chain = CellChain("rivers", 0, np.array([0, 1, 1]))
    return ConstraintPlan(seeds, faces, (chain,), ("rivers",), (), {}, {})


def test_the_disks_scale_the_berge_gabriel_and_protection_radii() -> None:
    hard, protect = constraint_disks(_plan())
    assert np.allclose(hard.center, [[0.0, 0.0], [4.0, 10.0]])
    assert np.allclose(hard.radius, [BERGE_CIRCLE_SCALE * 5.0, GABRIEL_SCALE * 8.0])
    assert np.allclose(protect.center, _plan().seeds.xy)
    assert np.allclose(protect.radius, PROTECTION_SHARE * np.array([20.0, 30.0, 30.0]))


def test_the_disks_need_one_radius_per_centre() -> None:
    with pytest.raises(ValueError, match="one radius per centre"):
        DiskSet(np.zeros((2, 2)), [1.0])


def _seeds(h: SizeSampler) -> tuple[np.ndarray, int, object]:
    domain = h.frame.to_local(DOMAIN)
    fixed = ring_seeds(domain, h)
    rng = np.random.default_rng(5)
    xmin, ymin, xmax, ymax = domain.bounds
    free = np.column_stack(
        [rng.uniform(xmin + 15, xmax - 15, 400), rng.uniform(ymin + 15, ymax - 15, 400)]
    )
    return np.vstack([fixed, free]), len(fixed), domain


def test_no_free_seed_and_a_zero_cap_leave_the_seeds_alone() -> None:
    h = _sampler(10.0)
    seeds, n_fixed, domain = _seeds(h)
    fixed_only = relax(seeds[:n_fixed], n_fixed, h, domain, *_no_disks())
    assert fixed_only.converged and fixed_only.iterations == 0
    frozen = relax(seeds, n_fixed, h, domain, *_no_disks(), cap=0)
    assert np.array_equal(frozen.seeds, seeds) and frozen.iterations == 0
