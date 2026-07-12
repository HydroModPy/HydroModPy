"""Export simulation fields from Zarr to VTU (ParaView / PyVista)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry
from hydromodpy.results.zarr_store import SimulationZarr

logger = get_logger(__name__)


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

    Raises
    ------
    ImportError
        Raised when ``meshio`` is not installed.
    KeyError
        Raised when ``variable`` is not stored in the Zarr hierarchy.

    Examples
    --------
    >>> export_vtu(run_zarr, run.sim_id, "head", -1, "head.vtu")
    """
    try:
        import meshio
    except ImportError as exc:
        raise ImportError("VTU export requires meshio: pip install meshio") from exc

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    descriptor = field_registry.get(variable)

    sz = SimulationZarr(zarr_path)
    try:
        grp = sz.root
        mesh = grp["mesh"]
        vertices = mesh["vertices"][:]
        connectivity = mesh["face_node_connectivity"][:]

        # Read field data
        arr = _resolve_zarr_path(grp, descriptor.zarr_path)
        if arr is None:
            raise KeyError(
                f"Variable '{variable}' (zarr_path={descriptor.zarr_path!r}) "
                f"not found for sim={sim_id}"
            )
        data = arr[timestep]
    finally:
        sz.close()

    # Pad vertices to 3D if needed
    if vertices.shape[1] == 2:
        vertices = np.column_stack([vertices, np.zeros(vertices.shape[0])])

    # Build meshio cells from face_node_connectivity
    cells, cell_indices = _build_meshio_cells(connectivity)

    if data.ndim == 2:
        # 3D field (layer, cell) → extract one layer
        data = data[layer or 0]

    mesh_out = meshio.Mesh(
        points=vertices,
        cells=cells,
        cell_data={variable: _split_cell_data(data, cell_indices)},
    )
    meshio.write(str(output_path), mesh_out)
    logger.info("Exported VTU: %s", output_path)
    return output_path


def _build_meshio_cells(connectivity: np.ndarray) -> tuple[list, list[np.ndarray]]:
    """Convert UGRID face_node_connectivity to meshio cell blocks.

    Groups faces by valence (number of valid vertices) so mixed and Voronoi/PEBI
    meshes keep every node: 3 -> ``triangle``, 4 -> ``quad``, >=5 -> ``polygon``.
    UGRID pads unused slots with a negative fill value at the tail of each row.
    Returns the cell blocks and, per block, the original face indices so field
    data can be gathered in the same cell order.
    """
    import meshio

    valence = (connectivity >= 0).sum(axis=1)
    type_for = {3: "triangle", 4: "quad"}

    cells: list = []
    cell_indices: list[np.ndarray] = []
    for n in np.unique(valence):
        n = int(n)
        if n < 3:
            continue
        face_idx = np.nonzero(valence == n)[0]
        block = connectivity[face_idx, :n]
        cells.append(meshio.CellBlock(type_for.get(n, "polygon"), block))
        cell_indices.append(face_idx)
    return cells, cell_indices


def _split_cell_data(data: np.ndarray, cell_indices: list[np.ndarray]) -> list[np.ndarray]:
    """Gather flat per-cell data into per-block arrays matching the cell blocks."""
    return [data[idx] for idx in cell_indices]


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
