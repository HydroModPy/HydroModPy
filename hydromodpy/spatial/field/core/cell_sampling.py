"""Deterministic interior sampling of mesh cells for support-field fractions.

Single source of truth shared by every support field (`spatial_support`,
`field_spatial_square`, `geology_field`). Quadrilateral and triangle cells
sample a fixed barycentric lattice. Polygon (Voronoi/PEBI) cells fan-triangulate
the convex n-gon from its first vertex and sample each sub-triangle at a density
proportional to its area, so the concatenated points stay area-uniform over the
whole cell. Voronoi cells are convex by construction, so the fan covers the cell
exactly.
"""

from __future__ import annotations

from functools import cache

import numpy as np


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
