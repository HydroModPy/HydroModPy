"""Planar-mesh orthogonality metric for the MODFLOW conductance vs XT3D choice.

The standard MODFLOW conductance (CVFD) two-point flux is exact only when the
line joining two connected cell centroids is perpendicular to their shared face
(a "K-orthogonal" connection) and the conductivity tensor is grid-aligned. On an
isotropic medium the only remaining error source is the geometric
non-orthogonality of the grid, which is exactly what the XT3D option corrects.

This module measures that non-orthogonality from a 2D planar mesh, so the solver
can decide whether XT3D is worth its cost. 0 deg = a perfectly orthogonal
connection (conductance is exact); large angles = conductance loses accuracy and
XT3D helps.

Reference: Provost, Langevin & Hughes (2017), "Documentation for the 'XT3D'
option in the NPF Package of MODFLOW 6", USGS TM 6-A56.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

__all__ = ["connection_nonorthogonality_deg", "nonorthogonality_summary"]


def connection_nonorthogonality_deg(planar_mesh) -> np.ndarray:
    """Per-interior-connection non-orthogonality angle [deg] of a 2D planar mesh.

    For each face shared by two cells, the angle between the centroid-to-centroid
    vector and the face normal. 0 deg means the connection is perpendicular to the
    face (conductance two-point flux is exact).
    """
    verts = np.asarray(planar_mesh.vertices, dtype=float)[:, :2]
    conn = planar_mesh.flat_connectivity  # rectangular array or ragged POLYGON tuple
    n_cells = len(conn)
    if n_cells == 0:
        return np.empty(0, dtype=float)
    # The connection node is the cell CENTER: the generator seed for a Voronoi/PEBI
    # mesh (perpendicular-bisector, ~0 deg), the vertex mean for a triangle mesh.
    x_centers, y_centers = planar_mesh.cell_centroids()
    centroids = np.column_stack(
        [np.asarray(x_centers, dtype=float), np.asarray(y_centers, dtype=float)]
    )

    edge_to_cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    for ci in range(n_cells):
        cell = np.asarray(conn[ci], dtype=int)
        arity = len(cell)
        for k in range(arity):
            a = int(cell[k])
            b = int(cell[(k + 1) % arity])
            edge_to_cells[(a, b) if a < b else (b, a)].append(ci)

    angles: list[float] = []
    for (a, b), cells in edge_to_cells.items():
        if len(cells) != 2:
            continue
        i, j = cells
        edge = verts[b] - verts[a]
        edge_len = float(np.hypot(edge[0], edge[1]))
        if edge_len == 0.0:
            continue
        ehat = edge / edge_len
        normal = np.array([-ehat[1], ehat[0]])
        link = centroids[j] - centroids[i]
        link_len = float(np.hypot(link[0], link[1]))
        if link_len == 0.0:
            continue
        cos = abs(float((link / link_len) @ normal))
        angles.append(float(np.degrees(np.arccos(min(1.0, cos)))))
    return np.asarray(angles, dtype=float)


def nonorthogonality_summary(planar_mesh) -> dict[str, float]:
    """Summary stats of the connection non-orthogonality [deg] (empty -> zeros)."""
    a = connection_nonorthogonality_deg(planar_mesh)
    if a.size == 0:
        return {"n": 0.0, "median": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "frac_gt_30": 0.0}
    return {
        "n": float(a.size),
        "median": float(np.median(a)),
        "p95": float(np.percentile(a, 95)),
        "p99": float(np.percentile(a, 99)),
        "max": float(a.max()),
        "frac_gt_30": float(np.mean(a > 30.0)),
    }
