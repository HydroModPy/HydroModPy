"""Cells of the outer sides, of the river and of a labelled family of a cell mesh.

Every solver reads the cells that carry a side boundary, a stream boundary or a
named family through these three functions, whatever the mesh engine. The
families come from the face rows and the cell chains of the ``PlanarCellMesh``.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

logger = get_logger(__name__)

__all__ = ["SIDE_IDS", "label_cells", "side_cells", "stream_cells"]

SIDE_IDS = ("west_side", "east_side", "south_side", "north_side")
"""Side boundary ids, as the flow configuration names them."""

_RIVER_LABELS = frozenset({"stream", "river"})
_CENTRE_TOLERANCE_REL = 1.0e-6
_CENTRE_TOLERANCE_ABS_M = 1.0e-9


def side_cells(cell_mesh: PlanarCellMesh, side: str) -> np.ndarray:
    """Return the sorted cell ids that carry one outer side.

    ``side`` is ``west_side``, ``east_side``, ``south_side`` or ``north_side``.
    The cells are those with a face in the family ``boundary:<side>``: half a
    cell inside the domain on a regular grid, the cells touching the side on
    triangles. On a mesh centred on its generators (the Voronoi dual), a Dirichlet
    head belongs on the boundary: the side takes the cells whose centre lies on
    it, within ``1e-6`` of the cell size, and falls back to the cells with a face
    on the side, with a warning, when no centre lies there.
    """
    if side not in SIDE_IDS:
        raise ValueError(f"Unsupported side boundary id: {side}")
    touching = cell_mesh.family_cells(f"boundary:{side.removesuffix('_side')}")
    if cell_mesh.center_kind != "generator":
        return touching
    centred = _cells_centred_on_side(cell_mesh, side)
    if centred.size:
        return centred
    if touching.size:
        logger.warning(
            "No cell of the solver mesh is centred on %s; the %d cells with a face "
            "on it carry it instead.",
            side,
            int(touching.size),
        )
    return touching


def _cells_centred_on_side(cell_mesh: PlanarCellMesh, side: str) -> np.ndarray:
    """Return the cells whose centre lies on one side of the vertex box."""
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    axis = 0 if side in ("west_side", "east_side") else 1
    edge = (
        vertices[:, axis].min() if side in ("west_side", "south_side") else vertices[:, axis].max()
    )
    size = np.sqrt(cell_mesh.geometry.areas)
    tolerance = np.maximum(_CENTRE_TOLERANCE_ABS_M, _CENTRE_TOLERANCE_REL * size)
    return np.flatnonzero(np.abs(cell_mesh.centers[:, axis] - edge) <= tolerance)


def stream_cells(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Return the sorted cell ids of the river family.

    An engine that cuts the river into faces (triangles, Voronoi) gives the cells
    on both sides of every ``rivers`` face; an engine that rasterizes it (regular)
    gives the cells of its ``rivers`` chains.
    """
    if cell_mesh.face_rows("rivers").any():
        table = cell_mesh.face_families
        rows = cell_mesh.face_rows("rivers")
        cells = np.concatenate([table.cell_a[rows], table.cell_b[rows]])
        return np.unique(cells[cells >= 0])
    parts = [chain.cell_ids for chain in cell_mesh.chains("rivers")]
    if not parts:
        return np.empty(0, dtype=np.int64)
    return np.unique(np.concatenate(parts))


def label_cells(cell_mesh: PlanarCellMesh, label: str) -> np.ndarray:
    """Return the sorted cell ids selected by one support label, empty when it matches nothing.

    ``stream`` and ``river`` give the river cells, a side id (``west_side`` ...)
    gives the cells of that side, and ``boundary:<name>`` gives every cell with a
    face in that boundary family (a named gmsh physical group).
    """
    text = str(label).strip()
    if text in _RIVER_LABELS:
        return stream_cells(cell_mesh)
    if text in SIDE_IDS:
        return side_cells(cell_mesh, text)
    if text.startswith("boundary:"):
        return cell_mesh.family_cells(text)
    return np.empty(0, dtype=np.int64)
