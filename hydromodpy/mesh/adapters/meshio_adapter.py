"""Round-trip conversion between HydroMesh and meshio Mesh objects.

meshio is the I/O backbone: VTU, MSH, XDMF, etc.  These two functions ensure
lossless conversion so that ``HydroMesh`` can be serialized to any format
meshio supports.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.mesh.cell_types import CellType
from hydromodpy.mesh.hydro_mesh import CellBlock, HydroMesh

# meshio name → CellType
_FROM_MESHIO: dict[str, CellType] = {
    ct.meshio_name: ct for ct in CellType
}


def from_meshio(mesh: Any) -> HydroMesh:
    """Convert a meshio ``Mesh`` into a ``HydroMesh``."""
    points = np.asarray(mesh.points, dtype=float)
    if points.ndim != 2 or points.shape[1] < 2:
        raise ValueError("meshio mesh must have at least 2D points")
    # Keep only xy or xyz
    vertices = points[:, : min(points.shape[1], 3)]

    cell_blocks: list[CellBlock] = []
    for block in mesh.cells:
        raw_type = str(block.type).strip().lower()
        ct = _FROM_MESHIO.get(raw_type)
        if ct is None:
            continue  # skip unsupported (line, vertex, etc.)
        cell_blocks.append(
            CellBlock(
                cell_type=ct,
                connectivity=np.asarray(block.data, dtype=int),
            )
        )

    if not cell_blocks:
        raise ValueError(
            "meshio mesh contains no supported cell types "
            f"({', '.join(sorted(_FROM_MESHIO))})"
        )

    # Collect cell_data: flatten per-block lists into flat arrays
    cell_data: dict[str, np.ndarray] = {}
    meshio_cell_data = getattr(mesh, "cell_data", {}) or {}
    for key, per_block_list in meshio_cell_data.items():
        if not isinstance(per_block_list, (list, tuple)):
            continue
        # Filter to keep only blocks we retained
        retained_indices = []
        for idx, block in enumerate(mesh.cells):
            raw_type = str(block.type).strip().lower()
            if raw_type in _FROM_MESHIO:
                retained_indices.append(idx)
        arrays = [
            np.asarray(per_block_list[i]).reshape(-1)
            for i in retained_indices
            if i < len(per_block_list)
        ]
        if arrays:
            cell_data[key] = np.concatenate(arrays)

    # Collect point_data
    point_data: dict[str, np.ndarray] = {}
    meshio_point_data = getattr(mesh, "point_data", {}) or {}
    for key, arr in meshio_point_data.items():
        point_data[key] = np.asarray(arr).reshape(-1)

    return HydroMesh(
        vertices=vertices,
        cell_blocks=tuple(cell_blocks),
        cell_data=cell_data,
        point_data=point_data,
    )


def to_meshio(hydro_mesh: HydroMesh) -> Any:
    """Convert a ``HydroMesh`` back into a meshio ``Mesh``."""
    try:
        import meshio  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ImportError("meshio is required for to_meshio()") from exc

    # Ensure 3D points for meshio
    verts = np.asarray(hydro_mesh.vertices, dtype=float)
    if verts.shape[1] == 2:
        verts = np.column_stack((verts, np.zeros(verts.shape[0], dtype=float)))

    cells = [
        (block.cell_type.meshio_name, np.asarray(block.connectivity, dtype=int))
        for block in hydro_mesh.cell_blocks
    ]

    # Rebuild per-block cell_data lists
    cell_data: dict[str, list[np.ndarray]] = {}
    if hydro_mesh.cell_data:
        block_sizes = [b.n_cells for b in hydro_mesh.cell_blocks]
        for key, flat_arr in hydro_mesh.cell_data.items():
            flat = np.asarray(flat_arr).reshape(-1)
            splits = np.cumsum(block_sizes[:-1])
            cell_data[key] = list(np.split(flat, splits))

    point_data: dict[str, np.ndarray] = {}
    for key, arr in hydro_mesh.point_data.items():
        point_data[key] = np.asarray(arr)

    return meshio.Mesh(
        points=verts,
        cells=cells,
        cell_data=cell_data,
        point_data=point_data,
    )
