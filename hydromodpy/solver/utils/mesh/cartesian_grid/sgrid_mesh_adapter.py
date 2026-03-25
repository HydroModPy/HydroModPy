"""Adapters from structured-grid objects to field-mesh objects.

Why this module exists
----------------------
The solver side (``SolverMesh`` or FloPy ``StructuredGrid``) and the field
side (``StructuredFieldMesh`` used by field/geology discretization) do not
share the same object model.  This module is the bridge between both worlds.

The adapter follows a simple contract:
1) recover consistent vertex coordinates from the solver grid,
2) expose them in the format expected by ``StructuredFieldMesh``.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.field.meshes import StructuredFieldMesh


def extract_structured_vertices(sgrid) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(x_vertices, y_vertices)`` from a StructuredGrid-like object.

    Extraction strategy (from most explicit to most generic):
    1) use ``xvertices`` / ``yvertices`` when available;
    2) use ``xyzvertices`` when exposed as a tuple/list;
    3) reconstruct from ``delr`` / ``delc`` and offsets.

    Returned arrays are always 2D float arrays compatible with
    ``StructuredFieldMesh(x_plot=..., y_plot=...)``.
    """
    # Preferred path: explicit 2D vertex arrays already computed by the grid.
    if hasattr(sgrid, "xvertices") and hasattr(sgrid, "yvertices"):
        x_vertices = np.asarray(getattr(sgrid, "xvertices"), dtype=float)
        y_vertices = np.asarray(getattr(sgrid, "yvertices"), dtype=float)
        if x_vertices.ndim == 2 and y_vertices.ndim == 2:
            return x_vertices, y_vertices

    # Alternative path used by some grid objects:
    # xyzvertices = (x_vertices, y_vertices, z_vertices, ...).
    if hasattr(sgrid, "xyzvertices"):
        xyz = getattr(sgrid, "xyzvertices")
        if isinstance(xyz, (tuple, list)) and len(xyz) >= 2:
            x_vertices = np.asarray(xyz[0], dtype=float)
            y_vertices = np.asarray(xyz[1], dtype=float)
            if x_vertices.ndim == 2 and y_vertices.ndim == 2:
                return x_vertices, y_vertices

    # Fallback path: rebuild vertices from cell sizes and origin offsets.
    # - delr: cell widths along X (columns)
    # - delc: cell heights along Y (rows)
    # Edges are cumulative sums from (xoff, yoff).
    delr = np.asarray(getattr(sgrid, "delr"), dtype=float).reshape(-1)
    delc = np.asarray(getattr(sgrid, "delc"), dtype=float).reshape(-1)
    xoff = float(getattr(sgrid, "xoffset", getattr(sgrid, "xoff", 0.0)))
    yoff = float(getattr(sgrid, "yoffset", getattr(sgrid, "yoff", 0.0)))
    x_edges = xoff + np.concatenate(([0.0], np.cumsum(delr)))
    y_edges = yoff + np.concatenate(([0.0], np.cumsum(delc)))
    # indexing='xy' gives arrays shaped as (nrow+1, ncol+1), aligned with
    # standard map coordinates (X horizontal, Y vertical).
    x_vertices, y_vertices = np.meshgrid(x_edges, y_edges, indexing="xy")
    return np.asarray(x_vertices, dtype=float), np.asarray(y_vertices, dtype=float)


def build_field_mesh_from_sgrid(sgrid) -> StructuredFieldMesh:
    """Build a ``StructuredFieldMesh`` view from one solver grid.

    The resulting mesh is geometry-only: it carries vertices plus light hints
    used by downstream discretization routines.
    """
    x_vertices, y_vertices = extract_structured_vertices(sgrid)
    nrow = int(getattr(sgrid, "nrow"))
    ncol = int(getattr(sgrid, "ncol"))
    return StructuredFieldMesh(
        x_plot=x_vertices,
        y_plot=y_vertices,
        # Keep explicit expected number of cells for consistency checks.
        target_n_cells=int(nrow * ncol),
        # Resolution hint is used only as a soft guidance by field utilities.
        resolution_hint=max(int(nrow), int(ncol)),
    )
