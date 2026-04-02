"""Export simulation fields from Zarr to NetCDF-4 with UGRID topology.

The exported file can be opened in QGIS (MDAL driver), THREDDS, or any
tool that understands the UGRID-1.0 convention.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import xarray as xr
import zarr

logger = logging.getLogger(__name__)


def export_netcdf(
    zarr_path: str | Path,
    sim_id: str,
    variables: list[str],
    output_path: str | Path,
    *,
    timesteps: list[int] | None = None,
) -> Path:
    """Export selected fields to a NetCDF-4 file with UGRID topology.

    Parameters
    ----------
    zarr_path : str or Path
        Path to ``project_results.zarr``.
    sim_id : str
        Simulation UUID.
    variables : list[str]
        Field names to export (e.g. ``["head", "watertable_depth"]``).
    output_path : str or Path
        Destination ``.nc`` file.
    timesteps : list[int], optional
        Subset of timestep indices to export. ``None`` exports all.

    Returns
    -------
    Path
        The written file path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    root = zarr.open_group(str(zarr_path), mode="r")
    grp = root[sim_id]

    mesh = grp["mesh"]
    vertices = mesh["vertices"][:]
    connectivity = mesh["face_node_connectivity"][:]
    z_interfaces = mesh["z_interfaces"][:]
    n_nodes = vertices.shape[0]
    n_cells = connectivity.shape[0]
    max_vpf = connectivity.shape[1]
    n_layers = len(z_interfaces) - 1

    # Build UGRID topology dataset
    ds = xr.Dataset()
    ds.attrs["Conventions"] = "UGRID-1.0"
    ds.attrs["simulation_id"] = sim_id

    # Mesh topology variable (scalar placeholder per UGRID convention)
    ds["mesh2d"] = xr.DataArray(
        data=np.int32(0),
        attrs={
            "cf_role": "mesh_topology",
            "topology_dimension": 2,
            "node_coordinates": "node_x node_y",
            "face_node_connectivity": "face_nodes",
            "face_dimension": "n_face",
        },
    )

    ds["node_x"] = xr.DataArray(vertices[:, 0], dims=("n_node",))
    ds["node_y"] = xr.DataArray(vertices[:, 1], dims=("n_node",))
    if vertices.shape[1] == 3:
        ds["node_z"] = xr.DataArray(vertices[:, 2], dims=("n_node",))

    ds["face_nodes"] = xr.DataArray(
        connectivity,
        dims=("n_face", "max_vertices_per_face"),
        attrs={
            "cf_role": "face_node_connectivity",
            "start_index": int(mesh.attrs.get("start_index", 0)),
            "_FillValue": -1,
        },
    )
    ds["z_interfaces"] = xr.DataArray(z_interfaces, dims=("n_z_interface",))

    # Compute face centroids for spatial reference
    valid_mask = connectivity >= 0
    cx = np.where(valid_mask, vertices[np.clip(connectivity, 0, n_nodes - 1), 0], np.nan)
    cy = np.where(valid_mask, vertices[np.clip(connectivity, 0, n_nodes - 1), 1], np.nan)
    ds["face_x"] = xr.DataArray(np.nanmean(cx, axis=1), dims=("n_face",))
    ds["face_y"] = xr.DataArray(np.nanmean(cy, axis=1), dims=("n_face",))

    # Locate each requested variable in the Zarr hierarchy
    for var_name in variables:
        arr = _find_variable(grp, var_name)
        if arr is None:
            logger.warning("Variable '%s' not found in sim %s, skipping", var_name, sim_id)
            continue

        data = arr[:]
        ts_idx = list(range(data.shape[0])) if timesteps is None else timesteps
        data = data[ts_idx]

        if data.ndim == 3:
            # (timestep, layer, cell) → 3D field
            ds[var_name] = xr.DataArray(
                data,
                dims=("time", "layer", "n_face"),
                attrs={"mesh": "mesh2d", "location": "face"},
            )
        elif data.ndim == 2:
            # (timestep, cell) → 2D field
            ds[var_name] = xr.DataArray(
                data,
                dims=("time", "n_face"),
                attrs={"mesh": "mesh2d", "location": "face"},
            )

    if "time" in ds.dims:
        ds["time"] = xr.DataArray(
            np.arange(ds.sizes["time"]),
            dims=("time",),
            attrs={"units": "timestep index"},
        )
    if "layer" in ds.dims:
        ds["layer"] = xr.DataArray(np.arange(ds.sizes["layer"]), dims=("layer",))

    ds.to_netcdf(output_path)
    logger.info("Exported NetCDF: %s", output_path)
    return output_path


def _find_variable(grp, var_name: str):
    """Search for a variable in the simulation group and its subgroups."""
    if var_name in grp:
        return grp[var_name]
    for sub in ("derived", "budget"):
        sg = grp.get(sub)
        if sg is not None and var_name in sg:
            return sg[var_name]
    return None
