"""State, in the QA of a cell mesh, where its side heads sit relative to the side.

A Dirichlet head on a side is applied to the cells ``side_cells`` names, and those
cells are not at the same distance from the side on every engine: half a cell on a
regular grid, a third of a triangle height on triangles, nothing on a mesh centred
on its generators. The mesh keeps that position, and the QA states it.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.family_cells import SIDE_IDS, side_cells

__all__ = ["SIDE_OFFSET_KEY", "annotate_side_cells", "side_center_offset_m"]

SIDE_OFFSET_KEY = "side_center_offset_m_p50"
"""Key of the median side-centre distance in ``MeshQA.extras``."""


def side_center_offset_m(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Return the distance [m] from the centre of each side cell to its side.

    One value per pair of a side and a cell that carries it, on the four sides of
    the box of the vertices. Empty when no side family exists.
    """
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    distances = []
    for side in SIDE_IDS:
        cells = side_cells(cell_mesh, side)
        if cells.size == 0:
            continue
        axis = 0 if side in ("west_side", "east_side") else 1
        edge = (
            vertices[:, axis].min()
            if side in ("west_side", "south_side")
            else vertices[:, axis].max()
        )
        distances.append(np.abs(cell_mesh.centers[cells, axis] - edge))
    return np.concatenate(distances) if distances else np.empty(0, dtype=float)


def annotate_side_cells(cell_mesh: PlanarCellMesh, statement: str) -> PlanarCellMesh:
    """Return ``cell_mesh`` with the engine's side statement and the side-centre offset in its QA.

    ``statement`` says which cells carry a side head on this engine. The median
    distance of their centres to the side is added to ``qa.extras`` when the mesh
    has a side. The derived geometry is carried over, not computed again.
    """
    offsets = side_center_offset_m(cell_mesh)
    extras = dict(cell_mesh.qa.extras)
    if offsets.size:
        extras[SIDE_OFFSET_KEY] = float(np.median(offsets))
    return cell_mesh.with_qa(
        dataclasses.replace(cell_mesh.qa, notes=(*cell_mesh.qa.notes, statement), extras=extras)
    )
