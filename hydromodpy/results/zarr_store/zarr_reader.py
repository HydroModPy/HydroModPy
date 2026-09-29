"""Read-side concerns for :class:`SimulationZarr`.

Owns every ``read_*`` entry point plus the root-attribute readers
(``geographic_fingerprint``, ``resolve_geographic_dir``,
``root_attrs_json``) and the :func:`to_xarray` view builder.

All helpers take the live :class:`SimulationZarr` so the module is
free of hidden state.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.field_routing import DRAIN_BAND_DEPTH_ATTR, drain_band_depth
from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry

if TYPE_CHECKING:
    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

logger = get_logger(__name__)

_DASK_FALLBACK_WARNED = False


def _optional_dask_array():
    """Return ``dask.array`` when installed, otherwise ``None``.

    Warns once when dask is absent: the xarray/field views then load eagerly
    (full ``np.asarray``), which can OOM on a large multi-year store.
    """
    global _DASK_FALLBACK_WARNED
    try:
        import dask.array as da
    except ModuleNotFoundError as exc:
        if exc.name != "dask":
            raise
        if not _DASK_FALLBACK_WARNED:
            logger.warning(
                "dask is not installed: field/xarray views load eagerly into RAM "
                "and can OOM on large stores. Install dask for lazy access."
            )
            _DASK_FALLBACK_WARNED = True
        return None
    return da


def field_array_view(arr: Any, da: Any | None) -> Any:
    """Return a stored array as numpy (``da`` None) or lazy dask, floats in float64.

    A compact store keeps its fields in float32. The cast is lazy under dask
    and exact, so a reader gets the dtype an exact store would give it.
    """
    if da is None:
        values = np.asarray(arr)
    else:
        values = da.from_array(arr, chunks=arr.chunks if arr.chunks else "auto")
    if np.issubdtype(values.dtype, np.floating) and values.dtype != np.float64:
        values = values.astype(np.float64)
    return values


def get_geographic_fingerprint(store_obj: SimulationZarr) -> str | None:
    """Return the persisted geographic fingerprint, if any."""
    value = store_obj._root.attrs.get("geographic_fingerprint")
    return str(value) if value else None


def set_geographic_fingerprint(store_obj: SimulationZarr, value: str | None) -> None:
    """Set or clear the geographic fingerprint root attribute."""
    if value is None:
        if "geographic_fingerprint" in store_obj._root.attrs:
            del store_obj._root.attrs["geographic_fingerprint"]
    else:
        store_obj._root.attrs["geographic_fingerprint"] = str(value)


def get_drain_band_depth(store_obj: SimulationZarr) -> float:
    """Return the sub-cell discharge band the run gave its drains, 0.0 if none."""
    return drain_band_depth(store_obj._root)


def set_drain_band_depth(store_obj: SimulationZarr, value: float) -> None:
    """Persist the discharge band so a reader can rebuild the seepage criterion.

    Cleared when it is not strictly positive, so an unbanded run leaves no
    attribute and reads exactly like every run written before the option.
    """
    depth = float(value)
    if not math.isfinite(depth) or depth <= 0.0:
        if DRAIN_BAND_DEPTH_ATTR in store_obj._root.attrs:
            del store_obj._root.attrs[DRAIN_BAND_DEPTH_ATTR]
        return
    store_obj._root.attrs[DRAIN_BAND_DEPTH_ATTR] = depth


def resolve_geographic_dir(store_obj: SimulationZarr, workspace_path: Path | str) -> Path | None:
    """Resolve the workspace-level cache dir tied to this store's fingerprint."""
    fp = get_geographic_fingerprint(store_obj)
    if fp is None:
        return None
    from hydromodpy.results.geographic_cache import GeographicCache

    return GeographicCache(workspace_path).path_for(fp)


def _is_time_resolved(variable: str) -> bool:
    """Return True when the registered field carries a leading time axis.

    Static geometry (``topography``, ``layer_thickness``) has no time
    dimension, so indexing it by timestep would silently return one layer or
    raise. Unregistered variables are assumed time-resolved, which is the
    historical behaviour for solver-specific arrays.
    """
    from hydromodpy.results import field_registry

    if not field_registry.has(variable):
        return True
    return field_registry.get(variable).shape.startswith("time")


def read_field(
    store_obj: SimulationZarr,
    variable: str,
    timestep: int,
    *,
    subgroup: str | None = None,
    layer: int | None = None,
) -> np.ndarray:
    """Read ``variable`` from ``subgroup`` (or auto), sliced at ``timestep``.

    ``timestep`` is ignored for static fields (see :func:`_is_time_resolved`).
    A float field comes back as float64 whatever precision it was stored in,
    so a compact store and an exact one hand their readers the same dtype.
    """
    array = _stored_array(store_obj, variable, subgroup)
    data = array[int(timestep)] if _is_time_resolved(variable) else array[:]
    if layer is not None and data.ndim == 2:
        data = data[layer]
    return _as_float64(data)


def read_field_range(
    store_obj: SimulationZarr,
    variable: str,
    start: int,
    stop: int,
    *,
    subgroup: str | None = None,
    layer: int | None = None,
) -> np.ndarray:
    """Read ``variable`` over timesteps ``[start, stop)`` as one stack.

    Row ``i`` is what :func:`read_field` returns at step ``start + i``: the
    same lookup, the same layer selection, floats in float64. The slice is
    read in one call, so each chunk is decoded once for the whole range. A
    static field is repeated once per step, as a step-by-step read gives it.
    Negative bounds count from the end of the time axis. A range that leaves
    the axis raises ``IndexError``, as a step outside it does.
    """
    array = _stored_array(store_obj, variable, subgroup)
    if not _is_time_resolved(variable):
        row = read_field(store_obj, variable, 0, subgroup=subgroup, layer=layer)
        return np.repeat(row[None], len(range(int(start), int(stop))), axis=0)
    first, last = step_range_bounds(start, stop, int(array.shape[0]))
    data = array[first:last]
    if layer is not None and data.ndim == 3:
        data = data[:, layer]
    return _as_float64(data)


def step_range_bounds(start: int, stop: int, n_steps: int) -> tuple[int, int]:
    """Return ``[start, stop)`` on a time axis of ``n_steps``, negatives from the end.

    Raises ``IndexError`` when the range leaves the axis or runs backwards,
    where a slice would silently return fewer rows than asked.
    """
    first = int(start) + n_steps if int(start) < 0 else int(start)
    last = int(stop) + n_steps if int(stop) < 0 else int(stop)
    if not 0 <= first <= last <= n_steps:
        raise IndexError(
            f"timesteps [{start}, {stop}) out of bounds for a time axis of length {n_steps}"
        )
    return first, last


def _stored_array(store_obj: SimulationZarr, variable: str, subgroup: str | None) -> Any:
    """Return the stored array of ``variable``, from ``subgroup`` or the first group holding it."""
    if subgroup:
        target = store_obj._root[subgroup]
        if variable not in target:
            raise KeyError(f"Variable '{variable}' not found in subgroup '{subgroup}'")
        return target[variable]
    for loc_name in (None, "state", "derived", "budget", "mesh"):
        loc = store_obj._root if loc_name is None else store_obj._root.get(loc_name)
        if loc is not None and variable in loc:
            return loc[variable]
    raise KeyError(f"Variable '{variable}' not found")


def _as_float64(data: np.ndarray) -> np.ndarray:
    """Return ``data`` with a float dtype widened to float64, exactly."""
    if np.issubdtype(data.dtype, np.floating) and data.dtype != np.float64:
        return data.astype(np.float64)
    return data


def read_forcing_timeseries(
    store_obj: SimulationZarr,
    variable: str,
    station_id: str,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Read a per-station forcing timeseries plus its attribute dict."""
    forcing = store_obj._root.get("forcing")
    if forcing is None:
        raise KeyError("No forcing group")
    var_grp = forcing.get(variable)
    if var_grp is None:
        raise KeyError(f"No forcing variable '{variable}'")
    sta_grp = var_grp.get(station_id)
    if sta_grp is None:
        raise KeyError(f"No forcing station '{station_id}' for '{variable}'")
    ts_int = np.asarray(sta_grp["timestamps"][:], dtype="int64")
    timestamps = ts_int.view("datetime64[ns]")
    values = np.asarray(sta_grp["values"][:], dtype="float64")
    attrs = dict(sta_grp.attrs)
    return timestamps, values, attrs


def read_lake_abacus(store_obj: SimulationZarr, lake_id: str) -> dict:
    """Read the reference vs simulated abacus arrays for one lake."""
    grp = store_obj._root.get("lake_abacus")
    if grp is None or lake_id not in grp:
        raise KeyError(f"Lake abacus '{lake_id}' not found")
    lake = grp[lake_id]
    out: dict = {
        name: np.asarray(lake[name][:], dtype="float64")
        for name in ("stage", "real_volume", "real_sarea", "sim_volume", "sim_sarea")
    }
    out.update(dict(lake.attrs))
    return out


def lake_abacus_lakes(store_obj: SimulationZarr) -> list[str]:
    """Return the lake ids with a persisted abacus comparison."""
    grp = store_obj._root.get("lake_abacus")
    return [] if grp is None else sorted(grp.keys())


def read_geographic_raster(store_obj: SimulationZarr, name: str) -> tuple[np.ndarray, dict]:
    """Read a per-run geographic raster and its georeferencing metadata."""
    geo = store_obj._root.get("geographic")
    if geo is None or name not in geo:
        raise KeyError(f"Geographic raster '{name}' not found")
    arr = geo[name]
    data = np.asarray(arr[:])
    meta = {
        "transform": tuple(arr.attrs.get("transform", ())),
        "crs": arr.attrs.get("crs", ""),
        "nodata": arr.attrs.get("nodata", -99999.0),
        "shape": tuple(arr.attrs.get("shape", ())),
    }
    return data, meta


def is_consolidated(store_obj: SimulationZarr) -> bool:
    """Return True when ``.zmetadata`` consolidation is detectable on disk."""
    path = store_obj._path
    if path.is_dir():
        return (path / ".zmetadata").exists() or (path / "zarr.json").exists()
    return False


def root_attrs_json(store_obj: SimulationZarr) -> str:
    """Return the root attributes as a JSON string for debug / logs."""
    return json.dumps({k: v for k, v in store_obj._root.attrs.items()}, default=str)


def to_xarray(store_obj: SimulationZarr):
    """Return an ``xarray.Dataset`` view over the simulation fields."""
    import xarray as xr

    da = _optional_dask_array()
    data_vars: dict[str, xr.Variable] = {}
    coords: dict[str, xr.Variable] = {}

    def _shape_dims(shape: str) -> tuple[str, ...]:
        return {
            field_registry.SHAPE_TIME_LAYER_FACE: ("time", "layer", "face"),
            field_registry.SHAPE_TIME_FACE: ("time", "face"),
            field_registry.SHAPE_LAYER_FACE: ("layer", "face"),
            field_registry.SHAPE_FACE: ("face",),
            field_registry.SHAPE_PARTICLES: ("time", "particle"),
        }.get(shape, ())

    for name, desc in field_registry.FIELD_REGISTRY.items():
        path = desc.zarr_path
        if "/" in path:
            group_name, var_name = path.split("/", 1)
            group = store_obj._root.get(group_name)
            if group is None or var_name not in group:
                continue
            arr = group[var_name]
        else:
            if path not in store_obj._root:
                continue
            arr = store_obj._root[path]
        dims = _shape_dims(desc.shape)
        if len(dims) != arr.ndim:
            dims = tuple(f"dim_{i}" for i in range(arr.ndim))
        values = field_array_view(arr, da)
        data_vars[name] = xr.Variable(
            dims,
            values,
            attrs=dict(arr.attrs),
        )

    if "time" in store_obj._root:
        time_arr = store_obj._root["time"]
        coords["time"] = xr.Variable(
            ("time",),
            np.asarray(time_arr[:]),
            attrs=dict(time_arr.attrs),
        )
    if "crs" in store_obj._root:
        crs_arr = store_obj._root["crs"]
        coords["crs"] = xr.Variable(
            (),
            np.asarray(crs_arr[()]),
            attrs=dict(crs_arr.attrs),
        )

    root_attrs = {k: v for k, v in store_obj._root.attrs.items()}
    return xr.Dataset(data_vars=data_vars, coords=coords, attrs=root_attrs)


__all__ = [
    "field_array_view",
    "get_geographic_fingerprint",
    "is_consolidated",
    "read_field",
    "read_field_range",
    "lake_abacus_lakes",
    "read_forcing_timeseries",
    "read_geographic_raster",
    "read_lake_abacus",
    "resolve_geographic_dir",
    "get_drain_band_depth",
    "root_attrs_json",
    "set_drain_band_depth",
    "set_geographic_fingerprint",
    "step_range_bounds",
    "to_xarray",
]
