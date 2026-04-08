"""Zarr v3 layout for simulation results (UGRID convention)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import zarr
import zarr.codecs

if TYPE_CHECKING:
    from zarr import Group

BLOSC_ZSTD = zarr.codecs.BloscCodec(cname="zstd", clevel=3)


def create_simulation_group(
    store: zarr.storage.StoreLike,
    sim_id: str,
    *,
    n_cells: int,
    n_layers: int,
    cell_types: list[str] | None = None,
) -> Group:
    """Create the top-level group for one simulation inside the Zarr store.

    Subgroups ``mesh/``, ``derived/``, ``budget/``, ``pathlines/`` are
    created empty, ready to receive arrays.

    Parameters
    ----------
    store : zarr.storage.StoreLike
        Root Zarr store (typically ``zarr.open_group(path)``).
    sim_id : str
        Simulation UUID used as group name.
    n_cells : int
        Number of 2D cells in the mesh.
    n_layers : int
        Number of vertical layers.
    cell_types : list[str], optional
        Cell type labels (e.g. ``["triangle"]``).
    """
    root = zarr.open_group(store, mode="a")
    grp = root.require_group(sim_id)

    grp.attrs["n_cells"] = n_cells
    grp.attrs["n_layers"] = n_layers
    if cell_types is not None:
        grp.attrs["cell_types"] = cell_types

    for sub in ("mesh", "derived", "budget", "pathlines"):
        grp.require_group(sub)

    return grp


def write_mesh_arrays(
    group: Group,
    vertices: np.ndarray,
    face_node_connectivity: np.ndarray,
    z_interfaces: np.ndarray,
    layer_indices: np.ndarray | None = None,
    source_cell_indices: np.ndarray | None = None,
    *,
    start_index: int = 0,
) -> None:
    """Write mesh topology arrays into ``group['mesh/']``.

    Parameters
    ----------
    group : zarr.Group
        Simulation-level group (contains a ``mesh/`` subgroup).
    vertices : np.ndarray
        Node coordinates, shape ``(n_nodes, 2)`` or ``(n_nodes, 3)``.
    face_node_connectivity : np.ndarray
        Cell-to-node connectivity, shape ``(n_cells, max_vpf)``, fill ``-1``.
    z_interfaces : np.ndarray
        Vertical layer interfaces, shape ``(n_layers + 1,)``.
    layer_indices : np.ndarray, optional
        Layer index per 3D prism, shape ``(n_prisms,)``.
    source_cell_indices : np.ndarray, optional
        Source 2D cell index per 3D prism, shape ``(n_prisms,)``.
    start_index : int
        Node numbering start index (0 or 1). Stored in ``.zattrs``.
    """
    mesh = group["mesh"]

    mesh.create_array(
        "vertices", data=vertices.astype("float64"), overwrite=True,
    )
    mesh.create_array(
        "face_node_connectivity",
        data=face_node_connectivity.astype("int32"),
        overwrite=True,
    )
    mesh.create_array(
        "z_interfaces", data=z_interfaces.astype("float64"), overwrite=True,
    )

    if layer_indices is not None:
        mesh.create_array(
            "layer_indices",
            data=layer_indices.astype("int32"),
            overwrite=True,
        )
    if source_cell_indices is not None:
        mesh.create_array(
            "source_cell_indices",
            data=source_cell_indices.astype("int32"),
            overwrite=True,
        )

    mesh.attrs["start_index"] = start_index
    mesh.attrs["n_nodes"] = vertices.shape[0]
    mesh.attrs["n_cells"] = face_node_connectivity.shape[0]
    mesh.attrs["n_layers"] = len(z_interfaces) - 1


def write_field_chunk(
    group: Group,
    variable: str,
    timestep: int,
    values: np.ndarray,
    *,
    n_timesteps: int | None = None,
    subgroup: str | None = None,
) -> None:
    """Write one timestep of a field variable into Zarr.

    The dataset is created on the first call (requires *n_timesteps*).
    Subsequent calls write into the existing array at the given timestep index.

    Parameters
    ----------
    group : zarr.Group
        Simulation-level group.
    variable : str
        Variable name (e.g. ``"head"``, ``"concentration"``).
    timestep : int
        Zero-based timestep index.
    values : np.ndarray
        Field values. Shape ``(n_layers, n_cells)`` for 3D fields or
        ``(n_cells,)`` for 2D fields.
    n_timesteps : int, optional
        Total number of timesteps. Required on first call to allocate the
        array.
    subgroup : str, optional
        Target subgroup (e.g. ``"derived"``, ``"budget"``). If ``None``,
        write at the simulation group root.
    """
    if subgroup:
        if subgroup not in group:
            group.create_group(subgroup)
        target = group[subgroup]
    else:
        target = group

    if values.ndim == 1:
        full_shape = (n_timesteps, values.shape[0]) if n_timesteps else None
        chunk_shape = (1, values.shape[0])
    elif values.ndim == 2:
        n_layers, n_cells = values.shape
        full_shape = (n_timesteps, n_layers, n_cells) if n_timesteps else None
        chunk_shape = (1, n_layers, n_cells)
    else:
        raise ValueError(f"Expected 1D or 2D values, got shape {values.shape}")

    if variable not in target:
        if n_timesteps is None:
            raise ValueError(
                f"n_timesteps required on first write of '{variable}'"
            )
        target.create_array(
            variable,
            shape=full_shape,
            chunks=chunk_shape,
            dtype=values.dtype,
            compressors=BLOSC_ZSTD,
            fill_value=np.nan,
            overwrite=True,
        )

    arr = target[variable]
    if values.ndim == 1:
        arr[timestep, :] = values
    else:
        arr[timestep, :, :] = values
