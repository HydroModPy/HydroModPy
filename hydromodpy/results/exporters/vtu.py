"""Export simulation fields from Zarr to VTU (ParaView / PyVista).

A VTU file carries no CRS of its own. The run metadata goes into the
``FieldData`` of the grid, which VTK, and so ParaView and PyVista, keep
through a load and a save. A number is an ``Int32`` array of one value. A
text is its UTF-8 bytes in a ``UInt8`` array, read back with
``bytes(array).decode()``. A VTK ``String`` array would show as text in
ParaView, but meshio refuses a whole file holding one, and meshio is how
HydroModPy and many scripts read a VTU.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.results.exporters._fields import one_layer, read_field_step
from hydromodpy.results.zarr_store import SimulationZarr

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
        field_data = {**_stored_field_data(sz.root, sim_id), **dict(metadata or {})}
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
    if output_path.suffix.lower() == ".vtu":
        _write_field_data(output_path, field_data)
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


def _write_field_data(path: Path, values: Mapping[str, str | int]) -> None:
    """Add ``values`` to the ``FieldData`` of the VTU meshio wrote at ``path``.

    meshio writes no ``FieldData``, so the block is added to its XML, ahead of
    the piece as VTK writes it. Only the names of :data:`RUN_FIELD_DATA` are
    written. A destination named other than ``.vtu`` is another format meshio
    picked from the suffix, and gets no block.
    """
    block = ElementTree.Element("FieldData")
    for name in RUN_FIELD_DATA:
        value = values.get(name)
        if value is None:
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            vtk_type, items = "Int32", [int(value)]
        else:
            vtk_type, items = "UInt8", list(str(value).encode("utf-8"))
        array = ElementTree.SubElement(
            block,
            "DataArray",
            {
                "type": vtk_type,
                "Name": name,
                "NumberOfTuples": str(len(items)),
                "format": "ascii",
            },
        )
        array.text = " ".join(str(item) for item in items)
    if not len(block):
        return
    tree = ElementTree.parse(path)
    grid = tree.getroot().find("UnstructuredGrid")
    if grid is None:
        raise ValueError(f"{path} holds no UnstructuredGrid: it is not a VTU file meshio wrote")
    grid.insert(0, block)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _layer_arrays(data: np.ndarray, variable: str, layer: int | None) -> dict[str, np.ndarray]:
    """Return the cell arrays to write: the layer asked for, or every layer."""
    if data.ndim == 1 or layer is not None:
        return {variable: one_layer(data, variable, layer, "VTU")}
    n_layers = int(data.shape[0])
    if n_layers == 1:
        return {variable: data[0]}
    return {f"{variable}_layer{index}": data[index] for index in range(n_layers)}


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
