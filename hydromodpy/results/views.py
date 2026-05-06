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

Module-level functions are the canonical implementation. ``Run`` exposes
thin lazy wrappers for notebook ergonomics.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from hydromodpy.results.run import Run

SimulatedActiveNetworkMode = Literal[
    "last",
    "any",
    "persistent",
    "always_active",
    "perennial",
    "persistence",
]


__all__ = [
    "saturated_fraction",
    "drainage_density",
    "persistence",
    "resolve_simulated_active_network_mode",
    "simulated_active_network_mode_label",
    "simulated_active_network_mask",
    "simulated_active_network_metrics",
    "simulated_active_network_overlap_metrics",
    "simulated_active_network_distance_metrics",
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
    try:
        mesh = sz.root.get("mesh")
        if mesh is None or "surface_top" not in mesh:
            return None
        top = np.asarray(mesh["surface_top"][:], dtype="float64").ravel()
        return np.isfinite(top) & (top > -9000.0)
    finally:
        sz.close()


def _stack_field(sim: Run, variable: str) -> np.ndarray:
    """Stack a per-timestep cell field into a ``(n_t, n_cells)`` array."""
    n = sim.n_timesteps or 1
    frames = [np.asarray(sim.field(variable, timestep=t)).ravel() for t in range(n)]
    return np.stack(frames)


def _stack_field_with_mask(sim: Run, variable: str) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(stack, active_cell_mask)`` and validate cell dimensions."""
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
    vertices = np.asarray(mesh.vertices)
    face_node_connectivity = np.asarray(mesh.face_node_connectivity)
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
    """Boolean mask of mesh cells intersected by one vector network."""
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


def _flatten_geometries(geometries: Iterable[BaseGeometry]) -> list[BaseGeometry]:
    """Flatten geometry collections into concrete Shapely geometries."""
    flattened: list[BaseGeometry] = []
    for geometry in geometries:
        if geometry is None or geometry.is_empty:
            continue
        parts = getattr(geometry, "geoms", None)
        if parts is None:
            flattened.append(geometry)
        else:
            flattened.extend(_flatten_geometries(parts))
    return flattened


def _network_geometries(network_gdf, *, buffer_m: float = 0.0) -> list[BaseGeometry]:
    """Return vector-network geometries, optionally buffered in model units."""
    if network_gdf is None or network_gdf.empty:
        return []
    geometries = network_gdf.geometry.dropna()
    if geometries.empty:
        return []
    if buffer_m > 0.0:
        geometries = geometries.buffer(float(buffer_m))
    return _flatten_geometries(geometries)


def _intersecting_cell_mask(
    polygons: np.ndarray,
    geometries: list[BaseGeometry],
) -> np.ndarray:
    """Return cells whose polygon intersects any of ``geometries``."""
    from shapely.strtree import STRtree

    mask = np.zeros(polygons.shape[0], dtype=bool)
    if not geometries:
        return mask
    tree = STRtree(geometries)
    for idx, polygon in enumerate(polygons):
        if polygon is None:
            continue
        if tree.query(polygon, predicate="intersects").size:
            mask[idx] = True
    return mask


def _nearest_distances(
    sources: Iterable[BaseGeometry],
    targets: list[BaseGeometry],
) -> list[float]:
    """Return distance from each source geometry to its nearest target."""
    from shapely.strtree import STRtree

    target_geometries = [target for target in targets if target is not None and not target.is_empty]
    if not target_geometries:
        return []
    tree = STRtree(target_geometries)
    distances: list[float] = []
    for source in sources:
        if source is None or source.is_empty:
            continue
        nearest = tree.nearest(source)
        if nearest is None:
            continue
        target = target_geometries[int(nearest)]
        distances.append(float(source.distance(target)))
    return distances


def _distance_stats(distances: list[float], *, prefix: str) -> dict[str, float | int | None]:
    """Return stable summary statistics for one directed distance sample."""
    if not distances:
        return {
            f"{prefix}_sample_count": 0,
            f"{prefix}_distance_mean_m": None,
            f"{prefix}_distance_median_m": None,
            f"{prefix}_distance_p95_m": None,
            f"{prefix}_distance_max_m": None,
        }
    values = np.asarray(distances, dtype="float64")
    return {
        f"{prefix}_sample_count": int(values.size),
        f"{prefix}_distance_mean_m": float(np.mean(values)),
        f"{prefix}_distance_median_m": float(np.median(values)),
        f"{prefix}_distance_p95_m": float(np.percentile(values, 95.0)),
        f"{prefix}_distance_max_m": float(np.max(values)),
    }


def _finite_mean(value: object) -> float | None:
    """Return a finite float or ``None``."""
    if value is None:
        return None
    parsed = float(value)
    return parsed if np.isfinite(parsed) else None


def _safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _flow_regime(sim: Run) -> str:
    direct_value = getattr(sim, "flow_regime", None)
    if isinstance(direct_value, str) and direct_value:
        return direct_value.lower()

    try:
        row = sim._load_row()
    except Exception:
        return "unknown"

    getter = getattr(row, "get", None)
    value = getter("flow_regime") if callable(getter) else getattr(row, "flow_regime", None)
    return value.lower() if isinstance(value, str) and value else "unknown"


def resolve_simulated_active_network_mode(
    sim: Run, mode: SimulatedActiveNetworkMode | None = None
) -> str:
    """Resolve the active-network mode from an optional user override."""
    if mode is None:
        return "last" if _flow_regime(sim) == "steady" else "persistent"
    if mode == "perennial":
        return "always_active"
    if mode in {"last", "any", "persistent", "always_active", "persistence"}:
        return mode
    raise ValueError(
        "Unknown simulated active-network mode. Expected one of: "
        "last, any, persistent, always_active, perennial, persistence."
    )


def simulated_active_network_mode_label(
    sim: Run,
    *,
    mode: SimulatedActiveNetworkMode | None = None,
    persistence_threshold: float = 0.5,
) -> str:
    """Return a display label for an active-network mode."""
    resolved_mode = resolve_simulated_active_network_mode(sim, mode)
    if resolved_mode == "last":
        return "steady active cells" if _flow_regime(sim) == "steady" else "last active step"
    if resolved_mode == "any":
        return "any active step"
    if resolved_mode == "persistent":
        return "persistent active cells"
    if resolved_mode == "always_active":
        return "always active cells"
    return f"persistence >= {persistence_threshold:g}"


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------


def saturated_fraction(
    sim: Run,
    *,
    threshold: float = 0.0,
) -> pd.Series:
    """Fraction of active catchment cells where seepage exceeds ``threshold``.

    Reads ``derived/seepage_mask`` from the simulation Zarr and
    reduces each timestep to the percentage of active cells above the
    threshold. Unit: ``%``.
    """
    mask = _catchment_mask(sim)
    stack = _stack_field(sim, "seepage_mask")
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

    Reads ``derived/accumulation_flux`` (m³/d) from the simulation Zarr
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
    mode: SimulatedActiveNetworkMode | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
) -> np.ndarray:
    """Return a per-cell simulated active-network view.

    The default mode is regime-aware: steady simulations use the last active
    step, transient or unknown simulations use persistent active cells.
    """
    persistence_threshold = float(persistence_threshold)
    if not 0.0 <= persistence_threshold <= 1.0:
        raise ValueError("persistence_threshold must be between 0 and 1.")
    normalized_mode = resolve_simulated_active_network_mode(sim, mode)

    stack, mask = _stack_field_with_mask(sim, variable)
    n_timesteps = stack.shape[0]
    if n_timesteps == 0:
        return np.full(stack.shape[1], np.nan, dtype="float64")

    active = np.asarray(stack, dtype="float64") > float(threshold)
    if normalized_mode == "last":
        ts = n_timesteps - 1 if timestep is None else int(timestep)
        if ts < 0:
            ts = n_timesteps + ts
        if ts < 0 or ts >= n_timesteps:
            raise IndexError(
                f"timestep {timestep} is outside the simulated active-network range "
                f"[0, {n_timesteps - 1}]."
            )
        values = active[ts].astype("float64")
    elif normalized_mode == "any":
        values = active.any(axis=0).astype("float64")
    elif normalized_mode == "persistent":
        values = (active.mean(axis=0) >= persistence_threshold).astype("float64")
    elif normalized_mode == "always_active":
        values = (active.mean(axis=0) >= 1.0).astype("float64")
    elif normalized_mode == "persistence":
        values = active.mean(axis=0).astype("float64")
    else:
        raise ValueError(
            "Unknown simulated active-network mode. Expected one of: "
            "last, any, persistent, always_active, perennial, persistence."
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
    """Return scalar metrics for the simulated active drainage network."""
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
            "always_active_cell_count": 0,
            "perennial_cell_count": 0,
            "drainage_density_mean_pct": 0.0,
            "drainage_density_max_pct": 0.0,
            "drainage_density_last_pct": 0.0,
            "active_any_ratio": 0.0,
            "persistent_ratio": 0.0,
            "always_active_ratio": 0.0,
            "perennial_ratio": 0.0,
            "persistence_mean": 0.0,
            "persistence_max": 0.0,
        }

    active = (np.asarray(stack, dtype="float64") > float(threshold)) & mask[None, :]
    active_counts = active.sum(axis=1).astype(float)
    persistence_fraction = active.mean(axis=0)
    active_any = persistence_fraction > 0.0
    persistent = persistence_fraction >= float(persistence_threshold)
    always_active = persistence_fraction >= 1.0

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
        "always_active_cell_count": int(always_active.sum()),
        "perennial_cell_count": int(always_active.sum()),
        "drainage_density_mean_pct": float(100.0 * np.mean(active_counts) / n_cells),
        "drainage_density_max_pct": float(100.0 * np.max(active_counts) / n_cells),
        "drainage_density_last_pct": float(100.0 * active_counts[-1] / n_cells),
        "active_any_ratio": float(active_any.sum() / n_cells),
        "persistent_ratio": float(persistent.sum() / n_cells),
        "always_active_ratio": float(always_active.sum() / n_cells),
        "perennial_ratio": float(always_active.sum() / n_cells),
        "persistence_mean": float(np.mean(persistence_fraction[mask])),
        "persistence_max": float(np.max(persistence_fraction[mask])),
    }


def simulated_active_network_overlap_metrics(
    sim: Run,
    *,
    network_role: str = "reference",
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: SimulatedActiveNetworkMode | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    buffer_m: float = 0.0,
) -> dict[str, float | int | str]:
    """Compare simulated active cells with an existing vector network role."""
    resolved_mode = resolve_simulated_active_network_mode(sim, mode)
    values = simulated_active_network_mask(
        sim,
        variable=variable,
        threshold=threshold,
        mode=resolved_mode,
        persistence_threshold=persistence_threshold,
        timestep=timestep,
    )
    valid = np.isfinite(values)
    if resolved_mode == "persistence":
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
        "mode": resolved_mode,
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


def simulated_active_network_distance_metrics(
    sim: Run,
    *,
    network_role: str = "reference",
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: SimulatedActiveNetworkMode | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    network_buffer_m: float = 0.0,
) -> dict[str, float | int | str | None]:
    """Return planar bidirectional distances between active cells and a network.

    Distances are computed in model/map units as follows:

    - simulated-to-network: centroid distance from each active simulated cell to
      the selected vector hydrographic network;
    - network-to-simulated: centroid distance from each mesh cell intersected by
      the selected vector network to the union of active simulated cell
      polygons.

    This is a lazy result view: it reads persisted fields and vector features
    from ``sim`` and does not mutate the catalog.
    """
    resolved_mode = resolve_simulated_active_network_mode(sim, mode)
    values = simulated_active_network_mask(
        sim,
        variable=variable,
        threshold=threshold,
        mode=resolved_mode,
        persistence_threshold=persistence_threshold,
        timestep=timestep,
    )
    valid = np.isfinite(values)
    if resolved_mode == "persistence":
        active = values >= float(persistence_threshold)
    else:
        active = values > 0.5
    active = active & valid

    polygons = _mesh_face_polygons(sim)
    if polygons.size != values.size:
        raise ValueError(
            "Mesh polygon count does not match simulated active-network field size: "
            f"mesh={polygons.size}, field={values.size}."
        )

    network_gdf = sim.hydrographic_network(network_role)
    network_geometries = _network_geometries(
        network_gdf,
        buffer_m=float(network_buffer_m),
    )
    network_cells = _intersecting_cell_mask(polygons, network_geometries) & valid

    active_polygons = [
        polygon for polygon, is_active in zip(polygons, active, strict=True) if is_active
    ]
    active_polygons = [polygon for polygon in active_polygons if polygon is not None]
    active_centroids = [polygon.centroid for polygon in active_polygons]
    network_centroids = [
        polygon.centroid
        for polygon, is_network in zip(polygons, network_cells, strict=True)
        if is_network and polygon is not None
    ]

    sim_to_network_distances = _nearest_distances(
        active_centroids,
        network_geometries,
    )
    network_to_sim_distances = _nearest_distances(
        network_centroids,
        active_polygons,
    )

    sim_to_network = _distance_stats(
        sim_to_network_distances,
        prefix="sim_to_network",
    )
    network_to_sim = _distance_stats(
        network_to_sim_distances,
        prefix="network_to_sim",
    )
    sim_mean = _finite_mean(sim_to_network["sim_to_network_distance_mean_m"])
    network_mean = _finite_mean(network_to_sim["network_to_sim_distance_mean_m"])
    if sim_mean is None or network_mean is None:
        bidirectional_mean = None
        bidirectional_quadratic_mean = None
        bidirectional_absolute_difference_m = None
        distance_ratio = None
        distance_log10_ratio = None
    else:
        bidirectional_mean = float(0.5 * (sim_mean + network_mean))
        bidirectional_quadratic_mean = float(np.hypot(sim_mean, network_mean))
        bidirectional_absolute_difference_m = float(abs(sim_mean - network_mean))
        if sim_mean == 0.0 and network_mean == 0.0:
            distance_ratio = 1.0
            distance_log10_ratio = 0.0
        elif network_mean > 0.0 and sim_mean > 0.0:
            distance_ratio = float(sim_mean / network_mean)
            distance_log10_ratio = float(np.log10(distance_ratio))
        else:
            distance_ratio = None
            distance_log10_ratio = None

    return {
        "network_role": network_role,
        "source_variable": variable,
        "threshold": float(threshold),
        "mode": resolved_mode,
        "persistence_threshold": float(persistence_threshold),
        "timestep": int(timestep) if timestep is not None else -1,
        "network_buffer_m": float(network_buffer_m),
        "distance_method": "planar_cell_centroid_to_network",
        "catchment_cell_count": int(valid.sum()),
        "active_cell_count": int(active.sum()),
        "network_cell_count": int(network_cells.sum()),
        **sim_to_network,
        **network_to_sim,
        "bidirectional_distance_mean_m": bidirectional_mean,
        "bidirectional_distance_quadratic_mean_m": bidirectional_quadratic_mean,
        "bidirectional_distance_absolute_difference_m": bidirectional_absolute_difference_m,
        "planar_distance_ratio": distance_ratio,
        "planar_distance_log10_ratio": distance_log10_ratio,
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
    try:
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
    finally:
        sz.close()

    return pd.Series(means, index=_time_index(sim, n_t), name="recharge_forcing")
