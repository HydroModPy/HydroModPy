"""Write-side concerns for :class:`SimulationZarr`.

Owns every ``write_*`` entry point: mesh, time, CRS, fields, forcing
timeseries and raster, geographic rasters, and ACDD root attrs.
Also owns the chunk / sharding decisions and the CF attribute
composition that flows from the registry.

Helpers take the live :class:`SimulationZarr` so the module stays free
of hidden state and can be unit-tested in isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import zarr

from hydromodpy.core.logging import get_logger
from hydromodpy.core.nodata import SENTINEL_ABS_THRESHOLD
from hydromodpy.results import field_registry
from hydromodpy.results.zarr_store.acdd import compose_acdd_root_attrs
from hydromodpy.results.zarr_store.chunks import (
    compute_balanced_chunks_1d,
    compute_balanced_chunks_2d,
    compute_shard_shape_1d,
    compute_shard_shape_2d,
    should_use_sharding,
)
from hydromodpy.results.zarr_store.constants import BLOSC_ZSTD
from hydromodpy.results.zarr_store.zarr_schema import (
    child_zarr_path,
    ensure_local_zarr_node_dir,
    update_attrs,
)

if TYPE_CHECKING:
    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

logger = get_logger(__name__)


def field_name_from_target(target: zarr.Group, variable: str) -> str:
    """Return the canonical registry field name for ``(group, variable)``."""
    path = target.path or ""
    candidate = f"{path}/{variable}" if path else variable
    for name, desc in field_registry.FIELD_REGISTRY.items():
        if desc.zarr_path == candidate or desc.public_name == variable:
            return name
    return ""


def attrs_for_field(name: str, dtype: np.dtype) -> dict[str, object]:
    """Compose CF attrs for a field straight from the registry + _FillValue.

    A float field declares no ``_FillValue`` attribute. Its missing value is
    NaN, JSON has no token for NaN, and writing one anyway is what made every
    ``zarr.json`` of the corpus invalid under RFC 8259. The array's own Zarr
    ``fill_value`` already carries NaN, serialised as the string ``"NaN"`` the
    Zarr v3 spec defines for it, so nothing is lost and readers still mask.
    An integer sentinel has a JSON number and stays in the CF block.
    """
    if not field_registry.has(name):
        attrs: dict[str, object] = {}
    else:
        attrs = dict(field_registry.cf_attrs(name))
    if np.issubdtype(dtype, np.integer):
        attrs["_FillValue"] = int(np.iinfo(dtype).min)
        attrs["missing_value"] = int(np.iinfo(dtype).min)
    return attrs


def mask_sentinels(values: np.ndarray) -> np.ndarray:
    """Replace MODFLOW dry/no-flow head sentinels with NaN in a float array.

    HDRY/HNOFLO (~ +-1e30) and -6e30 are orders of magnitude above any physical
    head; masking them here, at the field write, means every transient field
    reaches Zarr already NaN-clean and CF ``_FillValue`` == NaN holds on read.
    A non-float array is returned untouched (NaN is invalid for integers).
    """
    if not np.issubdtype(values.dtype, np.floating):
        return values
    # Two comparisons instead of np.abs(): the slab can reach hundreds of MiB
    # and a materialised absolute copy would double the write-side peak.
    sentinel = (values > SENTINEL_ABS_THRESHOLD) | (values < -SENTINEL_ABS_THRESHOLD)
    if not sentinel.any():
        return values
    cleaned = values.copy()
    cleaned[sentinel] = np.nan
    return cleaned


def ensure_child_dir(store_obj: SimulationZarr, target: zarr.Group, name: str) -> None:
    """Pre-create a directory node under ``target`` for the live store."""
    ensure_local_zarr_node_dir(store_obj._path, child_zarr_path(target, name))


def maybe_shards(
    ndim: int,
    n_timesteps: int,
    chunk_shape: tuple[int, ...],
    itemsize: int,
    *,
    n_layers: int,
    n_cells: int,
) -> tuple[int, ...] | None:
    """Pick a shard shape when the total array size crosses the 100 MiB trigger."""
    layer_bytes_per_step = n_layers * n_cells * max(itemsize, 1)
    if not should_use_sharding(n_timesteps, layer_bytes_per_step):
        return None
    if ndim == 1:
        shard = compute_shard_shape_1d(
            n_timesteps,
            (chunk_shape[0], chunk_shape[1]),
            itemsize=itemsize,
        )
        return tuple(shard) if shard is not None else None
    if ndim == 2:
        shard = compute_shard_shape_2d(
            n_timesteps,
            (chunk_shape[0], chunk_shape[1], chunk_shape[2]),
            itemsize=itemsize,
        )
        return tuple(shard) if shard is not None else None
    return None


def _fill_value_for_dtype(dtype: np.dtype) -> object | None:
    """Return the CF _FillValue used for a float/int array dtype."""
    if np.issubdtype(dtype, np.floating):
        return float(np.nan)
    if np.issubdtype(dtype, np.integer):
        return int(np.iinfo(dtype).min)
    return None


def attach_field_attrs(target: zarr.Group, variable: str) -> None:
    """Stamp the registry-derived CF attrs onto an existing field array."""
    name = field_name_from_target(target, variable)
    if not name:
        # Spatial budget components (drn, rcha, wel, sto-ss, ...) are not in the
        # field registry because their names are dynamic, but they are all
        # volumetric fluxes in m3/s (the extractor scales them to SI seconds).
        if (target.path or "").rsplit("/", 1)[-1] == "budget":
            arr = target[variable]
            attrs: dict[str, object] = {
                "units": "m3 s-1",
                "long_name": f"{variable} volumetric flux",
            }
            fill = _fill_value_for_dtype(np.dtype(arr.dtype))
            # Same rule as attrs_for_field: a NaN sentinel stays out of JSON.
            if fill is not None and not isinstance(fill, float):
                attrs["_FillValue"] = fill
                attrs["missing_value"] = fill
            update_attrs(arr, attrs)
        return
    arr = target[variable]
    update_attrs(arr, attrs_for_field(name, np.dtype(arr.dtype)))


def _write_array(
    store_obj: SimulationZarr,
    parent: zarr.Group,
    name: str,
    data: np.ndarray,
    *,
    dimension_names: tuple[str, ...],
    attrs: dict[str, object] | None = None,
    compressors: Any | None = None,
) -> zarr.Array:
    """Pre-create the child dir, write an array, and stamp ``attrs``.

    ``dimension_names`` is required, not optional: an array whose axes have no
    name cannot be opened by xarray and cannot be joined to anything. A 0-d
    array passes an empty tuple, which Zarr stores as no names at all.
    """
    ensure_child_dir(store_obj, parent, name)
    kwargs: dict[str, Any] = {
        "data": data,
        "overwrite": True,
        "dimension_names": tuple(dimension_names),
    }
    if compressors is not None:
        kwargs["compressors"] = compressors
    arr = parent.create_array(name, **kwargs)
    if attrs:
        update_attrs(arr, attrs)
    return arr


def _z_interface_dimensions(values: np.ndarray) -> tuple[str, ...]:
    """Return the axes of ``z_interfaces``, which is a column or a map.

    MODFLOW writes the vertical column of one reference cell, Boussinesq writes
    the top and bottom of every cell, and both are legal content of the same
    array name.
    """
    if values.ndim == 1:
        return (field_registry.AXIS_LAYER_INTERFACE,)
    if values.ndim == 2:
        return (field_registry.AXIS_LAYER_INTERFACE, field_registry.AXIS_FACE)
    raise ValueError(f"z_interfaces has 1 or 2 axes, got shape {values.shape}")


_Z_INTERFACE_ATTRS: dict[str, object] = {
    "long_name": "Altitude of layer interfaces",
    "units": "m",
    "standard_name": "altitude",
    "positive": "up",
}


# -- Mesh ---------------------------------------------------------------------


def write_mesh(
    store_obj: SimulationZarr,
    vertices: np.ndarray,
    face_node_connectivity: np.ndarray,
    z_interfaces: np.ndarray,
    layer_indices: np.ndarray | None = None,
    source_cell_indices: np.ndarray | None = None,
    topography: np.ndarray | None = None,
    *,
    topography_reference: np.ndarray | None = None,
    layer_thickness: np.ndarray | None = None,
    streambed_top: np.ndarray | None = None,
    streambed_connection: np.ndarray | None = None,
    start_index: int = 0,
    grid_type: str | None = None,
    structured_shape: tuple[int, int] | None = None,
) -> None:
    """Write the UGRID-1.0 mesh group, including the optional topography array.

    ``topography_reference`` (the pre-conditioning per-face top) is stored beside
    ``topography`` so the conditioning-impact map can render their difference.

    ``layer_thickness`` is the ``(n_layers, n_faces)`` saturated-thickness
    geometry of the model. ``z_interfaces`` only carries the vertical column of
    one reference cell, which is enough for metadata but not for a cross-section:
    the per-face thickness is what lets any figure rebuild the aquifer base
    under each cell.
    """
    with store_obj._guard_write():
        mesh = store_obj._root.require_group("mesh")
        _write_array(
            store_obj,
            mesh,
            "vertices",
            np.asarray(vertices, dtype="float64"),
            dimension_names=(field_registry.AXIS_NODE, field_registry.AXIS_NODE_COORDINATE),
            attrs={
                "long_name": "Mesh node coordinates (x, y, z)",
                "units": "m",
                "cf_role": "mesh_node_coordinates",
            },
        )
        _write_array(
            store_obj,
            mesh,
            "face_node_connectivity",
            np.asarray(face_node_connectivity, dtype="int32"),
            dimension_names=(field_registry.AXIS_FACE, field_registry.AXIS_MAX_FACE_NODES),
            attrs={
                "cf_role": "face_node_connectivity",
                "long_name": "Mapping from every face to its corner nodes",
                "start_index": int(start_index),
            },
        )
        interfaces = np.asarray(z_interfaces, dtype="float64")
        _write_array(
            store_obj,
            mesh,
            "z_interfaces",
            interfaces,
            dimension_names=_z_interface_dimensions(interfaces),
            attrs=_Z_INTERFACE_ATTRS,
        )
        if layer_indices is not None:
            _write_array(
                store_obj,
                mesh,
                "layer_indices",
                np.asarray(layer_indices, dtype="int32"),
                dimension_names=(field_registry.AXIS_FACE,),
            )
        if source_cell_indices is not None:
            _write_array(
                store_obj,
                mesh,
                "source_cell_indices",
                np.asarray(source_cell_indices, dtype="int32"),
                dimension_names=(field_registry.AXIS_FACE,),
            )
        if topography is not None:
            topo_arr = _write_array(
                store_obj,
                mesh,
                "topography",
                np.asarray(topography, dtype="float64"),
                dimension_names=(field_registry.AXIS_FACE,),
            )
            update_attrs(topo_arr, attrs_for_field("topography", topo_arr.dtype))
        if topography_reference is not None:
            _write_array(
                store_obj,
                mesh,
                "topography_reference",
                np.asarray(topography_reference, dtype="float64"),
                dimension_names=(field_registry.AXIS_FACE,),
                attrs={
                    "long_name": "Pre-conditioning model top per face",
                    "units": "m",
                },
            )
        for name, values in (
            ("streambed_top", streambed_top),
            ("streambed_connection", streambed_connection),
        ):
            if values is None:
                continue
            arr = _write_array(
                store_obj,
                mesh,
                name,
                np.asarray(values, dtype="float64"),
                dimension_names=(field_registry.AXIS_FACE,),
            )
            update_attrs(arr, attrs_for_field(name, arr.dtype))
        if layer_thickness is not None:
            thickness_arr = _write_array(
                store_obj,
                mesh,
                "layer_thickness",
                np.atleast_2d(np.asarray(layer_thickness, dtype="float64")),
                dimension_names=field_registry.static_field_dimensions(2),
            )
            update_attrs(thickness_arr, attrs_for_field("layer_thickness", thickness_arr.dtype))

        mesh_attrs: dict[str, object] = {
            "start_index": int(start_index),
            "n_nodes": int(np.asarray(vertices).shape[0]),
            "n_cells": int(np.asarray(face_node_connectivity).shape[0]),
            "n_layers": int(len(z_interfaces) - 1),
        }
        if grid_type:
            mesh_attrs["grid_type"] = str(grid_type)
        if structured_shape is not None:
            mesh_attrs["structured_shape"] = [
                int(structured_shape[0]),
                int(structured_shape[1]),
            ]
        update_attrs(mesh, mesh_attrs)

        # UGRID-1.0 topology scalar variable carrying the topology attrs.
        _write_array(
            store_obj,
            mesh,
            "topology",
            np.zeros((), dtype="int32"),
            dimension_names=(),
            attrs={
                "cf_role": "mesh_topology",
                "long_name": "UGRID 2D topology of the simulation mesh",
                "topology_dimension": 2,
                "node_coordinates": "vertices",
                "face_node_connectivity": "face_node_connectivity",
            },
        )


def write_topography(
    store_obj: SimulationZarr,
    topography: np.ndarray,
    *,
    z_interfaces: np.ndarray | None = None,
    n_cells: int | None = None,
    n_layers: int | None = None,
) -> None:
    """Write the mesh topography (and optional z_interfaces) only."""
    with store_obj._guard_write():
        mesh = store_obj._root.require_group("mesh")
        topo_arr = _write_array(
            store_obj,
            mesh,
            "topography",
            np.asarray(topography, dtype="float64"),
            dimension_names=(field_registry.AXIS_FACE,),
        )
        update_attrs(topo_arr, attrs_for_field("topography", topo_arr.dtype))
        if z_interfaces is not None:
            interfaces = np.asarray(z_interfaces, dtype="float64")
            _write_array(
                store_obj,
                mesh,
                "z_interfaces",
                interfaces,
                dimension_names=_z_interface_dimensions(interfaces),
                attrs=_Z_INTERFACE_ATTRS,
            )
        mesh_attrs: dict[str, object] = {}
        if n_cells is not None:
            mesh_attrs["n_cells"] = int(n_cells)
        if n_layers is not None:
            mesh_attrs["n_layers"] = int(n_layers)
        if mesh_attrs:
            update_attrs(mesh, mesh_attrs)


# -- Time / CRS --------------------------------------------------------------


def write_time(
    store_obj: SimulationZarr,
    values: np.ndarray,
    *,
    epoch: str = "1970-01-01T00:00:00",
    calendar: str = "proleptic_gregorian",
    units: str = "seconds since 1970-01-01T00:00:00",
) -> None:
    """Persist the CF time coordinate.

    Only the 1970-01-01 CF epoch is accepted: ``read_time`` decodes any unit
    scale (seconds/minutes/hours/days since 1970) but cannot honor another epoch,
    so a non-1970 anchor is rejected here rather than producing a store that
    write-validates then fails every read.
    """
    if "1970-01-01" not in epoch or "since 1970-01-01" not in units:
        raise ValueError(
            "write_time only supports the 1970-01-01 CF epoch "
            f"(read_time cannot decode another epoch): got epoch={epoch!r}, units={units!r}."
        )
    with store_obj._guard_write():
        _write_array(
            store_obj,
            store_obj._root,
            "time",
            np.asarray(values, dtype="int64"),
            dimension_names=(field_registry.AXIS_TIME,),
            attrs={
                "units": units,
                "calendar": calendar,
                "standard_name": "time",
                "long_name": "Simulation time",
                "axis": "T",
            },
        )
        store_obj._root = update_attrs(store_obj._root, {"time_epoch": epoch})


def write_crs(
    store_obj: SimulationZarr,
    *,
    crs_wkt: str,
    grid_mapping_name: str = "latitude_longitude",
    epsg_code: int | None = None,
    semi_major_axis: float | None = None,
    inverse_flattening: float | None = None,
) -> None:
    """Persist the CF grid-mapping CRS variable."""
    with store_obj._guard_write():
        attrs: dict[str, object] = {"grid_mapping_name": grid_mapping_name}
        if crs_wkt:
            attrs["crs_wkt"] = crs_wkt
        if epsg_code is not None:
            attrs["epsg_code"] = int(epsg_code)
        if semi_major_axis is not None:
            attrs["semi_major_axis"] = float(semi_major_axis)
        if inverse_flattening is not None:
            attrs["inverse_flattening"] = float(inverse_flattening)
        _write_array(
            store_obj,
            store_obj._root,
            "crs",
            np.zeros((), dtype="int32"),
            dimension_names=(),
            attrs=attrs,
        )


# -- Fields ------------------------------------------------------------------


def _field_target(store_obj: SimulationZarr, subgroup: str | None) -> zarr.Group:
    """Return the group holding field arrays, creating ``subgroup`` if needed."""
    if not subgroup:
        return store_obj._root
    if subgroup not in store_obj._root:
        ensure_child_dir(store_obj, store_obj._root, subgroup)
        store_obj._root.create_group(subgroup)
    return store_obj._root[subgroup]


def _create_field_array(
    store_obj: SimulationZarr,
    target: zarr.Group,
    variable: str,
    *,
    n_timesteps: int,
    per_step_shape: tuple[int, ...],
    dtype: np.dtype,
) -> None:
    """Create the (time, ...) array for ``variable`` with balanced chunks/shards."""
    itemsize = int(np.dtype(dtype).itemsize)
    if len(per_step_shape) == 1:
        n_layers, n_cells = 1, int(per_step_shape[0])
        full_shape: tuple[int, ...] = (int(n_timesteps), n_cells)
        if store_obj._balanced:
            chunk_shape: tuple[int, ...] = compute_balanced_chunks_1d(
                int(n_timesteps), n_cells, itemsize
            )
        else:
            chunk_shape = (1, n_cells)
    elif len(per_step_shape) == 2:
        n_layers, n_cells = int(per_step_shape[0]), int(per_step_shape[1])
        full_shape = (int(n_timesteps), n_layers, n_cells)
        if store_obj._balanced:
            chunk_shape = compute_balanced_chunks_2d(int(n_timesteps), n_layers, n_cells, itemsize)
        else:
            chunk_shape = (1, n_layers, n_cells)
    else:
        raise ValueError(f"Expected 1D or 2D per-step values, got shape {per_step_shape}")

    ensure_child_dir(store_obj, target, variable)
    shards = maybe_shards(
        len(per_step_shape),
        int(n_timesteps),
        chunk_shape,
        itemsize,
        n_layers=n_layers,
        n_cells=n_cells,
    )
    create_kwargs: dict[str, Any] = dict(
        shape=full_shape,
        chunks=chunk_shape,
        dtype=dtype,
        dimension_names=field_registry.timed_field_dimensions(len(full_shape)),
        compressors=BLOSC_ZSTD,
        # Derive the fill from the dtype so the array fill and the CF _FillValue
        # attr agree: NaN for floats, iinfo(dtype).min for ints (NaN is invalid
        # for an integer array).
        fill_value=_fill_value_for_dtype(dtype),
        overwrite=True,
    )
    if shards is not None:
        try:
            target.create_array(variable, shards=shards, **create_kwargs)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "ShardingCodec unavailable for %s (shape=%s, "
                "shard=%s): %s. Falling back to plain chunks.",
                variable,
                full_shape,
                shards,
                exc,
            )
            target.create_array(variable, **create_kwargs)
    else:
        target.create_array(variable, **create_kwargs)
    attach_field_attrs(target, variable)


def write_field(
    store_obj: SimulationZarr,
    variable: str,
    timestep: int,
    values: np.ndarray,
    *,
    n_timesteps: int | None = None,
    subgroup: str | None = None,
) -> None:
    """Append one timestep slice to ``variable`` under ``subgroup`` or root."""
    with store_obj._guard_write():
        target = _field_target(store_obj, subgroup)
        values = mask_sentinels(np.asarray(values))
        if values.ndim not in (1, 2):
            raise ValueError(f"Expected 1D or 2D values, got shape {values.shape}")

        if variable not in target:
            if n_timesteps is None:
                raise ValueError(f"n_timesteps required on first write of '{variable}'")
            _create_field_array(
                store_obj,
                target,
                variable,
                n_timesteps=int(n_timesteps),
                per_step_shape=tuple(int(s) for s in values.shape),
                dtype=values.dtype,
            )

        arr = target[variable]
        if values.ndim == 1:
            arr[int(timestep), :] = values
        else:
            arr[int(timestep), :, :] = values


def write_static_field(
    store_obj: SimulationZarr,
    variable: str,
    values: np.ndarray,
    *,
    subgroup: str | None = None,
) -> None:
    """Write a field that has no time axis, such as a model input parameter.

    ``write_field`` and ``write_field_stack`` both open the array with a
    leading time dimension. A conductivity field has one value per cell for
    the whole run, so storing it with a time axis would repeat it at every
    step and make every reader slice a dimension that carries no information.
    """
    with store_obj._guard_write():
        target = _field_target(store_obj, subgroup)
        data = mask_sentinels(np.asarray(values))
        arr = _write_array(
            store_obj,
            target,
            variable,
            data,
            dimension_names=field_registry.static_field_dimensions(data.ndim),
        )
        update_attrs(arr, attrs_for_field(variable, arr.dtype))


def write_field_stack(
    store_obj: SimulationZarr,
    variable: str,
    values: np.ndarray,
    *,
    n_timesteps: int | None = None,
    timestep_offset: int = 0,
    subgroup: str | None = None,
) -> None:
    """Write a ``(time, ...)`` stack of ``variable`` in one batched call.

    Batched writes encode each chunk/shard once. Per-timestep writes into a
    sharded array trigger one read-modify-write of a whole multi-MB shard per
    timestep, which dominated long transient extractions. Use
    ``timestep_offset`` with a total ``n_timesteps`` to stream large arrays in
    time slabs without holding the full stack in memory.
    """
    with store_obj._guard_write():
        target = _field_target(store_obj, subgroup)
        values = mask_sentinels(np.asarray(values))
        if values.ndim not in (2, 3):
            raise ValueError(f"Expected a (time, ...) stack, got shape {values.shape}")

        offset = int(timestep_offset)
        total = int(n_timesteps) if n_timesteps is not None else offset + int(values.shape[0])
        if offset + int(values.shape[0]) > total:
            raise ValueError(
                f"Stack slab [{offset}:{offset + int(values.shape[0])}] exceeds "
                f"n_timesteps={total} for '{variable}'."
            )

        per_step_shape = tuple(int(s) for s in values.shape[1:])
        full_shape = (total, *per_step_shape)
        existing = target.get(variable)
        if existing is None or tuple(int(s) for s in existing.shape) != full_shape:
            if offset != 0:
                raise ValueError(f"First slab of '{variable}' must start at timestep_offset=0.")
            _create_field_array(
                store_obj,
                target,
                variable,
                n_timesteps=total,
                per_step_shape=per_step_shape,
                dtype=values.dtype,
            )

        arr = target[variable]
        arr[offset : offset + int(values.shape[0])] = values


# -- Forcing -----------------------------------------------------------------


def write_forcing_timeseries(
    store_obj: SimulationZarr,
    variable: str,
    station_id: str,
    timestamps: np.ndarray,
    values: np.ndarray,
    *,
    unit: str = "",
    source: str = "",
) -> None:
    """Persist a per-station forcing timeseries under ``forcing/<var>/<station>``."""
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "forcing")
        forcing = store_obj._root.require_group("forcing")
        ensure_child_dir(store_obj, forcing, variable)
        var_grp = forcing.require_group(variable)
        ensure_child_dir(store_obj, var_grp, station_id)
        sta_grp = var_grp.require_group(station_id)

        ts_bytes = np.asarray(timestamps, dtype="datetime64[ns]").view("int64")
        _write_array(
            store_obj,
            sta_grp,
            "timestamps",
            ts_bytes,
            dimension_names=(field_registry.AXIS_RECORD,),
            attrs={
                "units": "nanoseconds since 1970-01-01T00:00:00",
                "calendar": "proleptic_gregorian",
                "standard_name": "time",
                "long_name": f"Timestamps for {variable}",
                "axis": "T",
            },
        )
        _write_array(
            store_obj,
            sta_grp,
            "values",
            np.asarray(values, dtype="float64"),
            dimension_names=(field_registry.AXIS_RECORD,),
            attrs={
                "units": str(unit),
                "long_name": f"Forcing values for {variable}",
                "source": str(source),
            },
        )
        update_attrs(
            sta_grp,
            {
                "unit": str(unit),
                "source": str(source),
                "n_records": int(len(values)),
            },
        )


def write_forcing_field(
    store_obj: SimulationZarr,
    variable: str,
    data: np.ndarray,
    *,
    unit: str = "",
    source: str = "",
) -> None:
    """Persist a gridded forcing field under ``forcing/<var>``."""
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "forcing")
        forcing = store_obj._root.require_group("forcing")
        _write_array(
            store_obj,
            forcing,
            variable,
            np.asarray(data),
            dimension_names=field_registry.per_array_dimensions(
                variable, int(np.asarray(data).ndim)
            ),
            attrs={"unit": str(unit), "source": str(source)},
            compressors=BLOSC_ZSTD,
        )


# -- Geographic rasters (per-run) -------------------------------------------


def write_geographic_raster(
    store_obj: SimulationZarr,
    name: str,
    data: np.ndarray,
    *,
    transform: tuple[float, ...],
    crs: str,
    nodata: float = -99999.0,
) -> None:
    """Persist a per-run raster under ``geographic/<name>``."""
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "geographic")
        geo = store_obj._root.require_group("geographic")
        _write_array(
            store_obj,
            geo,
            name,
            np.asarray(data),
            dimension_names=field_registry.per_array_dimensions(name, int(np.asarray(data).ndim)),
            attrs={
                "transform": list(transform),
                "crs": str(crs),
                "nodata": float(nodata),
                # CF _FillValue so xarray/rasterio auto-mask the nodata sentinel
                # on load instead of the consumer having to know -99999.
                "_FillValue": float(nodata),
                "shape": list(np.asarray(data).shape),
            },
            compressors=BLOSC_ZSTD,
        )


# -- Lake abacus comparison (per-run) ---------------------------------------


def write_lake_abacus(
    store_obj: SimulationZarr,
    lake_id: str,
    *,
    stage: np.ndarray,
    real_volume: np.ndarray,
    real_sarea: np.ndarray,
    sim_volume: np.ndarray,
    sim_sarea: np.ndarray,
    stage_unit: str = "m",
    volume_unit: str = "m3",
    area_unit: str = "m2",
) -> None:
    """Persist the reference vs simulated abacus under ``lake_abacus/<lake_id>``.

    The four curves are sampled on the single ``stage`` abscissa, so reading
    ``real_volume[i]`` against ``stage[i]`` only means something when the five
    arrays have one length. Writing them unequal produced a group no reader
    could open, and said so nowhere; it is refused here instead.
    """
    curves = (
        ("stage", np.asarray(stage, dtype="float64"), stage_unit),
        ("real_volume", np.asarray(real_volume, dtype="float64"), volume_unit),
        ("real_sarea", np.asarray(real_sarea, dtype="float64"), area_unit),
        ("sim_volume", np.asarray(sim_volume, dtype="float64"), volume_unit),
        ("sim_sarea", np.asarray(sim_sarea, dtype="float64"), area_unit),
    )
    lengths = {name: int(values.shape[0]) for name, values, _ in curves}
    if len(set(lengths.values())) != 1:
        raise ValueError(
            f"Lake abacus curves of '{lake_id}' are sampled on one stage axis but "
            f"have different lengths: {lengths}"
        )
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "lake_abacus")
        grp = store_obj._root.require_group("lake_abacus")
        ensure_child_dir(store_obj, grp, lake_id)
        lake = grp.require_group(lake_id)
        for name, values, unit in curves:
            _write_array(
                store_obj,
                lake,
                name,
                values,
                dimension_names=(field_registry.AXIS_STAGE_LEVEL,),
                attrs={"units": str(unit)},
            )
        update_attrs(
            lake,
            {"stage_unit": stage_unit, "volume_unit": volume_unit, "area_unit": area_unit},
        )


def write_lake_restart_state(store_obj: SimulationZarr, stages: dict[str, float]) -> None:
    """Persist each lake's final stage under ``lake_state_final`` for hotstart.

    The companion of the heads field for ``[flow] restart_from``: a later run
    seeds each lake's initial stage from this last value. ``stages`` maps
    ``lake_id -> stage`` in metres; an empty mapping writes nothing.
    """
    if not stages:
        return
    lake_ids = [str(lake_id) for lake_id in stages]
    values = np.asarray([float(stages[lake_id]) for lake_id in lake_ids], dtype="float64")
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "lake_state_final")
        grp = store_obj._root.require_group("lake_state_final")
        _write_array(
            store_obj,
            grp,
            "stage",
            values,
            dimension_names=(field_registry.AXIS_LAKE,),
            attrs={"units": "m"},
        )
        update_attrs(grp, {"lake_ids": lake_ids})


# -- Axis coordinates --------------------------------------------------------


def _axis_extents(root: zarr.Group) -> dict[str, int]:
    """Return the length of the layer and face axes of a finished store."""
    extents: dict[str, int] = {}
    mesh = root.get("mesh")
    if isinstance(mesh, zarr.Group):
        for key, axis in (
            ("n_cells", field_registry.AXIS_FACE),
            ("n_layers", field_registry.AXIS_LAYER),
        ):
            value = mesh.attrs.get(key)
            if value is not None:
                extents[axis] = int(value)
    for _, array in _walk_arrays(root):
        names = array.metadata.dimension_names or ()
        for axis, length in zip(names, array.shape, strict=False):
            if axis in (field_registry.AXIS_LAYER, field_registry.AXIS_FACE):
                extents.setdefault(axis, int(length))
    return extents


def _walk_arrays(group: zarr.Group, prefix: str = "") -> list[tuple[str, zarr.Array]]:
    """Return every array of ``group``, keyed by its path inside the store."""
    found: list[tuple[str, zarr.Array]] = []
    for name, member in group.members():
        path = f"{prefix}/{name}" if prefix else name
        if isinstance(member, zarr.Array):
            found.append((path, member))
        elif isinstance(member, zarr.Group):
            found.extend(_walk_arrays(member, path))
    return found


def harmonize_axis_references(store_obj: SimulationZarr) -> None:
    """Materialise the axis coordinates the fields name, and drop dangling ones.

    Every field declares ``coordinates = "time layer face"`` and
    ``grid_mapping = "crs"``. Until this runs, ``layer`` and ``face`` are names
    of nothing, and ``crs`` is a name of nothing on a run with no declared CRS:
    a CF attribute pointing at an absent variable is a broken reference, not
    metadata. Writing the two index arrays gives the face and layer axes a
    coordinate a reader can join on; removing an unresolvable ``grid_mapping``
    leaves the store saying only what is true.

    The root ``n_cells`` and ``n_layers`` are refreshed from the same extents.
    They were stamped at registration, before the mesh existed, and a store
    whose root announces ``n_cells = 0`` over a 200-cell mesh describes nothing.
    """
    root = store_obj.root
    extents = _axis_extents(root)
    with store_obj._guard_write():
        sizes = {
            key: extents[axis]
            for key, axis in (
                ("n_cells", field_registry.AXIS_FACE),
                ("n_layers", field_registry.AXIS_LAYER),
            )
            if axis in extents
        }
        if sizes:
            store_obj._root = update_attrs(root, sizes)
            root = store_obj._root
        if field_registry.AXIS_FACE in extents:
            _write_array(
                store_obj,
                root,
                field_registry.AXIS_FACE,
                np.arange(extents[field_registry.AXIS_FACE], dtype="int32"),
                dimension_names=(field_registry.AXIS_FACE,),
                attrs={
                    "long_name": "Index of a cell along the face axis of the fields",
                    "units": "1",
                    "comment": (
                        "Position along the face axis of every field array, and row of "
                        "mesh/face_node_connectivity."
                    ),
                },
            )
        if field_registry.AXIS_LAYER in extents:
            _write_array(
                store_obj,
                root,
                field_registry.AXIS_LAYER,
                np.arange(extents[field_registry.AXIS_LAYER], dtype="int32"),
                dimension_names=(field_registry.AXIS_LAYER,),
                attrs={
                    "long_name": "Model layer index, 0 at the top of the aquifer",
                    "units": "1",
                    "positive": "down",
                },
            )
        present = {path for path, _ in _walk_arrays(root)}
        for _, array in _walk_arrays(root):
            attrs = dict(array.attrs)
            grid_mapping = attrs.get("grid_mapping")
            if grid_mapping and str(grid_mapping) not in present:
                del array.attrs["grid_mapping"]
            declared = str(attrs.get("coordinates", "")).split()
            resolved = [name for name in declared if name in present]
            if resolved != declared:
                if resolved:
                    array.attrs["coordinates"] = " ".join(resolved)
                else:
                    del array.attrs["coordinates"]


# -- ACDD --------------------------------------------------------------------


def write_acdd_root_attrs(
    store_obj: SimulationZarr,
    *,
    sim_row: dict[str, Any] | None,
    runs_env: dict[str, Any] | None,
    project_table: dict[str, Any] | None = None,
    geographic_bounds: dict[str, float] | None = None,
    history_lines: list[str] | None = None,
) -> dict[str, Any]:
    """Compose and persist ACDD root attrs. Returns the attrs written."""
    attrs = compose_acdd_root_attrs(
        sim_row=sim_row,
        runs_env=runs_env,
        project_table=project_table,
        geographic_bounds=geographic_bounds,
        history_lines=history_lines,
    )
    with store_obj._guard_write():
        store_obj._root = update_attrs(store_obj._root, attrs)
        meta = store_obj._root.require_group("meta")
        # ``meta`` stores the same ACDD payload so a downstream tool can
        # discover the metadata even with .zmetadata stripped.
        update_attrs(meta, attrs)
    return attrs


__all__ = [
    "attach_field_attrs",
    "attrs_for_field",
    "ensure_child_dir",
    "field_name_from_target",
    "harmonize_axis_references",
    "maybe_shards",
    "write_acdd_root_attrs",
    "write_crs",
    "write_field",
    "write_forcing_field",
    "write_forcing_timeseries",
    "write_geographic_raster",
    "write_lake_abacus",
    "write_mesh",
    "write_static_field",
    "write_time",
    "write_topography",
]
