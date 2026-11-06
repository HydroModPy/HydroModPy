"""Export simulation fields from Zarr to NetCDF-4 with UGRID topology.

The exported file can be opened in QGIS (MDAL driver), THREDDS, or any
tool that understands the UGRID-1.0 convention.

A field that has layers is one variable with a ``layer`` dimension, whatever
the number of layers, so a script reads the same name on every model. QGIS reads
a mesh through MDAL, which binds a dataset to the face dimension and leaves out an
array carrying a third one, so a file for QGIS asks for one layer: the variable
then has no ``layer`` dimension and carries the layer as a scalar coordinate. The
CRS is stated twice for the same reason: once the CF way, once the way MDAL reads
it.

The face centers are the ones the model used (``mesh/face_x`` and
``mesh/face_y`` of the store). A store without them gives the mean of the
vertices of each face, which is off the generator of a Voronoi cell.
"""

from __future__ import annotations

import json
import numbers
import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry
from hydromodpy.results.derive.virtual_fields import field_descriptor
from hydromodpy.results.exporters.fields import is_timed, resolve_zarr_path
from hydromodpy.results.zarr_store import SimulationZarr

logger = get_logger(__name__)


def export_netcdf(
    zarr_path: str | Path,
    sim_id: str,
    variables: list[str],
    output_path: str | Path,
    *,
    timesteps: list[int] | None = None,
    values: Mapping[str, np.ndarray] | None = None,
    global_attrs: Mapping[str, Any] | None = None,
    layer: int | None = None,
) -> Path:
    """Export selected fields to a NetCDF-4 file with UGRID topology.

    Parameters
    ----------
    zarr_path : str or Path
        Path to the simulation Zarr store.
    sim_id : str
        Simulation UUID.
    variables : list[str]
        Field names to export (e.g. ``["head", "watertable_depth"]``). A field
        stored per layer is written as one variable with a ``layer`` dimension
        at any number of layers, the layers counted from 0 at the top like
        every layer index of HydroModPy.
    output_path : str or Path
        Destination ``.nc`` file.
    timesteps : list[int], optional
        Subset of timestep indices to export. ``None`` exports all. A static
        field (topography, a conductivity) is written once, without time.
    values : mapping of str to numpy.ndarray, optional
        Fields the caller computed, by name, each a ``(len(timesteps),
        n_cells)`` stack. The store is not read for them.
    global_attrs : mapping, optional
        Global attributes laid over the ones the store holds: the ACDD block
        of the run when it is exported before the seal writes it.
    layer : int, optional
        Keep this layer of every field that has layers, as a variable without
        a ``layer`` dimension, which is the form QGIS reads.

    Returns
    -------
    Path
        The written file path.

    Raises
    ------
    KeyError
        Raised when the simulation store does not contain a UGRID mesh.
    ValueError
        Raised when a time-dependent export has no Zarr time coordinate.

    Examples
    --------
    >>> export_netcdf(
    ...     run_zarr, run.sim_id, ["head", "watertable_depth"], "fields.nc"
    ... )  # doctest: +SKIP
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    descriptors = {name: field_descriptor(name) for name in variables}
    computed = dict(values or {})

    sz = SimulationZarr(zarr_path)
    try:
        grp = sz.root
        crs_attrs = dict(grp["crs"].attrs) if "crs" in grp else {}
        # Propagate the ACDD/CF root attrs persisted in the Zarr store
        # (composed by hydromodpy.results.zarr_store.acdd.compose_acdd_root_attrs).
        root_attrs = {str(k): v for k, v in dict(grp.attrs).items()}

        mesh = grp.get("mesh")
        if mesh is None or "vertices" not in mesh or "face_node_connectivity" not in mesh:
            raise KeyError(
                f"UGRID mesh (vertices, face_node_connectivity) not found for sim={sim_id}. "
                "NetCDF-UGRID export requires a full mesh. Use GeoTIFF or CSV export instead."
            )
        vertices = mesh["vertices"][:]
        connectivity = mesh["face_node_connectivity"][:]
        z_interfaces = mesh["z_interfaces"][:]
        start_index = int(mesh.attrs.get("start_index", 0))
        centres = (
            (mesh["face_x"][:], mesh["face_y"][:])
            if "face_x" in mesh and "face_y" in mesh
            else None
        )
    finally:
        sz.close()
    n_nodes = vertices.shape[0]

    # Build UGRID topology dataset
    ds = xr.Dataset()
    # Carry over every ACDD/CF root attribute from the Zarr store, then
    # override Conventions to advertise UGRID-1.0 alongside CF/ACDD and pin
    # the simulation_id explicitly. The Zarr root advertises
    # ``CF-1.11, ACDD-1.3, UGRID-1.0`` already, so this is mostly defensive
    # for a store that says nothing.
    for key, value in {**root_attrs, **dict(global_attrs or {})}.items():
        if value is None:
            continue
        ds.attrs[key] = _netcdf_attr(value)
    ds.attrs.setdefault("Conventions", "CF-1.11, ACDD-1.3, UGRID-1.0")
    ds.attrs["simulation_id"] = sim_id
    # The mesh says how large it is; a root written before the seal says 0.
    ds.attrs["n_cells"] = int(connectivity.shape[0])
    ds.attrs["n_layers"] = max(int(z_interfaces.shape[0]) - 1, 1)

    # Mesh topology variable (scalar placeholder per UGRID convention)
    ds["mesh2d"] = xr.DataArray(
        data=np.int32(0),
        attrs={
            "cf_role": "mesh_topology",
            "topology_dimension": 2,
            "node_coordinates": "node_x node_y",
            "face_node_connectivity": "face_nodes",
            "face_coordinates": "face_x face_y",
            "face_dimension": "n_face",
        },
    )

    ds["node_x"] = xr.DataArray(vertices[:, 0], dims=("n_node",), attrs=_axis_attrs("x", crs_attrs))
    ds["node_y"] = xr.DataArray(vertices[:, 1], dims=("n_node",), attrs=_axis_attrs("y", crs_attrs))
    if vertices.shape[1] == 3:
        ds["node_z"] = xr.DataArray(vertices[:, 2], dims=("n_node",))

    ds["face_nodes"] = xr.DataArray(
        connectivity,
        dims=("n_face", "max_vertices_per_face"),
        attrs={
            "cf_role": "face_node_connectivity",
            "start_index": start_index,
            "_FillValue": -1,
        },
    )
    ds["z_interfaces"] = xr.DataArray(
        z_interfaces,
        dims=("n_z_interface", "n_face"),
        attrs={
            "long_name": "Altitude of layer interfaces: model top, then the bottom of each layer",
            "units": "m",
            "positive": "up",
        },
    )
    if crs_attrs:
        ds["crs"] = xr.DataArray(np.int32(0), attrs=crs_attrs)
        mdal_crs = _mdal_crs_attrs(crs_attrs)
        if mdal_crs:
            ds["projected_coordinate_system"] = xr.DataArray(np.int32(0), attrs=mdal_crs)

    if centres is None:
        valid_mask = connectivity >= 0
        cx = np.where(valid_mask, vertices[np.clip(connectivity, 0, n_nodes - 1), 0], np.nan)
        cy = np.where(valid_mask, vertices[np.clip(connectivity, 0, n_nodes - 1), 1], np.nan)
        centres = (np.nanmean(cx, axis=1), np.nanmean(cy, axis=1))
    ds["face_x"] = xr.DataArray(centres[0], dims=("n_face",), attrs=_axis_attrs("x", crs_attrs))
    ds["face_y"] = xr.DataArray(centres[1], dims=("n_face",), attrs=_axis_attrs("y", crs_attrs))

    zarr_time: np.ndarray | None = None
    zarr_time_attrs: dict[str, object] = {}
    sz = SimulationZarr(zarr_path)
    try:
        grp = sz.root
        if "time" in grp:
            zarr_time = np.asarray(grp["time"][:])
            zarr_time_attrs = dict(grp["time"].attrs)
        ts_idx = None if timesteps is None else [int(t) for t in timesteps]
        for var_name in variables:
            descriptor = descriptors[var_name]
            timed = is_timed(descriptor)
            if var_name in computed:
                data = np.asarray(computed[var_name])
            else:
                arr = resolve_zarr_path(grp, descriptor.zarr_path)
                if arr is None:
                    data = _derive_stack(sz, sim_id, var_name, ts_idx, zarr_time)
                    if data is None:
                        logger.warning(
                            "Variable '%s' (zarr_path=%r) not present in sim %s, skipping",
                            var_name,
                            descriptor.zarr_path,
                            sim_id,
                        )
                        continue
                else:
                    data = np.asarray(arr[:])
                    if timed and ts_idx is not None:
                        data = data[ts_idx]
            _add_field(ds, var_name, data, timed=timed, attrs=_field_attrs(var_name), layer=layer)
    finally:
        sz.close()

    if "time" in ds.dims:
        time_indices = list(range(ds.sizes["time"])) if timesteps is None else list(timesteps)
        if zarr_time is None or max(time_indices, default=-1) >= len(zarr_time):
            raise ValueError("NetCDF export requires a Zarr time coordinate.")
        time_values = zarr_time[time_indices]
        ds["time"] = xr.DataArray(
            time_values,
            dims=("time",),
            attrs={"standard_name": "time", **zarr_time_attrs},
        )
    # zlib-compress the array variables (the Zarr source is Blosc-compressed, so
    # an uncompressed .nc balloons) and give float fields a CF _FillValue when
    # none is declared. Skip vars that already carry _FillValue in attrs (e.g.
    # face_nodes = -1) since xarray forbids it in both attrs and encoding. Pin
    # engine/format so a scipy-only environment cannot silently emit NETCDF3.
    encoding: dict[str, dict[str, object]] = {}
    for name, var in ds.variables.items():
        enc: dict[str, object] = {}
        if var.ndim >= 1 and np.issubdtype(var.dtype, np.number):
            enc["zlib"] = True
            enc["complevel"] = 4
        if (
            np.issubdtype(var.dtype, np.floating)
            and "_FillValue" not in var.attrs
            and name not in ds.coords
        ):
            enc["_FillValue"] = float("nan")
        if enc:
            encoding[name] = enc

    # Write beside the destination, then rename. netCDF4 truncates its output
    # before writing it, so exporting onto a file QGIS still holds open failed
    # halfway and left a zero-byte file where the previous export was. A rename
    # swaps the inode instead: the open layer keeps reading what it already has
    # until it is reloaded, and a failed export destroys nothing.
    tmp_path = output_path.with_name(f"{output_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        ds.to_netcdf(tmp_path, engine="netcdf4", format="NETCDF4", encoding=encoding)
        os.replace(tmp_path, output_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    logger.info("Exported NetCDF: %s", output_path)
    return output_path


def _netcdf_attr(value: object) -> object:
    """Return a global attribute in a form NetCDF stores.

    NetCDF takes text, numbers and flat lists of either. A mapping, such as
    the identity block of the run, or a list of anything else becomes JSON
    text, and a boolean becomes 0 or 1.
    """
    if isinstance(value, bool | np.bool_):
        return int(value)
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True, default=_json_scalar)
    if isinstance(value, list | tuple):
        texts = all(isinstance(item, str) for item in value)
        reals = all(
            isinstance(item, numbers.Real) and not isinstance(item, bool | np.bool_)
            for item in value
        )
        if not (texts or reals):
            return json.dumps(list(value), sort_keys=True, default=_json_scalar)
    return value


def _json_scalar(value: object) -> object:
    """Return a numpy scalar as the Python number JSON writes; refuse anything else."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _axis_attrs(axis: str, crs_attrs: Mapping[str, object]) -> dict[str, object]:
    """Return the attributes of an x or y coordinate, naming the CRS when there is one."""
    attrs: dict[str, object] = {
        "standard_name": f"projection_{axis}_coordinate",
        "units": "m",
    }
    if crs_attrs:
        attrs["grid_mapping"] = "crs"
    return attrs


def _field_attrs(name: str) -> dict[str, object]:
    """Return the CF attributes of one field, the rebuilt-only ones included."""
    if field_registry.has(name):
        attrs = field_registry.cf_attrs(name)
    else:
        descriptor = field_descriptor(name)
        attrs = {
            "long_name": descriptor.long_name,
            "units": descriptor.units,
            "cell_methods": descriptor.cell_methods,
        }
        if descriptor.valid_min is not None:
            attrs["valid_min"] = descriptor.valid_min
        if descriptor.valid_max is not None:
            attrs["valid_max"] = descriptor.valid_max
    return {**attrs, "mesh": "mesh2d", "location": "face"}


def _add_field(
    ds: xr.Dataset,
    var_name: str,
    data: np.ndarray,
    *,
    timed: bool,
    attrs: dict[str, object],
    layer: int | None,
) -> None:
    """Add one field to the dataset, as one variable.

    A field with layers has a ``layer`` dimension at any number of layers. A
    field with fewer layers than the model, a recharge applied to the top one,
    names its own dimension, since a NetCDF dimension has one size. With ``layer``
    the variable holds that layer alone, under a scalar ``layer`` coordinate.
    """
    dims: tuple[str, ...] = ("time", "n_face") if timed else ("n_face",)
    if data.ndim != (3 if timed else 2):
        ds[var_name] = xr.DataArray(data, dims=dims, attrs=attrs)
        return
    axis = 1 if timed else 0
    n_layers = int(data.shape[axis])
    if layer is not None:
        if not 0 <= int(layer) < n_layers:
            raise ValueError(
                f"layer = {layer} is out of range: {var_name!r} holds {n_layers} layer"
                f"{'s' if n_layers > 1 else ''} (0 to {n_layers - 1})."
            )
        ds[var_name] = xr.DataArray(
            np.take(data, int(layer), axis=axis),
            dims=dims,
            attrs={**attrs, "coordinates": "layer"},
            coords={"layer": int(layer)},
        )
        return
    name = "layer" if n_layers == int(ds.attrs["n_layers"]) else f"{var_name}_layer"
    dims = (*dims[:axis], name, *dims[axis:])
    ds[var_name] = xr.DataArray(data, dims=dims, attrs=attrs)
    if name not in ds.coords:
        ds[name] = xr.DataArray(
            np.arange(n_layers, dtype=np.int32),
            dims=(name,),
            attrs={"long_name": "Model layer, counted from 0 at the top", "units": "1"},
        )


def _mdal_crs_attrs(crs_attrs: dict[str, object]) -> dict[str, object]:
    """CRS attributes MDAL reads, for the ``projected_coordinate_system`` variable.

    The CF way of georeferencing a file is a grid-mapping variable carrying
    ``crs_wkt``, and the ``crs`` variable next to this one states it. MDAL,
    which is what QGIS opens a UGRID mesh with, does not read it: it looks up
    one variable by name and takes ``epsg``, then ``wkt``, which it parses as
    WKT1 only. Handed the WKT2 that ``crs_wkt`` holds it keeps no CRS at all,
    and QGIS then draws the mesh in whatever the project uses, nowhere near
    the catchment. So the EPSG code goes first and the WKT is downgraded.
    """
    attrs: dict[str, object] = {}
    epsg = crs_attrs.get("epsg_code")
    if epsg is not None:
        attrs["epsg"] = int(epsg)  # type: ignore[arg-type]
    wkt = crs_attrs.get("crs_wkt")
    if wkt:
        from pyproj import CRS as _CRS

        try:
            attrs["wkt"] = _CRS.from_wkt(str(wkt)).to_wkt("WKT1_GDAL")
        except Exception as exc:
            # A CRS pyproj cannot round-trip to WKT1 (a compound or a custom
            # one) leaves the EPSG code to carry the georeferencing alone.
            logger.debug("No WKT1 form for the run CRS, keeping the EPSG code only: %s", exc)
    return attrs


def _derive_stack(sz, sim_id: str, variable: str, timesteps, zarr_time) -> np.ndarray | None:
    """Rebuild a non-persisted field over the exported timesteps, or None.

    Water-table elevation/depth, seepage mask and drain outflow are computed
    on read rather than stored, so an export must rebuild them to stay
    faithful to what ``query_field()`` returns.
    """
    from hydromodpy.results.derive.virtual_fields import derive_field_stack

    n_time = None
    if zarr_time is not None:
        n_time = int(len(zarr_time))
    elif "head" in sz.root:
        n_time = int(sz.root["head"].shape[0])
    if n_time is None:
        return None
    if timesteps is None:
        return derive_field_stack(sz, sim_id, variable, list(range(n_time)))
    outside = [int(t) for t in timesteps if not -n_time <= int(t) < n_time]
    if outside:
        # A stored field indexed by numpy refuses these steps too.
        raise IndexError(f"timesteps {outside} are outside the {n_time} steps of the run")
    indices = [int(t) % n_time for t in timesteps]
    return derive_field_stack(sz, sim_id, variable, indices)
