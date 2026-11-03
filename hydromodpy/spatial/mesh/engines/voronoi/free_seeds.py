"""The free seeds of the Voronoi generator: count, draw and canonical order.

The total number of seeds is the integral of ``1 / h^2`` over the domain, so it
does not depend on the random seed. The free seeds fill what the constraint
seeds leave: a free seed is drawn with density ``1 / h^2`` by rejection, from an
explicit ``numpy.random.Generator``, and kept only outside the protection disk of
every constraint seed. Their order is the Morton key of a fixed 1 m grid of the
local frame, so the cell ids follow space, not the draw.
"""

from __future__ import annotations

import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.engines.voronoi.local_coords import SizeSampler

__all__ = [
    "DRAW_BLOCK",
    "DiskSet",
    "MAX_DRAW_BLOCKS",
    "MORTON_STEP_M",
    "free_seed_count",
    "morton_order",
    "sample_free_seeds",
]

DRAW_BLOCK = 1 << 20
"""Candidates ``(x, y, u)`` drawn per block. Fixed: the seeds depend on it."""

MAX_DRAW_BLOCKS = 1000
"""Blocks drawn before the domain is declared saturated by its constraint seeds."""

MORTON_STEP_M = 1.0
"""Cell of the fixed grid that orders the free seeds [m]."""

_NEAREST_DISKS = 8
"""Nearest disk centers a point is tested against."""

_MIN_SLICE = 4096
"""Fewest candidates tested at once."""

_MORTON_BITS = 32


def free_seed_count(h: SizeSampler, domain: BaseGeometry, n_constraint: int) -> int:
    """Number of free seeds: ``round(sum of A_pixel / h_pixel^2) - n_constraint``, at least 0.

    The sum runs over the pixels of the size field whose center lies in the
    local *domain*.
    """
    centres, pixel_area = h.pixel_centres()
    inside = shapely.contains_xy(domain, centres[:, 0], centres[:, 1])
    sizes = h.field.values.ravel()[inside]
    target = round(float(np.sum(pixel_area / sizes**2)))
    return max(0, target - int(n_constraint))


def sample_free_seeds(
    rng: np.random.Generator,
    h: SizeSampler,
    domain: BaseGeometry,
    constraint_xy: np.ndarray,
    constraint_radius: np.ndarray,
    n: int,
) -> np.ndarray:
    """Draw *n* free seeds ``(n, 2)`` in the local *domain*, in the order of the draw.

    Candidates ``(x, y, u)`` are drawn uniformly in the domain bounding box, in
    blocks of :data:`DRAW_BLOCK`. A candidate is kept when ``u < (h_min / h)^2``,
    when it lies in the domain, and when it is farther than ``constraint_radius``
    from each of its nearest constraint seeds. Raises ``MeshGenerationError``
    when :data:`MAX_DRAW_BLOCKS` blocks do not give *n* seeds.
    """
    if n <= 0:
        return np.empty((0, 2))
    shapely.prepare(domain)
    protection = DiskSet(constraint_xy, constraint_radius)
    xmin, ymin, xmax, ymax = domain.bounds
    kept: list[np.ndarray] = []
    found = 0
    for _ in range(MAX_DRAW_BLOCKS):
        draw = rng.random((DRAW_BLOCK, 3))
        xy = np.column_stack([xmin + (xmax - xmin) * draw[:, 0], ymin + (ymax - ymin) * draw[:, 1]])
        xy = xy[draw[:, 2] < (h.h_min / h(xy)) ** 2]
        # Candidates are tested in slices sized on what is missing; the kept
        # seeds are the first ones of the draw that pass, whatever the slicing.
        start = 0
        while found < n and start < len(xy):
            stop = start + max(2 * (n - found), _MIN_SLICE)
            batch = xy[start:stop]
            batch = batch[shapely.contains_xy(domain, batch[:, 0], batch[:, 1])]
            batch = batch[~protection.contains(batch)][: n - found]
            kept.append(batch)
            found += len(batch)
            start = stop
        if found == n:
            return np.vstack(kept)
    raise MeshGenerationError(
        f"the constraint seeds saturate the domain: {found} of {n} free seeds found in "
        f"{MAX_DRAW_BLOCKS} blocks of {DRAW_BLOCK} candidates"
    )


class DiskSet:
    """Disks ``(center, radius)`` in the local frame, tested against their nearest centers."""

    def __init__(self, center: np.ndarray, radius: np.ndarray) -> None:
        """Index the centers ``(k, 2)``; one radius [m] per center."""
        self.center = np.asarray(center, dtype=np.float64).reshape(-1, 2)
        radius = np.asarray(radius, dtype=np.float64).ravel()
        if radius.size != len(self.center):
            raise ValueError("a disk set needs one radius per centre")
        self.radius = radius
        self._k = min(_NEAREST_DISKS, len(self.center))
        self._tree = cKDTree(self.center) if self._k else None
        self._reach = float(radius.max(initial=0.0))
        self._padded = np.r_[radius, 0.0]

    def _inside(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Mask and ids ``(n, k)`` of the nearest disks that strictly hold each point."""
        if self._tree is None or not len(points):
            empty = np.zeros((len(points), max(self._k, 1)), dtype=bool)
            return empty, np.zeros(empty.shape, dtype=np.int64)
        distance, index = self._tree.query(points, k=self._k, distance_upper_bound=self._reach)
        distance = distance.reshape(len(points), self._k)
        index = index.reshape(len(points), self._k)
        return distance < self._padded[index], index

    def contains(self, points: np.ndarray) -> np.ndarray:
        """Mask of the points ``(n, 2)`` strictly inside a disk."""
        return self._inside(points)[0].any(axis=1)

    def project_out(self, points: np.ndarray, previous: np.ndarray) -> np.ndarray:
        """Move each point inside a disk radially onto the circle of the nearest such disk.

        A point at the very center leaves along the direction of its *previous*
        position; one with no direction keeps its previous position.
        """
        inside, index = self._inside(points)
        rows = np.flatnonzero(inside.any(axis=1))
        if not rows.size:
            return points
        disk = index[rows, np.argmax(inside[rows], axis=1)]
        centre = self.center[disk]
        offset = points[rows] - centre
        length = np.hypot(*offset.T)
        at_centre = length == 0.0
        offset[at_centre] = previous[rows][at_centre] - centre[at_centre]
        length[at_centre] = np.hypot(*offset[at_centre].T)
        moved = points.copy()
        stuck = length == 0.0
        length[stuck] = 1.0
        moved[rows] = centre + offset * (self.radius[disk] / length)[:, None]
        moved[rows[stuck]] = previous[rows[stuck]]
        return moved


def morton_order(xy: np.ndarray, step: float = MORTON_STEP_M) -> np.ndarray:
    """Permutation that sorts local points ``(n, 2)`` by Morton key, then by x and y.

    The key interleaves the column and row of each point on the grid of *step*
    anchored at the origin of the local frame.
    """
    points = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    if not len(points):
        return np.empty(0, dtype=np.int64)
    cells = np.floor(points / step).astype(np.int64)
    cells -= cells.min(axis=0)
    if cells.max() >= 1 << _MORTON_BITS:
        raise MeshGenerationError(
            f"the seeds span more than 2^{_MORTON_BITS} cells of {step} m along an axis"
        )
    key = _spread(cells[:, 0].astype(np.uint64)) | (
        _spread(cells[:, 1].astype(np.uint64)) << np.uint64(1)
    )
    return np.lexsort((points[:, 1], points[:, 0], key))


def _spread(value: np.ndarray) -> np.ndarray:
    """Insert a zero bit after each of the 32 low bits of *value*."""
    v = value & np.uint64(0xFFFFFFFF)
    v = (v | (v << np.uint64(16))) & np.uint64(0x0000FFFF0000FFFF)
    v = (v | (v << np.uint64(8))) & np.uint64(0x00FF00FF00FF00FF)
    v = (v | (v << np.uint64(4))) & np.uint64(0x0F0F0F0F0F0F0F0F)
    v = (v | (v << np.uint64(2))) & np.uint64(0x3333333333333333)
    return (v | (v << np.uint64(1))) & np.uint64(0x5555555555555555)
