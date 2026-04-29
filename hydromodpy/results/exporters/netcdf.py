"""Export simulation fields from Zarr to NetCDF-4 with UGRID topology.

The exported file can be opened in QGIS (MDAL driver), THREDDS, or any
tool that understands the UGRID-1.0 convention.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr
import zarr

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry

logger = get_logger(__name__)


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
        Path to the simulation Zarr store.
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

    descriptors = {name: field_registry.get(name) for name in variables}

    root = zarr.open_group(str(zarr_path), mode="r")
    grp = root

    mesh = grp.get("mesh")
    if mesh is None or "vertices" not in mesh or "face_node_connectivity" not in mesh:
        raise KeyError(
            f"UGRID mesh (vertices, face_node_connectivity) not found for sim={sim_id}. "
            "NetCDF-UGRID export requires a full mesh. Use GeoTIFF or CSV export instead."
        )
    vertices = mesh["vertices"][:]
    connectivity = mesh["face_node_connectivity"][:]
    z_interfaces = mesh["z_interfaces"][:]
    n_nodes = vertices.shape[0]
    connectivity.shape[0]
    connectivity.shape[1]
    len(z_interfaces) - 1

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
        descriptor = descriptors[var_name]
        arr = _resolve_zarr_path(grp, descriptor.zarr_path)
        if arr is None:
            logger.warning(
                "Variable '%s' (zarr_path=%r) not present in sim %s, skipping",
                var_name,
                descriptor.zarr_path,
                sim_id,
            )
            continue

        data = arr[:]
        ts_idx = list(range(data.shape[0])) if timesteps is None else timesteps
        data = data[ts_idx]

        attrs = {**field_registry.cf_attrs(var_name), "mesh": "mesh2d", "location": "face"}
        if data.ndim == 3:
            ds[var_name] = xr.DataArray(data, dims=("time", "layer", "n_face"), attrs=attrs)
        elif data.ndim == 2:
            ds[var_name] = xr.DataArray(data, dims=("time", "n_face"), attrs=attrs)

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
