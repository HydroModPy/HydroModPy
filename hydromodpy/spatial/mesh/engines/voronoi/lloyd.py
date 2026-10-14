"""Weighted Lloyd relaxation of the free seeds, the constraint seeds held fixed.

Each iteration moves every free seed to the centroid of its clipped cell for
the density ``rho = h^-4``. The centroid integrates ``rho`` with one point per
fan triangle ``(seed, a, b)`` of the cell ring, at the triangle centroid: a
coarser quadrature of the same density, cheaper than three points and with the
same size fidelity.

The new position is then projected out of the hard disks (the Berge balls of
the conformal face vertices, the Gabriel disks of the river chain segments),
then out of the protection disks of the constraint seeds. A move that still
ends in a hard disk, or outside the domain, is refused: the seed keeps its
position. The relaxation stops when the largest move falls under the tolerance,
as a share of the local size, or at the iteration cap; the report says which.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry

from hydromodpy.spatial.mesh.engines.voronoi.frame import SizeSampler
from hydromodpy.spatial.mesh.engines.voronoi.free_seeds import DiskSet
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import voronoi_cells, voronoi_envelope

__all__ = [
    "BERGE_BALL_SCALE",
    "GABRIEL_SCALE",
    "LLOYD_CAP",
    "LLOYD_TOLERANCE",
    "PROTECTION_SHARE",
    "LloydInvariants",
    "LloydReport",
    "lloyd_invariants",
    "relax",
    "weighted_centroids",
]

LLOYD_CAP = 25
"""Most Lloyd iterations; the QA reports whether the tolerance was reached before."""

LLOYD_TOLERANCE = 0.01
"""Default stop: the largest free seed move under this share of its local size."""

BERGE_BALL_SCALE = 1.02
"""Hard radius of a Berge ball, as a multiple of its radius ``R_v``."""

GABRIEL_SCALE = 0.51
"""Hard radius of the Gabriel disk of a chain segment, as a multiple of its length."""

PROTECTION_SHARE = 0.6
"""Protection radius in Lloyd, as a share of the size ``h(c)`` at the constraint seed."""


@dataclass(frozen=True, eq=False)
class LloydInvariants:
    """Disks a free seed must leave: hard ones (never entered) and protection ones."""

    hard_center: np.ndarray
    hard_radius: np.ndarray
    protect_center: np.ndarray
    protect_radius: np.ndarray

    def __post_init__(self) -> None:
        """Check one radius per centre."""
        for name in ("hard", "protect"):
            centre = np.asarray(getattr(self, f"{name}_center"), dtype=np.float64).reshape(-1, 2)
            radius = np.asarray(getattr(self, f"{name}_radius"), dtype=np.float64).ravel()
            if radius.size != len(centre):
                raise ValueError(f"{name} disks need one radius per centre")
            object.__setattr__(self, f"{name}_center", centre)
            object.__setattr__(self, f"{name}_radius", radius)


@dataclass(frozen=True, eq=False)
class LloydReport:
    """Relaxed seeds and how the relaxation ended (moves as shares of the local size)."""

    seeds: np.ndarray
    iterations: int
    cap: int
    converged: bool
    move_p50: float
    move_p99: float
    move_max: float
    rejected: int

    def extras(self) -> dict[str, float]:
        """The ``lloyd_*`` numbers of the mesh QA."""
        return {
            "lloyd_iterations": float(self.iterations),
            "lloyd_cap": float(self.cap),
            "lloyd_converged": float(self.converged),
            "lloyd_move_p50": self.move_p50,
            "lloyd_move_p99": self.move_p99,
            "lloyd_move_max": self.move_max,
            "lloyd_rejected": float(self.rejected),
        }


def lloyd_invariants(
    *,
    berge_center: np.ndarray,
    berge_radius: np.ndarray,
    chain_start: np.ndarray,
    chain_end: np.ndarray,
    constraint_xy: np.ndarray,
    constraint_size: np.ndarray,
) -> LloydInvariants:
    """The disks of the relaxation from the line state, all in the local frame.

    Hard disks: each Berge ball of a conformal vertex at ``1.02 R_v``, and the
    Gabriel disk of each chain segment ``[start, end]`` (centre at its middle,
    radius ``0.51 |end - start|``). Protection disks: ``0.6 h(c)`` around each
    constraint seed ``c``.
    """
    start = np.asarray(chain_start, dtype=np.float64).reshape(-1, 2)
    end = np.asarray(chain_end, dtype=np.float64).reshape(-1, 2)
    berge = np.asarray(berge_center, dtype=np.float64).reshape(-1, 2)
    return LloydInvariants(
        hard_center=np.vstack([berge, 0.5 * (start + end)]),
        hard_radius=np.concatenate(
            [
                BERGE_BALL_SCALE * np.asarray(berge_radius, dtype=np.float64).ravel(),
                GABRIEL_SCALE * np.hypot(*(end - start).T),
            ]
        ),
        protect_center=np.asarray(constraint_xy, dtype=np.float64).reshape(-1, 2),
        protect_radius=PROTECTION_SHARE * np.asarray(constraint_size, dtype=np.float64).ravel(),
    )


def weighted_centroids(cells: np.ndarray, seeds: np.ndarray, h: SizeSampler) -> np.ndarray:
    """Centroid ``(n, 2)`` of each cell for the density ``h^-4``, one point per fan triangle.

    The fan triangles join the seed to each edge of the cell exterior ring with
    signed areas, so the result does not depend on the ring orientation.
    """
    rings = shapely.get_exterior_ring(cells)
    coords, owner = shapely.get_coordinates(rings, return_index=True)
    same = owner[1:] == owner[:-1]
    a, b, cell = coords[:-1][same], coords[1:][same], owner[:-1][same]
    s = seeds[cell]
    area = 0.5 * (
        (a[:, 0] - s[:, 0]) * (b[:, 1] - s[:, 1]) - (b[:, 0] - s[:, 0]) * (a[:, 1] - s[:, 1])
    )
    point = (a + b + s) / 3.0
    weight = area * (h.h_min / h(point)) ** 4
    total = np.bincount(cell, weights=weight, minlength=len(seeds))
    x = np.bincount(cell, weights=weight * point[:, 0], minlength=len(seeds))
    y = np.bincount(cell, weights=weight * point[:, 1], minlength=len(seeds))
    centroid = np.array(seeds, dtype=np.float64, copy=True)
    ok = total != 0.0
    centroid[ok] = np.column_stack([x[ok], y[ok]]) / total[ok, None]
    return centroid


def relax(
    seeds: np.ndarray,
    n_fixed: int,
    h: SizeSampler,
    domain: BaseGeometry,
    invariants: LloydInvariants,
    *,
    tolerance: float = LLOYD_TOLERANCE,
    cap: int = LLOYD_CAP,
) -> LloydReport:
    """Relax the seeds after the first *n_fixed*, all in the local frame.

    Stops when the largest move of an iteration is under *tolerance* times the
    local size, or after *cap* iterations. ``rejected`` counts the refused moves
    over all iterations.
    """
    points = np.array(seeds, dtype=np.float64, copy=True)
    fixed = int(n_fixed)
    n_free = len(points) - fixed
    if n_free <= 0 or cap <= 0:
        return LloydReport(points, 0, cap, n_free <= 0, 0.0, 0.0, 0.0, 0)
    shapely.prepare(domain)
    envelope = voronoi_envelope(domain, h.h_max)
    hard = DiskSet(invariants.hard_center, invariants.hard_radius)
    protect = DiskSet(invariants.protect_center, invariants.protect_radius)
    rejected = 0
    iterations = 0
    move = np.zeros(n_free)
    while iterations < cap:
        iterations += 1
        cells = voronoi_cells(points, domain, envelope)
        previous = points[fixed:]
        target = weighted_centroids(cells[fixed:], previous, h)
        target = hard.project_out(target, previous)
        target = protect.project_out(target, previous)
        refused = hard.contains(target) | ~shapely.contains_xy(domain, target[:, 0], target[:, 1])
        target[refused] = previous[refused]
        rejected += int(refused.sum())
        move = np.hypot(*(target - previous).T) / h(target)
        points[fixed:] = target
        if move.max() < tolerance:
            break
    return LloydReport(
        seeds=points,
        iterations=iterations,
        cap=cap,
        converged=bool(move.max() < tolerance),
        move_p50=float(np.median(move)),
        move_p99=float(np.percentile(move, 99)),
        move_max=float(move.max()),
        rejected=rejected,
    )
