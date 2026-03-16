"""Adapters between HydroMesh and flopy grid objects.

The two main pathways:

1. **from_flopy_structured** — read a flopy ``StructuredGrid`` into a
   ``HydroMesh`` (preserving the structured_shape hint).
2. **to_flopy_disv_args** — export a planar ``HydroMesh`` as the keyword
   arguments needed by ``flopy.mf6.ModflowGwfdisv`` (vertices, cell2d,
   top, botm).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.mesh.cell_types import CellType
from hydromodpy.mesh.hydro_mesh import CellBlock, HydroMesh


def from_flopy_structured(sgrid) -> HydroMesh:
    """Convert a flopy ``StructuredGrid`` into a 2D ``HydroMesh``.

    The grid's vertex coordinates are extracted from ``xvertices`` /
    ``yvertices`` (preferred), ``xyzvertices``, or ``delr`` / ``delc``.
    """
    # Reuse existing extraction logic
    from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_mesh_adapter import (
        extract_structured_vertices,
    )

    x_verts, y_verts = extract_structured_vertices(sgrid)
    ny, nx = x_verts.shape  # (nrow+1, ncol+1)
    vertices = np.column_stack((x_verts.reshape(-1), y_verts.reshape(-1)))

    # Build quadrilateral connectivity (nrow * ncol cells)
    nrow, ncol = ny - 1, nx - 1
    connectivity = np.empty((nrow * ncol, 4), dtype=int)
    idx = 0
    for j in range(nrow):
        for i in range(ncol):
            n00 = j * nx + i
            n10 = j * nx + (i + 1)
            n11 = (j + 1) * nx + (i + 1)
            n01 = (j + 1) * nx + i
            connectivity[idx] = [n00, n10, n11, n01]
            idx += 1

    return HydroMesh(
        vertices=vertices,
        cell_blocks=(
            CellBlock(
                cell_type=CellType.QUADRILATERAL,
                connectivity=connectivity,
            ),
        ),
        structured_shape=(nrow, ncol),
    )


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
    """
    if hydro_mesh.ndim != 2:
        raise ValueError("to_flopy_disv_args requires a 2D mesh")

    verts = np.asarray(hydro_mesh.vertices, dtype=float)
    nvert = verts.shape[0]
    # DISV vertices: list of (iv, xv, yv)
    vertices = [
        [int(i), float(verts[i, 0]), float(verts[i, 1])]
        for i in range(nvert)
    ]

    conn = hydro_mesh.flat_connectivity
    ncpl = conn.shape[0]
    # cell2d: list of (icell, xc, yc, ncvert, iv1, iv2, ...)
    cell2d: list[list] = []
    for ic in range(ncpl):
        nodes = conn[ic]
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
