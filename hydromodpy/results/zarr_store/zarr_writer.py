"""Write-side concerns for :class:`SimulationZarr`.

Every ``write_*`` of :class:`SimulationZarr` is defined here once and bound
on the class as a method: mesh, time, CRS, fields, forcing, geographic
rasters and ACDD root attrs. Each takes the live store as its first argument.
The module also owns the chunk and shard decisions and the CF attributes
that flow from the registry.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

import numpy as np
import zarr

from hydromodpy.core.budget.terms import (
    BUDGET_KEPT_TERMS_ATTR,
    BUDGET_POLICY_ATTR,
    POLICY_ALL,
    BudgetKeep,
)
from hydromodpy.core.fields.nodata import SENTINEL_ABS_THRESHOLD
from hydromodpy.core.fields.precision import (
    KEPT_MANTISSA_BITS,
    QUANTIZATION_ALGORITHM,
    to_storage_precision,
)
from hydromodpy.core.io.value_digest import value_digest
from hydromodpy.core.logging import get_logger
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
from hydromodpy.results.zarr_store.geometry_writer import (
    attrs_for_field,
    ensure_child_dir,
    write_array,
)
from hydromodpy.results.zarr_store.zarr_schema import update_attrs

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
    # and a materialized absolute copy would double the write-side peak.
    sentinel = (values > SENTINEL_ABS_THRESHOLD) | (values < -SENTINEL_ABS_THRESHOLD)
    if not sentinel.any():
        return values
    cleaned = values.copy()
    cleaned[sentinel] = np.nan
    return cleaned


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


# -- Mesh ---------------------------------------------------------------------


# -- Time / CRS --------------------------------------------------------------


# -- Fields ------------------------------------------------------------------

QUANTIZATION_VARIABLE = "quantization_info"
"""Root container variable that describes the rounding of compact fields (CF-1.11 8.4)."""


def _stamp_quantization(store_obj: SimulationZarr, array: zarr.Array) -> None:
    """Say on ``array`` that it holds rounded values, and how they were rounded.

    CF-1.11 section 8.4 names the attributes: ``quantization`` points at a
    container variable carrying the algorithm, and ``quantization_nsb`` gives
    the mantissa bits kept. A reader can then tell a compact field from an
    exact one without comparing it to anything.
    """
    root = store_obj._root
    if QUANTIZATION_VARIABLE not in root:
        write_array(
            store_obj,
            root,
            QUANTIZATION_VARIABLE,
            np.zeros((), dtype="int32"),
            dimension_names=(),
            attrs={
                "algorithm": QUANTIZATION_ALGORITHM,
                "implementation": (
                    "hydromodpy.core.field_precision.round_mantissa: round to nearest, "
                    "ties to even, from float64, then an exact cast to float32"
                ),
            },
        )
    update_attrs(
        array,
        {"quantization": QUANTIZATION_VARIABLE, "quantization_nsb": KEPT_MANTISSA_BITS},
    )


def _field_dimensions(
    variable: str, ndim: int, fallback: Callable[[int], tuple[str, ...]]
) -> tuple[str, ...]:
    """Return the axis names of ``variable``, the registry ones when they fit its rank."""
    if field_registry.has(variable):
        dimensions = field_registry.get(variable).dimensions
        if len(dimensions) == ndim:
            return dimensions
    return fallback(ndim)


def _field_path(variable: str, subgroup: str | None) -> str:
    """Return the path of the array inside the store, the key of its value digests."""
    return variable if not subgroup else f"{subgroup.strip('/')}/{variable}"


def _digest_registry(store_obj: SimulationZarr) -> dict[str, dict[str, str]]:
    """Return the registry of value digests of a handle, attached on first use.

    A run hands the registry of its facts to the handle, so the digests
    survive the close and a resume. A handle opened alone keeps its own.
    """
    registry = getattr(store_obj, "field_digests", None)
    if registry is None:
        registry = {}
        store_obj.field_digests = registry
    return registry


def _record_step_digests(
    store_obj: SimulationZarr, path: str, first_step: int, values: np.ndarray, *, stack: bool
) -> None:
    """Keep the digest of the float64 values received, one per step, before any rounding.

    The registry lives in the facts of the run, so it survives a resume that
    does not read the extraction again. A step never written is folded from
    the store at the seal.
    """
    digests = _digest_registry(store_obj).setdefault(path, {})
    if stack:
        for index in range(int(values.shape[0])):
            digests[str(first_step + index)] = value_digest(values[index])
    else:
        digests[str(first_step)] = value_digest(values)


def _to_stored_field(
    store_obj: SimulationZarr,
    values: np.ndarray,
    *,
    path: str,
    first_step: int = 0,
    stack: bool = False,
) -> tuple[np.ndarray, bool]:
    """Mask sentinels, digest the float64 values a rounded field rounds, then cast.

    The digest is taken here because this is the one place the masked values
    exist before ``to_storage_precision``: a rounded array hashes what the run
    computed, not the rounded bytes a replay cannot reproduce on another
    processor.
    """
    cleaned = mask_sentinels(np.asarray(values))
    stored = to_storage_precision(cleaned, store_obj.field_precision)
    quantized = stored is not cleaned
    if quantized:
        _record_step_digests(store_obj, path, first_step, cleaned, stack=stack)
    return stored, quantized


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
    quantized: bool = False,
) -> None:
    """Create the (time, ...) array for ``variable`` with balanced chunks/shards."""
    itemsize = int(np.dtype(dtype).itemsize)
    if len(per_step_shape) == 1:
        n_layers, n_cells = 1, int(per_step_shape[0])
        full_shape: tuple[int, ...] = (int(n_timesteps), n_cells)
        chunk_shape: tuple[int, ...] = compute_balanced_chunks_1d(
            int(n_timesteps), n_cells, itemsize
        )
    elif len(per_step_shape) == 2:
        n_layers, n_cells = int(per_step_shape[0]), int(per_step_shape[1])
        full_shape = (int(n_timesteps), n_layers, n_cells)
        chunk_shape = compute_balanced_chunks_2d(int(n_timesteps), n_layers, n_cells, itemsize)
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
        dimension_names=_field_dimensions(
            variable, len(full_shape), field_registry.timed_field_dimensions
        ),
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
    if quantized:
        _stamp_quantization(store_obj, target[variable])


def write_field(
    store_obj: SimulationZarr,
    variable: str,
    timestep: int,
    values: np.ndarray,
    *,
    n_timesteps: int | None = None,
    subgroup: str | None = None,
) -> None:
    """Append one timestep slice to ``variable`` under ``subgroup`` or root.

    The values are written in the handle's ``field_precision``.
    """
    if np.ndim(values) not in (1, 2):
        raise ValueError(f"Expected 1D or 2D values, got shape {np.shape(values)}")
    with store_obj._guard_write():
        target = _field_target(store_obj, subgroup)
        values, quantized = _to_stored_field(
            store_obj,
            values,
            path=_field_path(variable, subgroup),
            first_step=int(timestep),
        )
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
                quantized=quantized,
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
        arr = write_array(
            store_obj,
            target,
            variable,
            data,
            dimension_names=_field_dimensions(
                variable, data.ndim, field_registry.static_field_dimensions
            ),
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
    time slabs without holding the full stack in memory. The values are
    written in the handle's ``field_precision``.
    """
    if np.ndim(values) not in (2, 3):
        raise ValueError(f"Expected a (time, ...) stack, got shape {np.shape(values)}")
    offset = int(timestep_offset)
    total = int(n_timesteps) if n_timesteps is not None else offset + int(values.shape[0])
    if offset + int(values.shape[0]) > total:
        raise ValueError(
            f"Stack slab [{offset}:{offset + int(values.shape[0])}] exceeds "
            f"n_timesteps={total} for '{variable}'."
        )
    with store_obj._guard_write():
        target = _field_target(store_obj, subgroup)
        values, quantized = _to_stored_field(
            store_obj,
            values,
            path=_field_path(variable, subgroup),
            first_step=offset,
            stack=True,
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
                quantized=quantized,
            )

        arr = target[variable]
        arr[offset : offset + int(values.shape[0])] = values


def write_budget_policy(
    store_obj: SimulationZarr, keep: BudgetKeep, written: Iterable[str]
) -> None:
    """Record on ``budget/`` the policy an extractor applied and the terms it kept.

    Under ``"all"`` the kept terms are the names written under ``budget/``.
    Under ``"consumers"`` they are the terms of the plan, produced or not: a
    kept term with no array is one the model does not produce. The group is
    created when absent, so a store that wrote nothing still says so.
    """
    if keep.policy == POLICY_ALL:
        kept = sorted({str(name) for name in written})
    else:
        kept = sorted(keep.terms)
    with store_obj._guard_write():
        group = _field_target(store_obj, "budget")
        update_attrs(group, {BUDGET_POLICY_ATTR: keep.policy, BUDGET_KEPT_TERMS_ATTR: kept})


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
        write_array(
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
        write_array(
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


def write_forcing_attrs(store_obj: SimulationZarr, attrs: Mapping[str, object]) -> None:
    """Stamp attributes on the ``forcing`` group."""
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "forcing")
        update_attrs(store_obj._root.require_group("forcing"), attrs)


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
        write_array(
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


# -- Soil reservoir columns (per-run) ----------------------------------------

# Fixed per-column arrays of the soil reservoir group: name -> (dtype, units,
# long_name). Unlike ``series``, these carry no per-call metadata: the set of
# columns is closed (spec section 6.2), so a caller passing an unknown one
# fails on the dict lookup below.
_SOIL_COLUMN_ARRAYS: dict[str, tuple[str, str, str]] = {
    "cell_index": ("int32", "1", "Flat (y, x) index of the SAFRAN cell"),
    "class_index": ("int32", "1", "Soil capacity class inside the cell"),
    "x": ("float64", "m", "Cell centre x, CRS of the run"),
    "y": ("float64", "m", "Cell centre y, CRS of the run"),
    "ru_mm": ("float64", "mm", "Soil available water capacity of the column"),
    "cell_fraction": ("float64", "1", "Share of its cell the column covers"),
    "basin_weight": ("float64", "1", "Weight of the column in the basin mean"),
}


def write_soil_columns(
    store_obj: SimulationZarr,
    *,
    timestamps: np.ndarray,
    series: Mapping[str, tuple[np.ndarray, str, str, str]],
    columns: Mapping[str, np.ndarray],
    attrs: Mapping[str, object],
) -> None:
    """Persist the soil reservoir columns under ``forcing/soil``.

    ``series`` maps a daily flux or state name to ``(values, units,
    cell_methods, long_name)``, ``(record, soil_column)`` shaped. ``columns``
    maps the fixed per-column arrays of :data:`_SOIL_COLUMN_ARRAYS`,
    ``(soil_column,)`` shaped. ``attrs`` is stamped on the group as-is.
    """
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "forcing")
        forcing = store_obj._root.require_group("forcing")
        ensure_child_dir(store_obj, forcing, "soil")
        soil = forcing.require_group("soil")

        ts = np.asarray(timestamps, dtype="datetime64[ns]").view("int64")
        write_array(
            store_obj,
            soil,
            "timestamps",
            ts,
            dimension_names=(field_registry.AXIS_RECORD,),
            attrs={
                "units": "nanoseconds since 1970-01-01T00:00:00",
                "calendar": "proleptic_gregorian",
                "standard_name": "time",
                "long_name": "Day of each soil record",
                "axis": "T",
            },
            compressors=BLOSC_ZSTD,
        )

        for name, (values, units, cell_methods, long_name) in series.items():
            write_array(
                store_obj,
                soil,
                name,
                np.asarray(values, dtype="float64"),
                dimension_names=(field_registry.AXIS_RECORD, field_registry.AXIS_SOIL_COLUMN),
                attrs={
                    "units": str(units),
                    "cell_methods": str(cell_methods),
                    "long_name": str(long_name),
                },
                compressors=BLOSC_ZSTD,
            )

        for name, values in columns.items():
            dtype, units, long_name = _SOIL_COLUMN_ARRAYS[name]
            write_array(
                store_obj,
                soil,
                name,
                np.asarray(values, dtype=dtype),
                dimension_names=(field_registry.AXIS_SOIL_COLUMN,),
                attrs={"units": units, "long_name": long_name},
                compressors=BLOSC_ZSTD,
            )

        update_attrs(soil, dict(attrs))


# -- Geographic rasters (per-run) -------------------------------------------


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
            write_array(
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
    ``lake_id -> stage`` in meters; an empty mapping writes nothing.
    """
    if not stages:
        return
    lake_ids = [str(lake_id) for lake_id in stages]
    values = np.asarray([float(stages[lake_id]) for lake_id in lake_ids], dtype="float64")
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "lake_state_final")
        grp = store_obj._root.require_group("lake_state_final")
        write_array(
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
    """Materialize the axis coordinates the fields name, and drop dangling ones.

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
            write_array(
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
            write_array(
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
        for path, array in _walk_arrays(root):
            attrs = dict(array.attrs)
            grid_mapping = attrs.get("grid_mapping")
            group = path.rpartition("/")[0]
            if grid_mapping and not {str(grid_mapping), f"{group}/{grid_mapping}"} & present:
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
) -> dict[str, Any]:
    """Compose and persist ACDD root attrs. Returns the attrs written."""
    attrs = compose_acdd_root_attrs(
        sim_row=sim_row,
        runs_env=runs_env,
        project_table=project_table,
        geographic_bounds=geographic_bounds,
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
    "field_name_from_target",
    "harmonize_axis_references",
    "maybe_shards",
    "QUANTIZATION_VARIABLE",
    "write_acdd_root_attrs",
    "write_field",
    "write_forcing_attrs",
    "write_forcing_field",
    "write_forcing_timeseries",
    "write_lake_abacus",
    "write_static_field",
]
