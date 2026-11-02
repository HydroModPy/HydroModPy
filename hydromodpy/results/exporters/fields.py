"""What every field exporter reads the same way: one step, one layer, the CRS.

A field is read at one step from the store, or rebuilt on read when it was
never persisted. A static field (topography, a conductivity) has no time axis
and reads whole whatever the step. A format that holds one layer takes the
layer asked for, and refuses a field of several layers when none was asked:
the top layer of a multi-layer model can be dry, and a silent layer 0 would
hide it.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.results.derive.virtual_fields import derive_field_slice, field_descriptor
from hydromodpy.results.field_registry import FieldDescriptor

TWO_DIMENSIONAL_FIELDS = ("watertable_elevation", "watertable_depth", "seepage_mask")
"""Fields of one value per cell, whatever the number of layers."""


def is_timed(descriptor: FieldDescriptor) -> bool:
    """Return whether a field carries a time axis."""
    return descriptor.shape.startswith("time")


def resolve_zarr_path(grp: Any, zarr_path: str) -> Any:
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


def read_field_step(handle: Any, sim_id: str, variable: str, timestep: int) -> np.ndarray:
    """Return ``variable`` at ``timestep`` from an open store, rebuilt when not persisted.

    Raises
    ------
    KeyError
        The field is neither stored nor rebuildable from what the store holds.
    """
    descriptor = field_descriptor(variable)
    arr = resolve_zarr_path(handle.root, descriptor.zarr_path)
    if arr is not None:
        return np.asarray(arr[int(timestep)] if is_timed(descriptor) else arr[:])
    data = derive_field_slice(handle, str(sim_id), variable, int(timestep))
    if data is None:
        raise KeyError(
            f"Variable '{variable}' (zarr_path={descriptor.zarr_path!r}) not found for sim={sim_id}"
        )
    return np.asarray(data)


def one_layer(data: np.ndarray, variable: str, layer: int | None, fmt: str) -> np.ndarray:
    """Return the one layer a format holds, refusing to guess on a multi-layer field."""
    values = np.asarray(data)
    if values.ndim == 1:
        return values
    n_layers = int(values.shape[0])
    if layer is None:
        if n_layers == 1:
            return values[0]
        alternatives = ", ".join(TWO_DIMENSIONAL_FIELDS)
        raise ValueError(
            f"{variable!r} holds {n_layers} layers and a {fmt} holds one. Write layer = 0 "
            f"for the top layer (or another), or export a field of one value per cell: "
            f"{alternatives}. NetCDF and VTU keep every layer."
        )
    if not 0 <= int(layer) < n_layers:
        raise ValueError(
            f"layer = {layer} is out of range: {variable!r} holds {n_layers} layer"
            f"{'s' if n_layers > 1 else ''} (0 to {n_layers - 1})."
        )
    return values[int(layer)]


def native_crs(grp: Any) -> str | None:
    """CRS the mesh vertices are expressed in, from the store's CF grid mapping."""
    node = grp.get("crs")
    if node is None:
        return None
    attrs = dict(node.attrs)
    epsg = attrs.get("epsg_code")
    if epsg is not None:
        return f"EPSG:{int(epsg)}"
    wkt = attrs.get("crs_wkt")
    return str(wkt) if wkt else None
