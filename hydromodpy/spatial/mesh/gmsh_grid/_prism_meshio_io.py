"""Meshio interoperability for extruded 3D prism meshes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid._constants import (
    CELL_LAYER_KEY as _CELL_LAYER_KEY,
)
from hydromodpy.spatial.mesh.gmsh_grid._constants import (
    CELL_SOURCE_KEY as _CELL_SOURCE_KEY,
)
from hydromodpy.spatial.mesh.gmsh_grid._constants import (
    POINT_BASE_KEY as _POINT_BASE_KEY,
)
from hydromodpy.spatial.mesh.gmsh_grid._constants import (
    POINT_LAYER_KEY as _POINT_LAYER_KEY,
)
from hydromodpy.spatial.mesh.gmsh_grid._deps import require_meshio as _require_meshio
from hydromodpy.spatial.mesh.gmsh_grid._prism_data import (
    MESHIO_CELL_TYPE_BY_2D,
    ExtrudedPrismMeshData,
    stable_unique,
)


def _extract_cell_block(mesh: Any) -> tuple[int, str, np.ndarray]:
    """Return the single supported 3D cell block from one meshio mesh."""
    supported: list[tuple[int, str, np.ndarray]] = []
    for idx, block in enumerate(tuple(mesh.cells)):
        block_type = str(block.type).strip().lower()
        if block_type == "wedge":
            supported.append((idx, "triangle", np.asarray(block.data, dtype=int)))
        elif block_type == "hexahedron":
            supported.append((idx, "quadrilateral", np.asarray(block.data, dtype=int)))
    if not supported:
        raise ValueError("Mesh does not contain supported 3D wedge/hexahedron cell blocks")
    if len(supported) > 1:
        raise ValueError("Mixed 3D extruded cell blocks are not supported in one mesh")
    return supported[0]


def _extract_one_cell_data(mesh: Any, *, key: str, block_index: int) -> np.ndarray | None:
    """Return one cell-data array aligned with the supported 3D block."""
    cell_data = getattr(mesh, "cell_data", {})
    values = cell_data.get(key)
    if values is None:
        return None
    if block_index >= len(values):
        raise ValueError(f"Mesh cell_data['{key}'] is inconsistent with cell blocks")
    return np.asarray(values[block_index], dtype=int).reshape(-1)


def _infer_mesh_data(mesh: Any) -> ExtrudedPrismMeshData:
    """Infer HydroModPy extrusion metadata from one meshio-compatible 3D mesh."""
    points_xyz = np.asarray(mesh.points, dtype=float)
    if points_xyz.ndim != 2 or points_xyz.shape[1] < 3:
        raise ValueError("Extruded mesh points must expose x, y and z coordinates")
    points_xyz = points_xyz[:, :3]

    block_index, cell_type_2d, prism_connectivity = _extract_cell_block(mesh)
    point_data = getattr(mesh, "point_data", {})
    point_layer_indices = point_data.get(_POINT_LAYER_KEY)
    point_base_indices = point_data.get(_POINT_BASE_KEY)
    layer_indices = _extract_one_cell_data(mesh, key=_CELL_LAYER_KEY, block_index=block_index)
    source_cell_indices = _extract_one_cell_data(
        mesh, key=_CELL_SOURCE_KEY, block_index=block_index
    )

    # Prefer explicit HydroModPy metadata when available. Fall back to geometry
    # inference only for simple layered meshes.
    if point_layer_indices is not None and point_base_indices is not None:
        point_layer_indices = np.asarray(point_layer_indices, dtype=int).reshape(-1)
        point_base_indices = np.asarray(point_base_indices, dtype=int).reshape(-1)
        if (
            point_layer_indices.size != points_xyz.shape[0]
            or point_base_indices.size != points_xyz.shape[0]
        ):
            raise ValueError("Point extrusion metadata does not match the number of points")
        level_ids = np.unique(point_layer_indices)
        z_interfaces = np.array(
            [
                float(np.mean(points_xyz[point_layer_indices == level_idx, 2]))
                for level_idx in np.sort(level_ids)
            ],
            dtype=float,
        )
    else:
        z_interfaces = stable_unique(points_xyz[:, 2])
        counts = [
            int(np.count_nonzero(np.isclose(points_xyz[:, 2], z_value, rtol=0.0, atol=1e-9)))
            for z_value in z_interfaces
        ]
        if len(set(counts)) != 1:
            raise ValueError(
                "Cannot infer layered point layout from the 3D mesh without hydromodpy metadata"
            )
        n_base_nodes = counts[0]
        if n_base_nodes * z_interfaces.size != points_xyz.shape[0]:
            raise ValueError(
                "Cannot infer layered point layout from the 3D mesh without hydromodpy metadata"
            )
        point_layer_indices = np.repeat(np.arange(z_interfaces.size, dtype=int), n_base_nodes)
        point_base_indices = np.tile(np.arange(n_base_nodes, dtype=int), z_interfaces.size)

    n_layers = int(z_interfaces.size - 1)
    if n_layers <= 0:
        raise ValueError("Extruded mesh requires at least one vertical layer")

    if layer_indices is None or source_cell_indices is None:
        if prism_connectivity.shape[0] % n_layers != 0:
            raise ValueError(
                "Cannot infer prism ordering from the 3D mesh without hydromodpy metadata"
            )
        n_base_cells = prism_connectivity.shape[0] // n_layers
        layer_indices = np.repeat(np.arange(n_layers, dtype=int), n_base_cells)
        source_cell_indices = np.tile(np.arange(n_base_cells, dtype=int), n_layers)

    return ExtrudedPrismMeshData(
        points_xyz=points_xyz,
        prism_connectivity=prism_connectivity,
        cell_type_2d=cell_type_2d,
        z_interfaces=z_interfaces,
        layer_indices=layer_indices,
        source_cell_indices=source_cell_indices,
        point_layer_indices=point_layer_indices,
        point_base_indices=point_base_indices,
        source_path=None if getattr(mesh, "path", None) is None else Path(mesh.path),
    )


def extruded_mesh_data_to_meshio(mesh_data: ExtrudedPrismMeshData):
    """Convert one raw extrusion payload to a meshio mesh."""
    meshio = _require_meshio()
    cell_type = MESHIO_CELL_TYPE_BY_2D[mesh_data.cell_type_2d]
    return meshio.Mesh(
        points=np.asarray(mesh_data.points_xyz, dtype=float),
        cells=[(cell_type, np.asarray(mesh_data.prism_connectivity, dtype=int))],
        point_data={
            _POINT_LAYER_KEY: np.asarray(mesh_data.point_layer_indices, dtype=int),
            _POINT_BASE_KEY: np.asarray(mesh_data.point_base_indices, dtype=int),
        },
        cell_data={
            _CELL_LAYER_KEY: [np.asarray(mesh_data.layer_indices, dtype=int)],
            _CELL_SOURCE_KEY: [np.asarray(mesh_data.source_cell_indices, dtype=int)],
        },
    )


def meshio_to_extruded_mesh_data(mesh: Any) -> ExtrudedPrismMeshData:
    """Convert one meshio mesh to the raw HydroModPy extrusion payload."""
    return _infer_mesh_data(mesh)


def read_extruded_prism_mesh(path: str | Path) -> ExtrudedPrismMeshData:
    """Read one persisted extruded prism mesh from disk."""
    meshio = _require_meshio()
    path_obj = Path(path).resolve()
    mesh = meshio.read(path_obj)
    mesh.path = path_obj
    return meshio_to_extruded_mesh_data(mesh)


def write_extruded_prism_mesh(
    path: str | Path,
    mesh_data: ExtrudedPrismMeshData,
    *,
    file_format: str | None = None,
) -> Path:
    """Write one raw extrusion payload to disk through meshio."""
    meshio = _require_meshio()
    path_obj = Path(path).resolve()
    meshio.write(path_obj, extruded_mesh_data_to_meshio(mesh_data), file_format=file_format)
    return path_obj
