"""Adapter from a planar ``HydroMesh`` to the arguments of flopy DISV.

**to_flopy_disv_args** exports a planar ``HydroMesh`` as the keyword arguments
needed by ``flopy.mf6.ModflowGwfdisv`` (vertices, cell2d, top, botm).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh


def _signed_polygon_area_xy(vertices_xy: np.ndarray) -> float:
    """Return the signed planar polygon area in XY coordinates."""
    x = vertices_xy[:, 0]
    y = vertices_xy[:, 1]
    return float(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _orient_nodes_for_disv(nodes: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    """Return nodes ordered with the clockwise orientation expected by MF6 DISV."""
    if nodes.size < 3:
        return nodes
    polygon = vertices[np.asarray(nodes, dtype=int)]
    if _signed_polygon_area_xy(polygon) <= 0.0:
        return np.asarray(nodes, dtype=int)
    return np.asarray([nodes[0], *nodes[:0:-1]], dtype=int)


def to_flopy_disv_args(
    hydro_mesh: HydroMesh,
    *,
    top: float | np.ndarray,
    botm: np.ndarray,
) -> dict[str, Any]:
    """Build flopy DISV keyword arguments from a 2D ``HydroMesh``.

    Returns a dict with keys ``nvert``, ``vertices``, ``ncpl``, ``cell2d``,
    ``top``, ``botm`` suitable for ``flopy.mf6.ModflowGwfdisv(**result)``.

    Parameters
    ----------
    hydro_mesh : HydroMesh
        A planar (2D) mesh.
    top : float or array
        Top elevation(s).
    botm : ndarray
        Bottom elevation per layer, shape ``(nlay, ncpl)``.

    Notes
    -----
    The function assumes that the planar connectivity already represents the
    DISV cell polygons in the desired order.  It only reformats the data.
    """
    if hydro_mesh.ndim != 2:
        raise ValueError("to_flopy_disv_args requires a 2D mesh")

    verts = np.asarray(hydro_mesh.vertices, dtype=float)
    nvert = verts.shape[0]
    # DISV vertices: list of (iv, xv, yv)
    vertices = [[int(i), float(verts[i, 0]), float(verts[i, 1])] for i in range(nvert)]

    conn = hydro_mesh.flat_connectivity
    ncpl = len(conn)  # rectangular array or ragged tuple; both len == n_cells
    # An explicit per-cell center (e.g. the Voronoi generator, exact for CVFD
    # orthogonality) overrides the vertex-mean centroid when supplied.
    centers = hydro_mesh.cell_data.get("disv_cell_center")
    if centers is not None:
        centers = np.asarray(centers, dtype=float).reshape(ncpl, 2)
    # cell2d: list of (icell, xc, yc, ncvert, iv1, iv2, ...)
    cell2d: list[list] = []
    for ic in range(ncpl):
        nodes = _orient_nodes_for_disv(np.asarray(conn[ic], dtype=int), verts)
        if centers is not None:
            xc, yc = float(centers[ic, 0]), float(centers[ic, 1])
        else:
            cell_verts = verts[nodes]
            xc = float(cell_verts[:, 0].mean())
            yc = float(cell_verts[:, 1].mean())
        row: list = [int(ic), xc, yc, int(len(nodes))]
        row.extend(int(n) for n in nodes)
        cell2d.append(row)

    return {
        "nvert": nvert,
        "vertices": vertices,
        "ncpl": ncpl,
        "cell2d": cell2d,
        "top": top,
        "botm": np.asarray(botm),
    }
