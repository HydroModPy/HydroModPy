"""Export simulation fields from Zarr to VTU (ParaView / PyVista)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import zarr

from hydromodpy.results import field_registry

logger = logging.getLogger(__name__)


def export_vtu(
    zarr_path: str | Path,
    sim_id: str,
    variable: str,
    timestep: int,
    output_path: str | Path,
    *,
    layer: int | None = None,
) -> Path:
    """Export one timestep of a field variable to a VTU file.

    Requires ``meshio`` (optional dependency).

    Parameters
    ----------
    zarr_path : str or Path
        Path to the simulation Zarr store.
    sim_id : str
        Simulation UUID.
    variable : str
        Field name (e.g. ``"head"``).
    timestep : int
        Timestep index.
    output_path : str or Path
        Destination ``.vtu`` file.
    layer : int, optional
        Layer index for 3D fields. If ``None``, the first layer is used.

    Returns
    -------
    Path
        The written file path.
    """
    try:
        import meshio
    except ImportError as exc:
        raise ImportError("VTU export requires meshio: pip install meshio") from exc

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    descriptor = field_registry.get(variable)

    root = zarr.open_group(str(zarr_path), mode="r")
    grp = root
    mesh = grp["mesh"]

    vertices = mesh["vertices"][:]
    connectivity = mesh["face_node_connectivity"][:]
    connectivity.shape[0]
    max_vpf = connectivity.shape[1]

    # Pad vertices to 3D if needed
    if vertices.shape[1] == 2:
        vertices = np.column_stack([vertices, np.zeros(vertices.shape[0])])

    # Build meshio cells from face_node_connectivity
    cells = _build_meshio_cells(connectivity, max_vpf)

    # Read field data
    arr = _resolve_zarr_path(grp, descriptor.zarr_path)
    if arr is None:
        raise KeyError(
            f"Variable '{variable}' (zarr_path={descriptor.zarr_path!r}) not found for sim={sim_id}"
        )

    data = arr[timestep]
    if data.ndim == 2:
        # 3D field (layer, cell) → extract one layer
        data = data[layer or 0]

    mesh_out = meshio.Mesh(
        points=vertices,
        cells=cells,
        cell_data={variable: _split_cell_data(data, cells)},
    )
    meshio.write(str(output_path), mesh_out)
    logger.info("Exported VTU: %s", output_path)
    return output_path


def _build_meshio_cells(connectivity: np.ndarray, max_vpf: int) -> list:
    """Convert UGRID face_node_connectivity to meshio cell blocks."""
    import meshio

    tri_mask = (
        (connectivity[:, 3] == -1) if max_vpf >= 4 else np.ones(len(connectivity), dtype=bool)
    )
    quad_mask = ~tri_mask

    cells = []
    if tri_mask.any():
        cells.append(meshio.CellBlock("triangle", connectivity[tri_mask, :3]))
    if quad_mask.any():
        cells.append(meshio.CellBlock("quad", connectivity[quad_mask, :4]))
    return cells


def _split_cell_data(data: np.ndarray, cells: list) -> list[np.ndarray]:
    """Split flat cell data into per-block arrays matching meshio cells."""
    result = []
    offset = 0
    for block in cells:
        n = block.data.shape[0]
        result.append(data[offset : offset + n])
        offset += n
    return result


def _resolve_zarr_path(grp, zarr_path: str):
    """Resolve a registry zarr_path inside the simulation group, or None if absent."""
    parts = zarr_path.split("/")
    cursor = grp
    for part in parts[:-1]:
        sub = cursor.get(part)
        if sub is None:
            return None
        cursor = sub
    leaf = parts[-1]
    if leaf in cursor:
        return cursor[leaf]
    return None
