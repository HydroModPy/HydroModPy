"""Lazy catchment-scale views computed on demand from a Run.

These functions read already-persisted spatial fields (``derived/`` and
``budget/`` groups in the simulation Zarr) and reduce them to scalar
timeseries on the fly. Nothing is written to DuckDB: results are returned
as ``pd.Series`` so that callers can plot, combine or aggregate them
freely.

All functions are pure - they take a :class:`Run` (or any
object exposing the same ``field`` / ``n_timesteps`` / ``mesh`` API) and
the reduction parameters, and return a new object. They never mutate the
catalog.

Standard Python pattern: the module-level function is the source of
truth; :class:`Run` exposes thin delegate methods for
ergonomics (``sim.drainage_density(...)`` calls
:func:`drainage_density`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


__all__ = [
    "saturated_fraction",
    "drainage_density",
    "persistence",
    "simulated_active_network_mask",
    "simulated_active_network_metrics",
    "simulated_active_network_overlap_metrics",
    "catchment_mean",
    "recharge_forcing",
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _time_index(sim: Run, n: int) -> pd.DatetimeIndex:
    """Return a ``pd.DatetimeIndex`` aligned with the simulation timesteps."""
    row = sim._load_row()
    start, end = row.get("period_start"), row.get("period_end")
    if start is not None and end is not None:
        return pd.date_range(start=start, end=end, periods=n)
    return pd.date_range("2000-01-01", periods=n, freq="D")


def _catchment_mask(sim: Run) -> np.ndarray | None:
    """Boolean mask of active cells from ``mesh/surface_top``."""
    sz = sim._catalog.open_zarr(sim._sim_id)
    mesh = sz.root.get("mesh")
    if mesh is None or "surface_top" not in mesh:
        return None
    top = np.asarray(mesh["surface_top"][:], dtype="float64").ravel()
    return np.isfinite(top) & (top > -9000.0)


def _stack_field(sim: Run, variable: str) -> np.ndarray:
    """Stack a per-timestep cell field into a ``(n_t, n_cells)`` array."""
    n = sim.n_timesteps or 1
    frames = [np.asarray(sim.field(variable, timestep=t)).ravel() for t in range(n)]
    return np.stack(frames)


def _stack_field_with_mask(sim: Run, variable: str) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(stack, active_cell_mask)`` and validate their cell dimensions."""
    stack = _stack_field(sim, variable)
    mask = _catchment_mask(sim)
    if mask is None:
        mask = np.ones(stack.shape[1], dtype=bool)
    else:
        mask = np.asarray(mask, dtype=bool).ravel()
    if mask.size != stack.shape[1]:
        raise ValueError(
            "Catchment mask size does not match simulated active-network field size: "
            f"mask={mask.size}, field={stack.shape[1]}."
        )
    return stack, mask


def _mesh_face_polygons(sim: Run) -> np.ndarray:
    """Return one Shapely polygon per mesh face."""
    from shapely.geometry import Polygon

    mesh = sim.mesh
    vertices = np.asarray(mesh["vertices"])
    face_node_connectivity = np.asarray(mesh["face_node_connectivity"])
    polygons = []
    for row in face_node_connectivity:
        nodes = row[row >= 0] if row.dtype.kind in "iu" else row[~np.isnan(row)]
        if nodes.size < 3:
            polygons.append(None)
            continue
        polygon = Polygon(vertices[nodes.astype(int), :2])
        polygons.append(polygon if polygon.is_valid and not polygon.is_empty else None)
    return np.asarray(polygons, dtype=object)


def _network_cell_mask(sim: Run, network_gdf, *, buffer_m: float = 0.0) -> np.ndarray:
    """Boolean mask of mesh cells intersected by one vector hydrographic network."""
    polygons = _mesh_face_polygons(sim)
    mask = np.zeros(polygons.shape[0], dtype=bool)
    if network_gdf is None or network_gdf.empty:
        return mask

    geometries = network_gdf.geometry.dropna()
    if geometries.empty:
        return mask
    if buffer_m > 0.0:
        geometries = geometries.buffer(float(buffer_m))
    try:
        network_union = geometries.union_all()
    except AttributeError:
        network_union = geometries.unary_union
    if network_union is None or network_union.is_empty:
        return mask

    for idx, polygon in enumerate(polygons):
        if polygon is not None and polygon.intersects(network_union):
            mask[idx] = True
    return mask


def _safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------


def saturated_fraction(
    sim: Run,
    *,
    threshold: float = 0.0,
) -> pd.Series:
    """Fraction of active catchment cells where seepage exceeds ``threshold``.

    Reads ``derived/seepage_areas`` (m) from the simulation Zarr and
    reduces each timestep to the percentage of active cells above the
    threshold. Unit: ``%``.
    """
    mask = _catchment_mask(sim)
    stack = _stack_field(sim, "seepage_areas")
    if mask is None:
        mask = np.ones(stack.shape[1], dtype=bool)
    n_active = int(mask.sum())
    if n_active == 0:
        return pd.Series(dtype="float64", name="saturated_fraction")
    active = (stack > threshold) & mask
    pct = 100.0 * active.sum(axis=1) / n_active
    return pd.Series(pct, index=_time_index(sim, stack.shape[0]), name="saturated_fraction")


def drainage_density(
    sim: Run,
    *,
    threshold: float = 0.0,
) -> pd.Series:
    """Fraction of active catchment cells whose routed drain flux is positive.

    Reads ``derived/accumulation_flux`` from the simulation Zarr
    and returns the fraction of active cells above ``threshold``, per
    timestep. Unit: ``%``.

    Matches the headwater-study definition of "active drainage density"
    (stream-network occupation of the catchment).
    """
    mask = _catchment_mask(sim)
    stack = _stack_field(sim, "accumulation_flux")
    if mask is None:
        mask = np.ones(stack.shape[1], dtype=bool)
    n_active = int(mask.sum())
    if n_active == 0:
        return pd.Series(dtype="float64", name="drainage_density")
    active = (stack > threshold) & mask
    pct = 100.0 * active.sum(axis=1) / n_active
    return pd.Series(pct, index=_time_index(sim, stack.shape[0]), name="drainage_density")


def persistence(
    sim: Run,
    *,
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    window: Literal["year", "full"] = "full",
) -> np.ndarray:
    """Per-cell fraction of timesteps where ``variable`` exceeds ``threshold``.

    ``window='full'`` reduces over the whole simulation and returns a 1D
    array of length ``n_cells``. ``window='year'`` groups by calendar
    year and returns a 2D array ``(n_years, n_cells)``.
    """
    stack = _stack_field(sim, variable)
    active = stack > threshold
    if window == "full":
        return active.mean(axis=0)
    if window == "year":
        idx = _time_index(sim, stack.shape[0])
        frame = pd.DataFrame(active, index=idx)
        return frame.groupby(frame.index.year).mean().to_numpy()
    raise ValueError(f"Unknown window '{window}'")


def simulated_active_network_mask(
    sim: Run,
    *,
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: Literal["last", "any", "persistent", "perennial", "persistence"] = "persistent",
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
) -> np.ndarray:
    """Return a per-cell simulated active-network view.

    The view is computed from a persisted cell field, usually
    ``derived/accumulation_flux``. It does not persist a vector network.

    Modes:
    - ``last``: cells active at the selected timestep, defaulting to the last one.
    - ``any``: cells active at least once over the simulation.
    - ``persistent``: cells active for at least ``persistence_threshold`` of timesteps.
    - ``perennial``: cells active at every timestep.
    - ``persistence``: continuous active-time fraction in ``[0, 1]``.

    Inactive catchment cells are returned as ``0`` for binary modes. Cells
    outside the active catchment mask are returned as ``NaN`` for plotting.
    """
    persistence_threshold = float(persistence_threshold)
    if not 0.0 <= persistence_threshold <= 1.0:
        raise ValueError("persistence_threshold must be between 0 and 1.")

    stack, mask = _stack_field_with_mask(sim, variable)
    n_timesteps = stack.shape[0]
    if n_timesteps == 0:
        return np.full(stack.shape[1], np.nan, dtype="float64")

    active = np.asarray(stack, dtype="float64") > float(threshold)
    if mode == "last":
        ts = n_timesteps - 1 if timestep is None else int(timestep)
        if ts < 0:
            ts = n_timesteps + ts
        if ts < 0 or ts >= n_timesteps:
            raise IndexError(
                f"timestep {timestep} is outside the simulated active-network range "
                f"[0, {n_timesteps - 1}]."
            )
        values = active[ts].astype("float64")
    elif mode == "any":
        values = active.any(axis=0).astype("float64")
    elif mode == "persistent":
        values = (active.mean(axis=0) >= persistence_threshold).astype("float64")
    elif mode == "perennial":
        values = (active.mean(axis=0) >= 1.0).astype("float64")
    elif mode == "persistence":
        values = active.mean(axis=0).astype("float64")
    else:
        raise ValueError(
            "Unknown simulated active-network mode. Expected one of: "
            "last, any, persistent, perennial, persistence."
        )

    values[~mask] = np.nan
    return values


def simulated_active_network_metrics(
    sim: Run,
    *,
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    persistence_threshold: float = 0.5,
) -> dict[str, float | int | str]:
    """Return scalar metrics for the simulated active drainage network.

    This is a computed view over a persisted cell field, not a persisted
    ``HydrographicNetwork(role="simulated_active")``. The default contract
    interprets cells with ``accumulation_flux > threshold`` as active at one
    timestep, then summarizes active occupancy through time.
    """
    if not 0.0 <= float(persistence_threshold) <= 1.0:
        raise ValueError("persistence_threshold must be between 0 and 1.")

    stack, mask = _stack_field_with_mask(sim, variable)

    n_cells = int(mask.sum())
    n_timesteps = int(stack.shape[0])
    if n_cells == 0 or n_timesteps == 0:
        return {
            "source_variable": variable,
            "threshold": float(threshold),
            "persistence_threshold": float(persistence_threshold),
            "n_timesteps": n_timesteps,
            "catchment_cell_count": 0,
            "active_cell_count_mean": 0.0,
            "active_cell_count_max": 0,
            "active_cell_count_last": 0,
            "active_cell_count_any": 0,
            "persistent_cell_count": 0,
            "perennial_cell_count": 0,
            "drainage_density_mean_pct": 0.0,
            "drainage_density_max_pct": 0.0,
            "drainage_density_last_pct": 0.0,
            "active_any_ratio": 0.0,
            "persistent_ratio": 0.0,
            "perennial_ratio": 0.0,
            "persistence_mean": 0.0,
            "persistence_max": 0.0,
        }

    active = (np.asarray(stack, dtype="float64") > float(threshold)) & mask[None, :]
    active_counts = active.sum(axis=1).astype(float)
    persistence_fraction = active.mean(axis=0)
    active_any = persistence_fraction > 0.0
    persistent = persistence_fraction >= float(persistence_threshold)
    perennial = persistence_fraction >= 1.0

    return {
        "source_variable": variable,
        "threshold": float(threshold),
        "persistence_threshold": float(persistence_threshold),
        "n_timesteps": n_timesteps,
        "catchment_cell_count": n_cells,
        "active_cell_count_mean": float(np.mean(active_counts)),
        "active_cell_count_max": int(np.max(active_counts)),
        "active_cell_count_last": int(active_counts[-1]),
        "active_cell_count_any": int(active_any.sum()),
        "persistent_cell_count": int(persistent.sum()),
        "perennial_cell_count": int(perennial.sum()),
        "drainage_density_mean_pct": float(100.0 * np.mean(active_counts) / n_cells),
        "drainage_density_max_pct": float(100.0 * np.max(active_counts) / n_cells),
        "drainage_density_last_pct": float(100.0 * active_counts[-1] / n_cells),
        "active_any_ratio": float(active_any.sum() / n_cells),
        "persistent_ratio": float(persistent.sum() / n_cells),
        "perennial_ratio": float(perennial.sum() / n_cells),
        "persistence_mean": float(np.mean(persistence_fraction[mask])),
        "persistence_max": float(np.max(persistence_fraction[mask])),
    }


def simulated_active_network_overlap_metrics(
    sim: Run,
    *,
    network_role: str = "reference",
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: Literal["last", "any", "persistent", "perennial", "persistence"] = "persistent",
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    buffer_m: float = 0.0,
) -> dict[str, float | int | str]:
    """Compare simulated active cells with an existing vector network role.

    This is a cell-overlap diagnostic. It rasterizes the selected persisted
    vector network role onto mesh cells by intersection, then compares that
    occupancy mask with ``simulated_active_network_mask``. The default target
    is ``reference`` because the primary validation question is whether the
    simulated active network matches observed hydrography. ``generated`` is
    still useful as a secondary topographic/DEM-derived diagnostic.
    """
    values = simulated_active_network_mask(
        sim,
        variable=variable,
        threshold=threshold,
        mode=mode,
        persistence_threshold=persistence_threshold,
        timestep=timestep,
    )
    valid = np.isfinite(values)
    if mode == "persistence":
        active = values >= float(persistence_threshold)
    else:
        active = values > 0.5
    active = active & valid

    network_gdf = sim.hydrographic_network(network_role)
    network_cells = _network_cell_mask(sim, network_gdf, buffer_m=float(buffer_m))
    if network_cells.size != values.size:
        raise ValueError(
            "Vector-network cell mask size does not match simulated active-network field size: "
            f"network={network_cells.size}, field={values.size}."
        )
    network_cells = network_cells & valid

    overlap = active & network_cells
    missing = network_cells & ~active
    extra = active & ~network_cells
    active_count = int(active.sum())
    network_count = int(network_cells.sum())
    overlap_count = int(overlap.sum())
    union_count = int((active | network_cells).sum())

    precision = _safe_ratio(overlap_count, active_count)
    coverage = _safe_ratio(overlap_count, network_count)
    f1 = 0.0 if precision + coverage == 0.0 else 2.0 * precision * coverage / (precision + coverage)

    return {
        "network_role": network_role,
        "source_variable": variable,
        "threshold": float(threshold),
        "mode": mode,
        "persistence_threshold": float(persistence_threshold),
        "timestep": int(timestep) if timestep is not None else -1,
        "buffer_m": float(buffer_m),
        "catchment_cell_count": int(valid.sum()),
        "active_cell_count": active_count,
        "network_cell_count": network_count,
        "overlap_cell_count": overlap_count,
        "missing_network_cell_count": int(missing.sum()),
        "extra_active_cell_count": int(extra.sum()),
        "network_coverage_ratio": coverage,
        "active_precision_ratio": precision,
        "cell_f1_ratio": float(f1),
        "cell_jaccard_ratio": _safe_ratio(overlap_count, union_count),
    }


def catchment_mean(
    sim: Run,
    variable: str,
    *,
    name: str | None = None,
) -> pd.Series:
    """Arithmetic mean of ``variable`` over active catchment cells per timestep.

    Works for any cell-scalar variable persisted under ``derived/`` or
    ``budget/`` (e.g. ``watertable_depth``, ``watertable_elevation``).
    """
    mask = _catchment_mask(sim)
    stack = _stack_field(sim, variable)
    if mask is None:
        mask = np.ones(stack.shape[1], dtype=bool)
    if not mask.any():
        return pd.Series(dtype="float64", name=name or variable)
    masked = np.where(mask[None, :], stack, np.nan)
    means = np.nanmean(masked, axis=1)
    return pd.Series(means, index=_time_index(sim, stack.shape[0]), name=name or variable)


def recharge_forcing(sim: Run) -> pd.Series:
    """Input recharge rate per stress period (from ``budget/recharge``).

    Reads the first substep of each stress period from the MODFLOW
    budget; constant within a period by the forcing contract.
    """
    sz = sim._catalog.open_zarr(sim._sim_id)
    budget = sz.root.get("budget")
    if budget is None:
        return pd.Series(dtype="float64", name="recharge_forcing")
    rch_key = next((k for k in ("recharge", "rch") if k in budget), None)
    if rch_key is None:
        return pd.Series(dtype="float64", name="recharge_forcing")

    arr = budget[rch_key]
    n_t = arr.shape[0]
    mask = _catchment_mask(sim)
    means = []
    for t in range(n_t):
        field = np.asarray(arr[t], dtype="float64").ravel()
        if mask is not None and mask.size == field.size:
            field = np.where(mask, field, np.nan)
        means.append(float(np.nanmean(field)))

    return pd.Series(means, index=_time_index(sim, n_t), name="recharge_forcing")
