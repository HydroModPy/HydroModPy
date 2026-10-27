"""Export simulation fields from Zarr to VTU (ParaView / PyVista).

The cells come from the ``mesh/`` group of the run store, in its order, and
the file is written by ``write_vtu`` of ``hydromodpy/spatial/mesh/io/vtu.py``,
the one VTU writer of HydroModPy. A VTU file carries no CRS of its own. The run
metadata (:data:`RUN_FIELD_DATA`) goes into the ``FieldData`` of the grid, as
that module writes it: a number is an ``Int32`` array of one value, a text its
UTF-8 bytes in a ``UInt8`` array, read back with ``read_vtu_field_data``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import meshio
import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.results.exporters._fields import one_layer, read_field_step
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.spatial.mesh.io.meshio_bridge import to_meshio
from hydromodpy.spatial.mesh.io.vtu import write_vtu
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

logger = get_logger(__name__)

RUN_FIELD_DATA = ("sim_id", "crs_wkt", "epsg_code", "license", "hydromodpy_version")
"""The run metadata a VTU carries in its ``FieldData``, each one when the run knows it."""


def export_vtu(
    zarr_path: str | Path,
    sim_id: str,
    variable: str,
    timestep: int,
    output_path: str | Path,
    *,
    layer: int | None = None,
    values: np.ndarray | None = None,
    metadata: Mapping[str, str | int] | None = None,
) -> Path:
    """Export one timestep of a field variable to a VTU file.

    A destination named other than ``.vtu`` is written by meshio in the format
    of its suffix, without the run metadata.

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
        one cell array per layer named ``<variable>_layer<N>``, ``N`` counted
        from 0 at the top; a field of one layer keeps its bare name.
    values : numpy.ndarray, optional
        The per-cell values to write, when the caller computed them.
    metadata : mapping of str to str or int, optional
        Run metadata laid over the one the store holds, by ``FieldData``
        name (:data:`RUN_FIELD_DATA`): the version of a run exported
        before its seal writes it on the store.

    Returns
    -------
    Path
        The written file path.

    Raises
    ------
    KeyError
        Raised when ``variable`` is not stored in the Zarr hierarchy.
    ValueError
        Raised when ``values`` do not hold one value per cell.

    Examples
    --------
    >>> export_vtu(run_zarr, run.sim_id, "head", -1, "head.vtu")  # doctest: +SKIP
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sz = SimulationZarr(zarr_path)
    try:
        mesh = sz.root["mesh"]
        vertices = mesh["vertices"][:]
        connectivity = mesh["face_node_connectivity"][:]
        data = values if values is not None else read_field_step(sz, sim_id, variable, timestep)
        field_data = {**_stored_field_data(sz.root, sim_id), **dict(metadata or {})}
    finally:
        sz.close()

    hydro_mesh = HydroMesh(
        vertices=vertices, cell_blocks=(_cell_block(np.asarray(connectivity)),)
    ).with_cell_data(**_layer_arrays(np.asarray(data), variable, layer))
    if output_path.suffix.lower() == ".vtu":
        run_metadata = {
            name: field_data[name] for name in RUN_FIELD_DATA if field_data.get(name) is not None
        }
        write_vtu(output_path, hydro_mesh, field_data=run_metadata)
    else:
        meshio.write(str(output_path), to_meshio(hydro_mesh))
    logger.info("Exported VTU: %s", output_path)
    return output_path


def _stored_field_data(root: Any, sim_id: str) -> dict[str, str | int]:
    """Return the run metadata the store holds: its CRS, and its licence and version once sealed."""
    crs = dict(root["crs"].attrs) if "crs" in root else {}
    found = {
        "sim_id": sim_id,
        "crs_wkt": crs.get("crs_wkt"),
        "epsg_code": crs.get("epsg_code"),
        "license": root.attrs.get("license"),
        "hydromodpy_version": root.attrs.get("hydromodpy_version"),
    }
    return {name: value for name, value in found.items() if value not in (None, "")}


def _cell_block(connectivity: np.ndarray) -> CellBlock:
    """Return the cells of a ``face_node_connectivity`` padded by -1, in the order of the store.

    Cells of three nodes, or of four, make a triangle or a quadrilateral block.
    Any other mesh, a Voronoi one among them, makes one ragged polygon block.
    """
    counts = (connectivity >= 0).sum(axis=1)
    if counts.size and int(counts.min()) == int(counts.max()) and int(counts[0]) in (3, 4):
        cell_type = CellType.TRIANGLE if int(counts[0]) == 3 else CellType.QUADRILATERAL
        return CellBlock(cell_type, connectivity[:, : int(counts[0])])
    return CellBlock(
        CellType.POLYGON,
        tuple(row[:count] for row, count in zip(connectivity, counts.tolist(), strict=True)),
    )


def _layer_arrays(data: np.ndarray, variable: str, layer: int | None) -> dict[str, np.ndarray]:
    """Return the cell arrays to write: the layer asked for, or every layer."""
    if data.ndim == 1 or layer is not None:
        return {variable: one_layer(data, variable, layer, "VTU")}
    n_layers = int(data.shape[0])
    if n_layers == 1:
        return {variable: data[0]}
    return {f"{variable}_layer{index}": data[index] for index in range(n_layers)}
