"""The cell mesh of a mesh bundle.

A bundle lists nodes, triangles and edges with their river flag. This module
reads them as a ``PlanarCellMesh``: the nodes and the triangles in the order of
the files, the vertex means as centres, the flagged edges as the ``rivers`` face
family and the boundary edges that lie on the bounding box as the
``boundary:<side>`` families.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import CatchmentMeshBundle
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    FaceFamilyTable,
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)

__all__ = ["cell_mesh_from_bundle"]

_ENGINE_VERSION = "1.0.0"
_SIDES = ("west", "east", "south", "north")


def cell_mesh_from_bundle(bundle: CatchmentMeshBundle, *, crs_wkt: str) -> PlanarCellMesh:
    """Read a bundle of triangles as a cell mesh.

    Cell and vertex ``i`` are the ``i``-th cell and node of the bundle. A face
    keeps the orientation of its bundle edge: ``cell_a`` is the cell the edge
    lists first, ``cell_b`` the other cell or -1.
    """
    node_position = {int(node.node_id): index for index, node in enumerate(bundle.nodes)}
    cell_position = {int(cell.cell_id): index for index, cell in enumerate(bundle.cells)}
    vertices = np.asarray([[node.x, node.y] for node in bundle.nodes], dtype=np.float64)
    arity = {len(cell.node_indices) for cell in bundle.cells}
    if arity != {3}:
        raise ValueError(
            f"a bundle cell mesh needs triangles; the cells have {sorted(arity)} nodes"
        )
    connectivity = np.asarray(
        [[node_position[int(node)] for node in cell.node_indices] for cell in bundle.cells],
        dtype=np.int64,
    )
    mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(cell_type=CellType.TRIANGLE, connectivity=connectivity),),
    )
    return build_planar_cell_mesh(
        mesh,
        vertices[connectivity].mean(axis=1),
        center_kind="vertex_mean",
        crs_wkt=crs_wkt,
        identity=MeshIdentity("triangle", _ENGINE_VERSION, "", None),
        declarations={
            "graded": True,
            "exact_faces": True,
            "deterministic": False,
            "needs_cache": True,
        },
        face_families=_face_families(bundle, node_position, cell_position, vertices),
    )


def _face_families(
    bundle: CatchmentMeshBundle,
    node_position: dict[int, int],
    cell_position: dict[int, int],
    vertices: np.ndarray,
) -> FaceFamilyTable | None:
    """Return the river faces and the faces of each outer side, or ``None`` when there is none."""
    edges = bundle.edges
    node_a = np.asarray([node_position[int(edge.node_a)] for edge in edges], dtype=np.int64)
    node_b = np.asarray([node_position[int(edge.node_b)] for edge in edges], dtype=np.int64)
    cell_a = np.asarray([cell_position[int(edge.cell_a)] for edge in edges], dtype=np.int64)
    cell_b = np.asarray(
        [-1 if edge.cell_b is None else cell_position[int(edge.cell_b)] for edge in edges],
        dtype=np.int64,
    )
    side_of_edge = _side_of_boundary_edges(vertices, node_a, node_b, cell_b)

    selections = {"rivers": np.flatnonzero([edge.is_river for edge in edges])}
    for side in sorted(_SIDES):
        selections[f"boundary:{side}"] = np.flatnonzero(side_of_edge == _SIDES.index(side))
    selections = {name: rows for name, rows in selections.items() if rows.size}
    if not selections:
        return None

    rows = np.concatenate(list(selections.values()))
    return FaceFamilyTable(
        names=tuple(selections),
        family=np.repeat(np.arange(len(selections)), [r.size for r in selections.values()]),
        cell_a=cell_a[rows],
        cell_b=cell_b[rows],
        node_a=node_a[rows],
        node_b=node_b[rows],
        zone_left=np.full(rows.size, -1),
        zone_right=np.full(rows.size, -1),
    )


def _side_of_boundary_edges(
    vertices: np.ndarray, node_a: np.ndarray, node_b: np.ndarray, cell_b: np.ndarray
) -> np.ndarray:
    """Return, per edge, the index in ``_SIDES`` of the side of the bounding box it lies on, else -1.

    Only boundary edges (``cell_b < 0``) take a side, by their midpoint, within
    ``1e-8`` of the span of the box (at least ``1e-9`` m). An edge on two sides,
    at a corner of a rectangle, takes the first of west, east, south, north.
    """
    x_min, y_min = vertices.min(axis=0)
    x_max, y_max = vertices.max(axis=0)
    tolerance_m = max(1.0e-9, 1.0e-8 * max(x_max - x_min, y_max - y_min, 1.0))
    mid_x = 0.5 * (vertices[node_a, 0] + vertices[node_b, 0])
    mid_y = 0.5 * (vertices[node_a, 1] + vertices[node_b, 1])
    on_side = np.column_stack(
        [
            np.isclose(mid_x, x_min, atol=tolerance_m, rtol=0.0),
            np.isclose(mid_x, x_max, atol=tolerance_m, rtol=0.0),
            np.isclose(mid_y, y_min, atol=tolerance_m, rtol=0.0),
            np.isclose(mid_y, y_max, atol=tolerance_m, rtol=0.0),
        ]
    )
    on_side &= (cell_b < 0)[:, None]
    return np.where(on_side.any(axis=1), on_side.argmax(axis=1), -1)
