"""Weighted Lloyd: centroids for h^-4, fixed constraint seeds, hard disks never entered."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Polygon, box

from hydromodpy.spatial.mesh.engines.voronoi.constraints.plan import (
    ConstraintPlan,
    ConstraintSeeds,
    FaceLineState,
)
from hydromodpy.spatial.mesh.engines.voronoi.frame import SizeSampler, local_frame
from hydromodpy.spatial.mesh.engines.voronoi.free_seeds import DiskSet
from hydromodpy.spatial.mesh.engines.voronoi.lloyd import (
    BERGE_BALL_SCALE,
    GABRIEL_SCALE,
    LLOYD_CAP,
    PROTECTION_SHARE,
    constraint_disks,
    relax,
    weighted_centroids,
)
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain
from hydromodpy.spatial.mesh.request import SizeField
from hydromodpy.spatial.mesh.resample import positions_at_local_size
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


def test_a_graded_size_pulls_the_centroid_towards_the_small_cells() -> None:
    xmin, _, xmax, _ = DOMAIN.bounds
    ncol = int((xmax - xmin) / 5.0)
    h = _sampler(10.0 + 0.5 * 5.0 * np.arange(ncol))
    cell = shapely.box(-20.0, -20.0, 20.0, 20.0)
    centroid = weighted_centroids(np.array([cell]), np.zeros((1, 2)), h)
    assert centroid[0, 0] < -1.0
    assert abs(centroid[0, 1]) < 1e-9


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
    assert np.allclose(hard.radius, [BERGE_BALL_SCALE * 5.0, GABRIEL_SCALE * 8.0])
    assert np.allclose(protect.center, _plan().seeds.xy)
    assert np.allclose(protect.radius, PROTECTION_SHARE * np.array([20.0, 30.0, 30.0]))


def test_a_plan_without_chain_or_conformal_vertex_has_no_hard_disk() -> None:
    plan = _plan()
    plan = ConstraintPlan(
        plan.seeds,
        dataclasses.replace(plan.faces, conformal=np.zeros(2, dtype=bool)),
        (),
        ("rivers",),
        (),
        {},
        {},
    )
    hard, protect = constraint_disks(plan)
    assert hard.center.shape == (0, 2) and hard.radius.shape == (0,)
    assert len(protect.radius) == plan.seeds.n


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


def test_relax_holds_the_fixed_seeds_and_reports_its_moves() -> None:
    h = _sampler(10.0)
    seeds, n_fixed, domain = _seeds(h)
    report = relax(seeds, n_fixed, h, domain, *_no_disks(), cap=6)
    assert np.array_equal(report.seeds[:n_fixed], seeds[:n_fixed])
    assert report.iterations == 6
    assert report.cap == 6
    assert not report.converged
    assert 0.0 < report.move_p50 <= report.move_p99 <= report.move_max
    assert report.move_p50 <= report.move_rms <= report.move_max
    free = report.seeds[n_fixed:]
    assert shapely.contains_xy(domain, free[:, 0], free[:, 1]).all()
    extras = report.extras()
    assert set(extras) == {
        "lloyd_iterations",
        "lloyd_cap",
        "lloyd_converged",
        "lloyd_move_rms",
        "lloyd_move_p50",
        "lloyd_move_p99",
        "lloyd_move_max",
        "lloyd_rejected",
    }
    assert extras["lloyd_converged"] == 0.0


def test_relax_stops_once_the_root_mean_square_move_is_under_the_tolerance() -> None:
    h = _sampler(10.0)
    seeds, n_fixed, domain = _seeds(h)
    probe = relax(seeds, n_fixed, h, domain, *_no_disks(), cap=8)
    tolerance = 0.5 * (probe.move_rms + probe.move_max)
    report = relax(seeds, n_fixed, h, domain, *_no_disks(), tolerance=tolerance)
    assert report.converged
    assert report.iterations < LLOYD_CAP
    assert report.move_rms < tolerance < report.move_max


def test_no_free_seed_ends_in_a_hard_disk() -> None:
    h = _sampler(10.0)
    seeds, n_fixed, domain = _seeds(h)
    hard_center = np.array([[0.0, 0.0], [-60.0, 30.0]])
    hard_radius = np.array([25.0, 15.0])
    free = seeds[n_fixed:]
    outside = ~DiskSet(hard_center, hard_radius).contains(free)
    seeds = np.vstack([seeds[:n_fixed], free[outside]])
    hard = DiskSet(hard_center, hard_radius)
    report = relax(seeds, n_fixed, h, domain, hard, _no_disks()[1], cap=8)
    moved = report.seeds[n_fixed:]
    distance = np.hypot(*(moved[:, None, :] - hard_center[None]).transpose(2, 0, 1))
    assert np.all(distance >= hard_radius * (1.0 - 1e-12))


def test_a_move_that_stays_in_a_hard_disk_is_refused_and_counted() -> None:
    h = _sampler(10.0)
    domain = h.frame.to_local(DOMAIN)
    fixed = ring_seeds(domain, h)
    centre = np.array([shapely.get_coordinates(domain.centroid)[0]])
    free = centre + [3.0, 2.0]
    # The disk covers the whole domain: every projection lands outside it.
    hard = DiskSet(centre, [200.0])
    report = relax(np.vstack([fixed, free]), len(fixed), h, domain, hard, _no_disks()[1], cap=2)
    # A refused move is no move: the iteration is a fixed point and the relaxation stops.
    assert report.rejected == 1
    assert report.iterations == 1
    assert np.array_equal(report.seeds[-1], free[0])


def test_no_free_seed_and_a_zero_cap_leave_the_seeds_alone() -> None:
    h = _sampler(10.0)
    seeds, n_fixed, domain = _seeds(h)
    fixed_only = relax(seeds[:n_fixed], n_fixed, h, domain, *_no_disks())
    assert fixed_only.converged and fixed_only.iterations == 0
    frozen = relax(seeds, n_fixed, h, domain, *_no_disks(), cap=0)
    assert np.array_equal(frozen.seeds, seeds) and frozen.iterations == 0
