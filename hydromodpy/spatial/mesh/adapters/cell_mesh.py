"""Planar cell meshes from the three current producers.

The regular grid, the gmsh triangulation with its runtime support, and the
Voronoi dual of that triangulation with the support rebuilt on it. Each adapter
keeps the producer's cells and vertex order as they are, states the centre rule
the solvers use today, maps the support families to face families and measures
the QA.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.spatial.mesh.adapters.field_mesh_adapter import from_gmsh_planar
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import DerivedGeometry, derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    FaceFamilyTable,
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
    from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import GmshSupportMetadata
    from hydromodpy.spatial.mesh.model.grid_wrappers import RegularGrid

__all__ = [
    "cell_mesh_from_regular_grid",
    "cell_mesh_from_triangulation",
    "cell_mesh_from_voronoi_dual",
]

_ENGINE_VERSION = "1.0.0"
_SIDE_NAMES = {
    "west_side": "west",
    "east_side": "east",
    "south_side": "south",
    "north_side": "north",
}
_NODE_TOLERANCE_M = 1.0e-3
"""Largest gap [m] between a support vertex and the mesh vertex (a .msh rounds to 1e-6 m)."""


def cell_mesh_from_regular_grid(grid: RegularGrid, *, crs_wkt: str) -> PlanarCellMesh:
    """Wrap a regular grid: the quads of ``RegularGrid.to_hydro_mesh``, row 0 north."""
    mesh = grid.to_hydro_mesh()
    nrow, ncol = (int(v) for v in grid.shape)
    xmin, ymax = grid.origin
    x = xmin + (np.arange(ncol) + 0.5) * float(grid.dx)
    y = ymax - (np.arange(nrow) + 0.5) * float(grid.dy)
    xx, yy = np.meshgrid(x, y, indexing="xy")
    return build_planar_cell_mesh(
        mesh,
        np.column_stack([xx.ravel(), yy.ravel()]),
        center_kind="cell_center",
        crs_wkt=crs_wkt,
        identity=MeshIdentity("regular", _ENGINE_VERSION, "", None),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
        structured_shape=(nrow, ncol),
        domain_area_m2=nrow * ncol * float(grid.dx) * float(grid.dy),
    )


def cell_mesh_from_triangulation(
    mesh: GmshPlanarMesh2D | HydroMesh,
    support: GmshSupportMetadata | None,
    *,
    crs_wkt: str,
) -> PlanarCellMesh:
    """Wrap a gmsh triangulation; centres are the vertex means the solvers use.

    The support gives the face families: ``rivers``, ``geology`` (with the zones
    of both sides) and ``boundary:<side>``.
    """
    hydro = mesh if isinstance(mesh, HydroMesh) else from_gmsh_planar(mesh)
    if hydro.ndim != 2 or hydro.cell_types != (CellType.TRIANGLE,):
        raise ValueError("cell_mesh_from_triangulation needs one planar block of triangles")
    centers = hydro.vertices[np.asarray(hydro.flat_connectivity)].mean(axis=1)
    geometry = derive_geometry(hydro)
    families, cell_zone, zone_names = _support_families(support, hydro, geometry)
    return build_planar_cell_mesh(
        hydro,
        centers,
        geometry=geometry,
        center_kind="vertex_mean",
        crs_wkt=crs_wkt,
        identity=MeshIdentity("triangle", _ENGINE_VERSION, "", None),
        declarations={
            "graded": True,
            "exact_faces": True,
            "deterministic": False,
            "needs_cache": True,
        },
        face_families=families,
        cell_zone=cell_zone,
        zone_names=zone_names,
    )


def cell_mesh_from_voronoi_dual(
    dual: HydroMesh,
    support_on_dual: GmshSupportMetadata,
    *,
    crs_wkt: str,
) -> PlanarCellMesh:
    """Wrap the Voronoi dual of a triangulation; centres are its generators.

    ``support_on_dual`` is the support rebuilt on the dual cells
    (``support_on_planar_mesh``); it gives the ``rivers`` and ``boundary:<side>``
    face families.
    """
    generators = dual.cell_data.get("disv_cell_center")
    if generators is None:
        raise ValueError("a Voronoi dual carries its generators in cell_data['disv_cell_center']")
    if dual.ndim != 2 or dual.cell_types != (CellType.POLYGON,):
        raise ValueError("cell_mesh_from_voronoi_dual needs one planar block of polygons")
    geometry = derive_geometry(dual)
    families, cell_zone, zone_names = _support_families(support_on_dual, dual, geometry)
    return build_planar_cell_mesh(
        dual,
        np.asarray(generators, dtype=np.float64).reshape(-1, 2),
        geometry=geometry,
        center_kind="generator",
        crs_wkt=crs_wkt,
        identity=MeshIdentity("voronoi", _ENGINE_VERSION, "", None),
        declarations={
            "graded": True,
            "exact_faces": False,
            "deterministic": False,
            "needs_cache": True,
        },
        face_families=families,
        cell_zone=cell_zone,
        zone_names=zone_names,
    )


def _check_support_matches(
    support: GmshSupportMetadata, mesh: HydroMesh, geometry: DerivedGeometry
) -> None:
    """Refuse a support that indexes other cells or other vertices than ``mesh``.

    The cell count and the vertices do not tell a permuted cell order apart, so
    every support edge must also border the same two cells in the mesh.
    """
    if support.n_cells != mesh.n_cells:
        raise ValueError(
            f"the support describes {support.n_cells} cells, the mesh has {mesh.n_cells}"
        )
    nodes = np.column_stack([support.node_x_m, support.node_y_m])
    if nodes.shape != mesh.vertices.shape or not np.allclose(
        nodes, mesh.vertices, rtol=0.0, atol=_NODE_TOLERANCE_M
    ):
        raise ValueError("the support vertices are not the mesh vertices")
    n_nodes = np.int64(mesh.n_nodes)
    node_a = np.asarray(support.edge_node_a_index, dtype=np.int64)
    node_b = np.asarray(support.edge_node_b_index, dtype=np.int64)
    wanted = np.minimum(node_a, node_b) * n_nodes + np.maximum(node_a, node_b)
    known = geometry.edge_nodes[:, 0] * n_nodes + geometry.edge_nodes[:, 1]
    position = np.minimum(np.searchsorted(known, wanted), max(known.size - 1, 0))
    if known.size == 0 or np.any(known[position] != wanted):
        raise ValueError("a support edge joins two vertices that are not a mesh edge")
    mesh_cells = np.sort(geometry.edge_cells[position], axis=1)
    support_cells = np.sort(
        np.column_stack([support.edge_cell_a, support.edge_cell_b]).astype(np.int64), axis=1
    )
    wrong = np.any(mesh_cells != support_cells, axis=1)
    if np.any(wrong):
        raise ValueError(
            f"the support names other cells than the mesh on {int(wrong.sum())} edges: "
            "its cells are not in the cell order of the mesh"
        )


def _zone_index(keys: np.ndarray, zone_names: tuple[str, ...]) -> np.ndarray:
    """Return the index of each key in the sorted ``zone_names``, -1 for an empty key."""
    if not zone_names or keys.size == 0:
        return np.full(keys.size, -1, dtype=np.int32)
    index = np.searchsorted(np.asarray(zone_names), keys)
    return np.where(keys != "", index, -1).astype(np.int32)


def _support_families(
    support: GmshSupportMetadata | None, mesh: HydroMesh, geometry: DerivedGeometry
) -> tuple[FaceFamilyTable | None, np.ndarray | None, tuple[str, ...]]:
    """Map a runtime support to face families, cell zones and zone names.

    Rows keep the support orientation: ``cell_a`` is the owner cell, ``cell_b``
    the other cell or -1. A geology face carries the zone of each side.
    """
    if support is None or np.asarray(support.edge_ids).size == 0:
        return None, None, ()
    _check_support_matches(support, mesh, geometry)
    key_a = np.asarray(support.geology_a_key, dtype=str)
    key_b = np.asarray(support.geology_b_key, dtype=str)
    zone_names = tuple(sorted((set(key_a.tolist()) | set(key_b.tolist())) - {""}))
    zone_a = _zone_index(key_a, zone_names)
    zone_b = _zone_index(key_b, zone_names)
    cell_a = np.asarray(support.edge_cell_a, dtype=np.int64)
    cell_b = np.asarray(support.edge_cell_b, dtype=np.int64)

    selections = {
        "rivers": np.flatnonzero(np.asarray(support.edge_is_river, dtype=bool)),
        "geology": np.flatnonzero(np.asarray(support.edge_kind) == "geology_interface"),
    }
    edge_ids = np.asarray(support.edge_ids, dtype=np.int64)
    position = np.argsort(edge_ids, kind="stable")
    labelled = np.fromiter(support.boundary_labels_by_edge_id, dtype=np.int64)
    labels = np.asarray(list(support.boundary_labels_by_edge_id.values()), dtype=str)
    rows_of_labelled = position[np.searchsorted(edge_ids, labelled, sorter=position)]
    for label in sorted(set(labels.tolist())):
        name = f"boundary:{_SIDE_NAMES.get(label, label)}"
        selections[name] = np.sort(rows_of_labelled[labels == label])
    selections = {name: rows for name, rows in selections.items() if rows.size}

    cell_zone = None
    if zone_names:
        cell_zone = np.full(mesh.n_cells, -1, dtype=np.int32)
        cell_zone[cell_a] = zone_a
        inner = cell_b >= 0
        cell_zone[cell_b[inner]] = zone_b[inner]
    if not selections:
        return None, cell_zone, zone_names

    rows = np.concatenate(list(selections.values()))
    return (
        FaceFamilyTable(
            names=tuple(selections),
            family=np.repeat(np.arange(len(selections)), [r.size for r in selections.values()]),
            cell_a=cell_a[rows],
            cell_b=cell_b[rows],
            node_a=np.asarray(support.edge_node_a_index, dtype=np.int64)[rows],
            node_b=np.asarray(support.edge_node_b_index, dtype=np.int64)[rows],
            zone_left=zone_a[rows],
            zone_right=zone_b[rows],
        ),
        cell_zone,
        zone_names,
    )
