"""Deterministic interior sampling of mesh cells for support-field fractions.

Single source of truth shared by every support field (`support_fields`,
`two_zone_field`, `geology_field`), with the zone shares of a cell
(`sampled_zone_fractions`) and the batch path of quadrilaterals. Quadrilateral and triangle cells
sample a fixed barycentric lattice. Polygon (Voronoi/PEBI) cells fan-triangulate
the convex n-gon from its first vertex and sample each sub-triangle at a density
proportional to its area, so the concatenated points stay area-uniform over the
whole cell. Voronoi cells are convex by construction, so the fan covers the cell
exactly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import cache
from typing import TYPE_CHECKING, Literal

import numpy as np

from hydromodpy.spatial.field.mesh_cells import mesh_cells

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh


@cache
def quadrilateral_sample_weights(n_sub_per_axis: int) -> np.ndarray:
    """Barycentric weights of a regular sub-grid over the unit quadrilateral."""
    n = max(2, int(n_sub_per_axis))
    u = (np.arange(n, dtype=float) + 0.5) / float(n)
    v = (np.arange(n, dtype=float) + 0.5) / float(n)
    uu, vv = np.meshgrid(u, v, indexing="xy")
    return np.column_stack(
        (
            ((1.0 - uu) * (1.0 - vv)).ravel(),
            (uu * (1.0 - vv)).ravel(),
            (uu * vv).ravel(),
            ((1.0 - uu) * vv).ravel(),
        )
    )


@cache
def triangle_sample_weights(n_sub_per_axis: int) -> np.ndarray:
    """Barycentric weights of a regular sub-grid over the unit triangle."""
    n = max(2, int(n_sub_per_axis))
    u = (np.arange(n, dtype=float) + 0.5) / float(n)
    v = (np.arange(n, dtype=float) + 0.5) / float(n)
    uu, vv = np.meshgrid(u, v, indexing="xy")
    mask = (uu + vv) < 1.0
    uu = uu[mask]
    vv = vv[mask]
    return np.column_stack((1.0 - uu - vv, uu, vv))


def _quad_points(verts: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    weights = quadrilateral_sample_weights(n)
    x = weights @ verts[:, 0]
    y = weights @ verts[:, 1]
    return x.ravel(), y.ravel()


def quadrilateral_points_in_cells(
    vertices: np.ndarray, n_sub_per_axis: int
) -> tuple[np.ndarray, np.ndarray]:
    """Sample points of many quadrilaterals at once, one row per cell.

    ``vertices`` has the shape ``(n_cells, 4, 2)``. The points are those of the
    one-cell path, but summed term by term instead of by a matrix product, so
    the last bit can differ. Each path keeps its own sum so that its fractions
    do not move.
    """
    verts = np.asarray(vertices, dtype=float)
    weights = quadrilateral_sample_weights(n_sub_per_axis)
    w0 = weights[:, 0][None, :]
    w1 = weights[:, 1][None, :]
    w2 = weights[:, 2][None, :]
    w3 = weights[:, 3][None, :]
    x = (
        w0 * verts[:, 0, 0:1]
        + w1 * verts[:, 1, 0:1]
        + w2 * verts[:, 2, 0:1]
        + w3 * verts[:, 3, 0:1]
    )
    y = (
        w0 * verts[:, 0, 1:2]
        + w1 * verts[:, 1, 1:2]
        + w2 * verts[:, 2, 1:2]
        + w3 * verts[:, 3, 1:2]
    )
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def _triangle_points(verts: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    weights = triangle_sample_weights(n)
    x = weights @ verts[:, 0]
    y = weights @ verts[:, 1]
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def _polygon_points(verts: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    k = int(verts.shape[0])
    if k < 3:
        return verts[:, 0].copy(), verts[:, 1].copy()
    anchor = verts[0]
    tri_verts: list[np.ndarray] = []
    areas = np.empty(k - 2, dtype=float)
    for i in range(1, k - 1):
        b = verts[i]
        c = verts[i + 1]
        areas[i - 1] = 0.5 * abs(
            (b[0] - anchor[0]) * (c[1] - anchor[1]) - (c[0] - anchor[0]) * (b[1] - anchor[1])
        )
        tri_verts.append(np.array([anchor, b, c], dtype=float))
    max_area = float(areas.max()) if areas.size else 0.0
    if max_area <= 0.0:
        centroid = verts.mean(axis=0)
        return np.asarray([centroid[0]]), np.asarray([centroid[1]])
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    for area, tri in zip(areas, tri_verts, strict=True):
        if area <= 0.0:
            continue
        # Constant point density: n_i = n * sqrt(area_i / max_area) so each
        # sub-triangle contributes points proportional to its area.
        n_i = max(2, int(round(n * float(np.sqrt(area / max_area)))))
        x, y = _triangle_points(tri, n_i)
        xs.append(x)
        ys.append(y)
    if not xs:
        centroid = verts.mean(axis=0)
        return np.asarray([centroid[0]]), np.asarray([centroid[1]])
    return np.concatenate(xs), np.concatenate(ys)


def sample_points_in_cell(cell, *, n_sub_per_axis: int) -> tuple[np.ndarray, np.ndarray]:
    """Generate deterministic interior sample points for one mesh cell."""
    n = max(2, int(n_sub_per_axis))
    verts = np.asarray(cell.vertices, dtype=float)
    kind = cell.kind
    if kind == "quadrilateral":
        return _quad_points(verts, n)
    if kind == "triangle":
        return _triangle_points(verts, n)
    if kind == "polygon":
        return _polygon_points(verts, n)
    raise ValueError(f"Unsupported cell kind '{cell.kind}'")


def sampled_zone_fractions(
    cell_mesh: PlanarCellMesh,
    zone_id: Callable[[np.ndarray, np.ndarray], np.ndarray],
    zone_keys: Sequence[str],
    n_sub_per_axis: int,
    *,
    total: Literal["samples", "labelled", "zone_keys"] = "samples",
) -> dict[str, np.ndarray]:
    """Share of each zone among the sample points of each cell.

    ``zone_id`` gives the zone key of each sample point. The share of a zone is
    the count of its points over a total, which ``total`` chooses:
    ``"samples"`` counts every point of the cell, ``"labeled"`` the points
    that fall in a zone (a non-empty key), and ``"zone_keys"`` adds the counts
    of ``zone_keys``, a key named twice counted twice. A total of zero counts
    as one, so the cell gets a share of zero.
    """
    fractions = {key: np.zeros(cell_mesh.n_cells, dtype=float) for key in zone_keys}
    for cell in mesh_cells(cell_mesh):
        x, y = sample_points_in_cell(cell, n_sub_per_axis=n_sub_per_axis)
        zone_ids = zone_id(x, y)
        counts = [int(np.count_nonzero(zone_ids == key)) for key in zone_keys]
        if total == "samples":
            n_total = zone_ids.size
        elif total == "labelled":
            n_total = int(np.count_nonzero(zone_ids != ""))
        else:
            n_total = sum(counts)
        n_total = max(n_total, 1)
        for key, count in zip(zone_keys, counts, strict=True):
            fractions[key][cell.index] = float(count) / float(n_total)
    return fractions
