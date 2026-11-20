"""Read-side concerns for :class:`SimulationZarr`.

Every ``read_*`` of :class:`SimulationZarr` is defined here once and bound
on the class as a method, so each takes the live store as its first argument.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.budget.flux import DRAIN_BAND_DEPTH_ATTR, drain_band_depth
from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry

if TYPE_CHECKING:
    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

logger = get_logger(__name__)

_DASK_FALLBACK_WARNED = False

CONCENTRATION_FIELD = "concentration"
"""The public name of the solute concentration, whatever its stored form."""


def has_concentration(root: Any) -> bool:
    """Say whether a store root holds a concentration in one of its two forms.

    The stored form of today holds one solute per run, named by its ``spc_name``,
    under ``concentration/<spc_name>``. A store written before that held the array
    at the root of the fields, without a name. Both answer True.
    """
    try:
        concentration_array(root)
    except KeyError:
        return False
    return True


def concentration_array(root: Any) -> Any:
    """Return the stored concentration array of a run, at the path it holds.

    The extractor writes one solute, named by ``spc_name``, under the
    ``concentration`` subgroup, and a store written by a pre-release wrote the array
    straight under ``concentration``. Every reader of the public name goes
    through here, so both forms read the same way, and a group that carries
    more than one solute is refused with their names, because one run holds
    one solute.

    Raises
    ------
    KeyError
        When the store holds no concentration, or several named ones.
    """
    node = root.get(CONCENTRATION_FIELD)
    if node is None:
        raise KeyError("No concentration stored: a concentration field needs a transport run.")
    if hasattr(node, "shape"):
        return node
    species = sorted(key for key in node.keys() if not key.startswith("."))
    if not species:
        raise KeyError("The group 'concentration' of the store holds no solute.")
    if len(species) > 1:
        raise KeyError(
            "The store holds several solutes under concentration ("
            f"{', '.join(species)}) and one run carries one: read concentration/<spc>."
        )
    return node[species[0]]


def stored_field_array(root: Any, zarr_path: str) -> Any:
    """Resolve a registry ``zarr_path`` to its stored array, or ``None`` when absent.

    The concentration goes through :func:`concentration_array`, because its
    path names a group of solutes and not an array. Several solutes under it
    raise the ``KeyError`` that names them.
    """
    if zarr_path == CONCENTRATION_FIELD:
        if root.get(CONCENTRATION_FIELD) is None:
            return None
        return concentration_array(root)
    node = root
    for part in zarr_path.split("/"):
        getter = getattr(node, "get", None)
        node = getter(part) if getter is not None else None
        if node is None:
            return None
    return node


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


def read_field(
    store_obj: SimulationZarr,
    variable: str,
    timestep: int,
    *,
    subgroup: str | None = None,
    layer: int | None = None,
) -> np.ndarray:
    """Read ``variable`` from ``subgroup`` (or auto), sliced at ``timestep``.

    ``timestep`` is ignored for static fields (see :func:`~hydromodpy.results.field_registry.is_time_resolved`).
    A float field comes back as float64 whatever precision it was stored in,
    so a compact store and an exact one hand their readers the same dtype.
    """
    array = _stored_array(store_obj, variable, subgroup)
    data = array[int(timestep)] if field_registry.is_time_resolved(variable) else array[:]
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
    if not field_registry.is_time_resolved(variable):
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


def read_time(store_obj: SimulationZarr) -> np.ndarray | None:
    """Return the CF ``/time`` axis as ``datetime64[ns]``, or ``None``.

    This axis is the single source of truth for the simulation clock: the
    exact stress-period timestamps the solver wrote, shared by every field
    array. Stored as integer offsets since the CF epoch (1970-01-01), so a
    plain numpy cast decodes it without a calendar library.
    """
    root = store_obj._root
    if root is None or "time" not in root:
        return None
    arr = root["time"]
    values = np.asarray(arr[:])
    if values.size == 0:
        return None
    units = str(dict(arr.attrs).get("units", "seconds since 1970-01-01"))
    if "since 1970-01-01" not in units:
        # The decode below assumes the 1970 epoch; a different epoch would
        # silently shift the whole clock (~30 years for a 2000 anchor).
        raise ValueError(
            f"SimulationZarr.read_time: time units {units!r} are not anchored to "
            "'since 1970-01-01'; the clock cannot be decoded without an epoch offset."
        )
    unit_code = "s"
    if units.startswith("days"):
        unit_code = "D"
    elif units.startswith("hours"):
        unit_code = "h"
    elif units.startswith("minutes"):
        unit_code = "m"
    return values.astype(f"datetime64[{unit_code}]").astype("datetime64[ns]")


def _stored_array(store_obj: SimulationZarr, variable: str, subgroup: str | None) -> Any:
    """Return the stored array of ``variable``, from ``subgroup`` or the first group holding it."""
    if subgroup:
        target = store_obj._root[subgroup]
        if variable not in target:
            raise KeyError(f"Variable '{variable}' not found in subgroup '{subgroup}'")
        return target[variable]
    if variable == CONCENTRATION_FIELD and has_concentration(store_obj._root):
        return concentration_array(store_obj._root)
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
        if name == CONCENTRATION_FIELD:
            if not has_concentration(store_obj._root):
                continue
            arr = concentration_array(store_obj._root)
        elif "/" in path:
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
    "CONCENTRATION_FIELD",
    "concentration_array",
    "field_array_view",
    "get_geographic_fingerprint",
    "get_drain_band_depth",
    "has_concentration",
    "read_field",
    "read_field_range",
    "lake_abacus_lakes",
    "read_forcing_timeseries",
    "read_geographic_raster",
    "read_lake_abacus",
    "read_time",
    "set_drain_band_depth",
    "set_geographic_fingerprint",
    "step_range_bounds",
    "stored_field_array",
    "to_xarray",
]
