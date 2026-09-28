"""Export simulation fields from Zarr to VTU (ParaView / PyVista)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.results.exporters._fields import one_layer, read_field_step
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
    values: np.ndarray | None = None,
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
        Timestep index. Ignored for a static field.
    output_path : str or Path
        Destination ``.vtu`` file.
    layer : int, optional
        Layer of a field of several layers. Left out, every layer is written,
        one cell array per layer named ``<variable>_layer<N>``; a field of one
        layer keeps its bare name.
    values : numpy.ndarray, optional
        The per-cell values to write, when the caller computed them.

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
    >>> export_vtu(run_zarr, run.sim_id, "head", -1, "head.vtu")  # doctest: +SKIP
    """
    try:
        import meshio
    except ImportError as exc:
        raise ImportError("VTU export requires meshio: pip install meshio") from exc

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sz = SimulationZarr(zarr_path)
    try:
        mesh = sz.root["mesh"]
        vertices = mesh["vertices"][:]
        connectivity = mesh["face_node_connectivity"][:]
        data = values if values is not None else read_field_step(sz, sim_id, variable, timestep)
    finally:
        sz.close()

    # Pad vertices to 3D if needed
    if vertices.shape[1] == 2:
        vertices = np.column_stack([vertices, np.zeros(vertices.shape[0])])

    cells, cell_indices = _build_meshio_cells(connectivity)
    cell_data = {
        name: _split_cell_data(layer_values, cell_indices)
        for name, layer_values in _layer_arrays(np.asarray(data), variable, layer).items()
    }
    mesh_out = meshio.Mesh(points=vertices, cells=cells, cell_data=cell_data)
    meshio.write(str(output_path), mesh_out)
    logger.info("Exported VTU: %s", output_path)
    return output_path


def _layer_arrays(data: np.ndarray, variable: str, layer: int | None) -> dict[str, np.ndarray]:
    """Return the cell arrays to write: the layer asked for, or every layer."""
    if data.ndim == 1 or layer is not None:
        return {variable: one_layer(data, variable, layer, "VTU")}
    n_layers = int(data.shape[0])
    if n_layers == 1:
        return {variable: data[0]}
    return {f"{variable}_layer{index + 1}": data[index] for index in range(n_layers)}


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
