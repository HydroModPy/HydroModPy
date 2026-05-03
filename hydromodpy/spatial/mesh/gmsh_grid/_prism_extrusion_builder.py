"""Vertical extrusion of one planar 2D mesh into a 3D prism mesh."""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid._prism_data import (
    NODES_PER_3D_CELL,
    ExtrudedPrismMeshData,
)
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D


def build_default_components(
    planar_mesh: GmshPlanarMesh2D,
    z_interfaces: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Repeat the planar mesh at every interface and connect adjacent levels."""
    n_planar_nodes = int(planar_mesh.points_xy.shape[0])
    n_levels = int(z_interfaces.size)
    n_layers = int(n_levels - 1)
    n_planar_cells = int(planar_mesh.n_cells)

    # Points are stacked level by level so the vertical layout stays explicit.
    points_xyz = np.vstack(
        [
            np.column_stack(
                (
                    planar_mesh.points_xy,
                    np.full(n_planar_nodes, float(z_value), dtype=float),
                )
            )
            for z_value in z_interfaces
        ]
    )
    point_layer_indices: np.ndarray[Any, Any] = np.repeat(
        np.arange(n_levels, dtype=int), n_planar_nodes
    )
    point_base_indices: np.ndarray[Any, Any] = np.tile(
        np.arange(n_planar_nodes, dtype=int), n_levels
    )

    prism_connectivity: np.ndarray[Any, Any] = np.empty(
        (n_layers * n_planar_cells, NODES_PER_3D_CELL[planar_mesh.cell_type]),
        dtype=int,
    )
    layer_indices: np.ndarray[Any, Any] = np.empty(n_layers * n_planar_cells, dtype=int)
    source_cell_indices: np.ndarray[Any, Any] = np.empty(n_layers * n_planar_cells, dtype=int)
    base_connectivity: np.ndarray[Any, Any] = np.asarray(planar_mesh.connectivity, dtype=int)
    for layer_idx in range(n_layers):
        offset_top = layer_idx * n_planar_nodes
        offset_bot = (layer_idx + 1) * n_planar_nodes
        start = layer_idx * n_planar_cells
        stop = start + n_planar_cells
        prism_connectivity[start:stop, : base_connectivity.shape[1]] = (
            base_connectivity + offset_top
        )
        prism_connectivity[start:stop, base_connectivity.shape[1] :] = (
            base_connectivity + offset_bot
        )
        layer_indices[start:stop] = layer_idx
        source_cell_indices[start:stop] = np.arange(n_planar_cells, dtype=int)
    return (
        points_xyz,
        prism_connectivity,
        layer_indices,
        source_cell_indices,
        point_layer_indices,
        point_base_indices,
    )


def build_planar_mesh_from_data(mesh_data: ExtrudedPrismMeshData) -> GmshPlanarMesh2D:
    """Reconstruct the base 2D mesh from the layer-0 slice of a 3D extrusion."""
    point_mask = np.asarray(mesh_data.point_layer_indices == 0, dtype=bool)
    base_points = np.asarray(mesh_data.points_xyz[point_mask, :2], dtype=float)
    base_order = np.asarray(mesh_data.point_base_indices[point_mask], dtype=int)
    if base_points.shape[0] == 0:
        raise ValueError("Extruded mesh does not expose any node on layer interface 0")
    order = np.argsort(base_order)
    base_points = base_points[order]
    base_connectivity: np.ndarray[Any, Any] = np.empty(
        (
            int(np.max(mesh_data.source_cell_indices)) + 1,
            3 if mesh_data.cell_type_2d == "triangle" else 4,
        ),
        dtype=int,
    )
    point_base_by_node = np.asarray(mesh_data.point_base_indices, dtype=int)
    layer0_mask = np.asarray(mesh_data.layer_indices == 0, dtype=bool)
    if not np.any(layer0_mask):
        raise ValueError("Extruded mesh does not expose any prism on layer 0")
    first_half_width = base_connectivity.shape[1]
    layer0_conn = np.asarray(
        mesh_data.prism_connectivity[layer0_mask, :first_half_width], dtype=int
    )
    layer0_source = np.asarray(mesh_data.source_cell_indices[layer0_mask], dtype=int)
    sort_order = np.argsort(layer0_source)
    for idx, source_cell in enumerate(layer0_source[sort_order]):
        base_connectivity[source_cell] = point_base_by_node[layer0_conn[sort_order[idx]]]
    return GmshPlanarMesh2D(
        points_xy=base_points,
        connectivity=base_connectivity,
        cell_type=mesh_data.cell_type_2d,
        target_n_cells=base_connectivity.shape[0],
    )
