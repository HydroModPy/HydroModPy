"""The cells of a planar cell mesh as the field supports read them.

A support field samples each cell from its kind and its vertices. ``mesh_cells``
gives them for every cell of a ``PlanarCellMesh``, ``cell_values`` checks an array
of one value per cell, and ``MeshWithValues`` carries such an array with its mesh.
``cell_mesh_from_edges`` builds the grid of quadrilaterals of the field demos.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)

__all__ = ("MeshCell", "MeshWithValues", "cell_mesh_from_edges", "cell_values", "mesh_cells")


@dataclass(frozen=True)
class MeshCell:
    """One mesh cell in geometric form.

    ``kind`` is the cell type value (``"quadrilateral"``, ``"triangle"`` or
    ``"polygon"``) and ``vertices`` the ``(k, 2)`` coordinates of its nodes, in
    their order in the cell.
    """

    index: int
    kind: str
    node_indices: tuple[int, ...]
    vertices: np.ndarray
    centroid: tuple[float, float]


@dataclass(frozen=True)
class MeshWithValues:
    """A planar cell mesh carrying one value per cell."""

    mesh: PlanarCellMesh
    cell_values: np.ndarray
    label: str | None = None

    @property
    def n_cells(self) -> int:
        """Number of cells."""
        return self.mesh.n_cells


def mesh_cells(cell_mesh: PlanarCellMesh) -> tuple[MeshCell, ...]:
    """Return the ``MeshCell`` of each cell of ``cell_mesh``, in cell order.

    The nodes of a cell are its row of ``connectivity_rows`` without the ``-1``
    slots. The centroid is the cell centre of the mesh.
    """
    kind = cell_mesh.mesh.cell_types[0].value
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    rows = np.asarray(cell_mesh.connectivity_rows)
    centers = cell_mesh.centers
    cells = []
    for index, row in enumerate(rows):
        nodes = row[row >= 0]
        cells.append(
            MeshCell(
                index=index,
                kind=kind,
                node_indices=tuple(int(node) for node in nodes),
                vertices=xy[nodes],
                centroid=(float(centers[index, 0]), float(centers[index, 1])),
            )
        )
    return tuple(cells)


def cell_values(cell_mesh: PlanarCellMesh, values: object) -> np.ndarray:
    """Return ``values`` flattened to one value per cell of ``cell_mesh``."""
    flat = np.asarray(values).reshape(-1)
    if flat.size != cell_mesh.n_cells:
        raise ValueError(
            "Cell values must contain exactly one value per cell: "
            f"got {flat.size} for {cell_mesh.n_cells} cells"
        )
    return flat


def cell_mesh_from_edges(x_edges: object, y_edges: object, *, crs_wkt: str) -> PlanarCellMesh:
    """Return the quadrilaterals between increasing x and y edges, row 0 south.

    The nodes of a cell run counter-clockwise from its south-west corner. The
    field demos keep this layout, so the points sampled in a cell stay the same
    to the bit. The mesh carries no ``structured_shape``, which a solver reads
    row 0 north.
    """
    x = np.asarray(x_edges, dtype=float).reshape(-1)
    y = np.asarray(y_edges, dtype=float).reshape(-1)
    if x.size < 2 or y.size < 2:
        raise ValueError("x_edges and y_edges must each contain at least 2 values")
    if not (np.all(np.diff(x) > 0.0) and np.all(np.diff(y) > 0.0)):
        raise ValueError("x_edges and y_edges must be strictly increasing")
    x_nodes, y_nodes = np.meshgrid(x, y, indexing="xy")
    n_x = x.size
    row, col = np.divmod(np.arange((y.size - 1) * (n_x - 1)), n_x - 1)
    south_west = row * n_x + col
    north_west = south_west + n_x
    quads = np.column_stack([south_west, south_west + 1, north_west + 1, north_west])
    x_centers, y_centers = np.meshgrid(0.5 * (x[:-1] + x[1:]), 0.5 * (y[:-1] + y[1:]))
    mesh = HydroMesh(
        vertices=np.column_stack((x_nodes.ravel(), y_nodes.ravel())),
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, quads),),
    )
    return build_planar_cell_mesh(
        mesh,
        np.column_stack((x_centers.ravel(), y_centers.ravel())),
        center_kind="cell_center",
        crs_wkt=crs_wkt,
        identity=MeshIdentity("structured", "1.0.0", "", None),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
    )
