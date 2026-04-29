"""MF6 recharge / EVT stress-period data builders."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

import numpy as np

from hydromodpy.core.units import convert_payload_to_m_per_s


def sanitize_numeric_payload(payload: object) -> object:
    """Replace unsupported/invalid numeric payload values by finite MF6-safe values."""
    if payload is None:
        return 0.0
    if isinstance(payload, Mapping):
        return {key: sanitize_numeric_payload(value) for key, value in payload.items()}
    if isinstance(payload, Real) and not isinstance(payload, bool):
        scalar = float(payload)
        return 0.0 if not np.isfinite(scalar) else scalar
    if hasattr(payload, "replace") and hasattr(payload, "fillna"):
        series = payload.copy()
        series = series.astype(float)
        return series.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    arr = np.asarray(payload, dtype=float)
    if arr.ndim == 0:
        scalar = float(arr)
        return 0.0 if not np.isfinite(scalar) else scalar
    return np.nan_to_num(arr.astype(float, copy=False), nan=0.0, posinf=0.0, neginf=0.0)


def payload_has_negative_values(payload: object) -> bool:
    """Return True when a recharge payload contains at least one negative value."""
    if isinstance(payload, Mapping):
        return any(payload_has_negative_values(value) for value in payload.values())
    if isinstance(payload, Real) and not isinstance(payload, bool):
        return float(payload) < 0.0
    arr = np.asarray(payload, dtype=float)
    return bool(np.any(arr < 0.0))


def clip_negative_payload(payload: object) -> object:
    """Clip negative recharge values to zero for MF6 RCH compatibility."""
    if isinstance(payload, Mapping):
        return {key: clip_negative_payload(value) for key, value in payload.items()}
    if isinstance(payload, Real) and not isinstance(payload, bool):
        return max(float(payload), 0.0)
    if hasattr(payload, "clip"):
        try:
            return payload.clip(lower=0.0)
        except TypeError:
            pass

    arr = np.asarray(payload, dtype=float)
    if arr.ndim == 0:
        return max(float(arr), 0.0)
    return np.maximum(arr, 0.0)


def copy_runtime_payload(payload: object) -> object:
    """Return a detached copy of one runtime payload when possible."""
    if isinstance(payload, Mapping):
        return {key: copy_runtime_payload(value) for key, value in payload.items()}
    if hasattr(payload, "copy"):
        try:
            return payload.copy()
        except Exception:
            pass
    return payload


def extract_evt_payload_2d(
    rch_data: Mapping[int, object],
    negative_to_evt: bool,
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray] | None]:
    """Route negative recharge arrays to EVT and clip RCH to non-negative values."""
    normalized_rch = {int(kper): np.asarray(value, dtype=float) for kper, value in rch_data.items()}
    if not negative_to_evt:
        return normalized_rch, None

    has_negative = any(np.any(arr < 0.0) for arr in normalized_rch.values())
    if not has_negative:
        return normalized_rch, None

    evt_data: dict[int, np.ndarray] = {}
    clipped_rch: dict[int, np.ndarray] = {}
    for kper, arr in normalized_rch.items():
        if int(kper) == 0:
            evt_data[int(kper)] = np.zeros_like(arr, dtype=float)
        else:
            evt_data[int(kper)] = np.abs(np.minimum(arr, 0.0)).astype(float, copy=False)
        clipped_rch[int(kper)] = np.maximum(arr, 0.0).astype(float, copy=False)
    return clipped_rch, evt_data


def series_payload_value(payload: object, kper: int, *, first_clim: object) -> float:
    """Resolve one scalar climate value from a scalar/sequence payload."""
    if kper == 0:
        if first_clim == "mean":
            arr = np.asarray(payload, dtype=float)
            return float(np.nanmean(arr))
        if first_clim == "first":
            if hasattr(payload, "iloc"):
                first = payload.iloc[0]
                if isinstance(first, Real) and not isinstance(first, bool):
                    return float(first)
                first_arr = np.asarray(first, dtype=float).ravel()
                return float(first_arr[0]) if first_arr.size else 0.0
            arr = np.asarray(payload, dtype=float).ravel()
            return float(arr[0]) if arr.size else 0.0
        if isinstance(first_clim, Real) and not isinstance(first_clim, bool):
            return float(first_clim)

    if hasattr(payload, "iloc"):
        idx = min(max(int(kper), 0), len(payload) - 1)
        value = payload.iloc[idx]
        if isinstance(value, Real) and not isinstance(value, bool):
            return float(value)
        value_arr = np.asarray(value, dtype=float).ravel()
        if value_arr.size:
            return float(value_arr[0])
        return 0.0

    arr = np.asarray(payload, dtype=float).ravel()
    if arr.size == 0:
        return 0.0
    idx = min(max(int(kper), 0), int(arr.size) - 1)
    return float(arr[idx])


def extract_evt_payload(
    model,
    payload: object,
    negative_to_evt: bool,
) -> tuple[object, dict[int, object] | None]:
    """Route negative recharge values to EVT and keep RCH non-negative."""
    if not negative_to_evt or not payload_has_negative_values(payload):
        return payload, None

    if isinstance(payload, Mapping):
        return extract_evt_payload_2d(payload, True)

    payload_for_rch = copy_runtime_payload(payload)
    evt_payload = copy_runtime_payload(payload)

    if isinstance(payload_for_rch, list):
        payload_for_rch = np.asarray(payload_for_rch, dtype=float)
    if isinstance(evt_payload, list):
        evt_payload = np.asarray(evt_payload, dtype=float)

    if hasattr(evt_payload, "clip"):
        try:
            payload_for_rch = evt_payload.clip(lower=0.0)
        except TypeError:
            payload_for_rch = clip_negative_payload(payload_for_rch)
    else:
        payload_for_rch = clip_negative_payload(payload_for_rch)

    evt_negative = np.asarray(evt_payload, dtype=float)
    evt_negative[evt_negative >= 0.0] = 0.0
    evt_negative = np.abs(evt_negative)

    first_clim = model.first_clim if model.first_clim is not None else "mean"
    evt_spd: dict[int, object] = {
        kper: (
            0.0 if kper == 0 else series_payload_value(evt_negative, kper, first_clim=first_clim)
        )
        for kper in range(int(model.nper))
    }
    return payload_for_rch, evt_spd


def bind_recharge_from_flow(model) -> None:
    """Resolve recharge inputs from the canonical flow recharge configuration."""
    model._evt_rate_payload = None
    model._pending_negative_to_evt = False
    if model.recharge is not None:
        model.recharge = sanitize_numeric_payload(model.recharge)
        if model.first_clim is None:
            model.first_clim = "mean"
        return

    active = getattr(model.flow, "active_sinks_sources", [])
    if "recharge" not in active:
        model.recharge = 0.0
        if model.first_clim is None:
            model.first_clim = "mean"
        return

    sinks_sources = getattr(model.flow, "sinks_sources", {})
    recharge_cfg = sinks_sources.get("recharge") if isinstance(sinks_sources, Mapping) else None
    if recharge_cfg is None:
        model.recharge = 0.0
        if model.first_clim is None:
            model.first_clim = "mean"
        return

    # Heterogeneous path: gridded FieldRecords or located PointRecords from data
    # managers. Both get discretized onto the solver grid by
    # `resolve_deferred_heterogeneous_recharge` once `solver_mesh` is available.
    het_source = getattr(recharge_cfg, "heterogeneous_source", None)
    if het_source is not None and (
        getattr(het_source, "has_fields", False) or getattr(het_source, "has_points", False)
    ):
        bind_heterogeneous_recharge(model, recharge_cfg)
        return

    payload = copy_runtime_payload(getattr(recharge_cfg, "values", 0.0))
    payload = convert_payload_to_m_per_s(
        payload,
        unit=str(getattr(recharge_cfg, "units", "mm/day")),
        label="flow.sinks_sources.recharge.values",
    )
    payload = sanitize_numeric_payload(payload)
    negative_to_evt = bool(getattr(recharge_cfg, "negative_to_evt", False))
    if hasattr(model, "nper"):
        payload, evt_payload = extract_evt_payload(model, payload, negative_to_evt)
        model._evt_rate_payload = evt_payload
    else:
        model._pending_negative_to_evt = negative_to_evt

    model.recharge = payload
    model.first_clim = getattr(
        recharge_cfg,
        "first_clim",
        model.first_clim if model.first_clim is not None else "mean",
    )


def bind_heterogeneous_recharge(model, recharge_cfg: object) -> None:
    """Store heterogeneous source for deferred discretization."""
    model._heterogeneous_recharge_source = recharge_cfg.heterogeneous_source
    model._heterogeneous_negative_to_evt = bool(getattr(recharge_cfg, "negative_to_evt", False))
    model._heterogeneous_interpolation_method = getattr(
        recharge_cfg, "interpolation_method", "nearest"
    )
    # Heterogeneous data comes from data-managers (always mm/day).
    # recharge_cfg.units has been normalized to "m/s" by Flow init.
    model._heterogeneous_source_unit = "mm/day"
    model.recharge = 0.0  # placeholder; replaced after solver_mesh construction
    model.first_clim = getattr(
        recharge_cfg,
        "first_clim",
        model.first_clim if model.first_clim is not None else "mean",
    )


def resolve_deferred_heterogeneous_recharge(model) -> None:
    """Discretize stored heterogeneous recharge after solver_mesh is available."""
    het_source = getattr(model, "_heterogeneous_recharge_source", None)
    if het_source is None:
        return

    sim_window = model.time_grid.window if model.time_grid is not None else None
    interp_method = getattr(model, "_heterogeneous_interpolation_method", "nearest")
    source_unit = getattr(model, "_heterogeneous_source_unit", "mm/day")
    use_structured = bool(getattr(model.solver_mesh, "is_structured", False))
    if use_structured:
        from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import (
            discretize_fields_on_sgrid,
            discretize_points_on_sgrid,
        )
    else:
        from hydromodpy.spatial.mesh.gmsh_grid.planar_forcing_discretization import (
            discretize_fields_on_planar_mesh,
            discretize_points_on_planar_mesh,
        )

        planar_mesh = getattr(model, "runtime_mesh_planar", None)
        if planar_mesh is None:
            from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D

            planar_mesh = GmshPlanarMesh2D.from_hydro_mesh(model.solver_mesh.planar_mesh)

    # Prefer fields; fall back to located points.
    if getattr(het_source, "has_fields", False):
        if use_structured:
            raw_arrays = discretize_fields_on_sgrid(
                load_result=het_source,
                sgrid=model.solver_mesh,
                nper=int(model.nper),
                simulation_window=sim_window,
                method=interp_method,
            )
        else:
            raw_arrays = discretize_fields_on_planar_mesh(
                load_result=het_source,
                planar_mesh=planar_mesh,
                nper=int(model.nper),
                simulation_window=sim_window,
                method=interp_method,
            )
    elif getattr(het_source, "has_points", False):
        if use_structured:
            raw_arrays = discretize_points_on_sgrid(
                load_result=het_source,
                sgrid=model.solver_mesh,
                nper=int(model.nper),
                simulation_window=sim_window,
                method=interp_method,
                source_unit=source_unit,
            )
        else:
            raw_arrays = discretize_points_on_planar_mesh(
                load_result=het_source,
                planar_mesh=planar_mesh,
                nper=int(model.nper),
                simulation_window=sim_window,
                method=interp_method,
                source_unit=source_unit,
            )
    else:
        model._heterogeneous_recharge_source = None
        return

    raw_arrays, evt_payload = extract_evt_payload_2d(
        raw_arrays,
        getattr(model, "_heterogeneous_negative_to_evt", False),
    )

    # `recharge_to_spd` handles Mapping {kper: ndarray(ncpl,)}.
    model.recharge = raw_arrays
    model._evt_rate_payload = evt_payload
    model._heterogeneous_recharge_source = None


def scalar_to_flat(model, value: float) -> np.ndarray:
    """Return flat (ncpl,) array filled with one scalar."""
    return np.full(int(model.ncpl), float(value), dtype=float)


def as_recharge_flat(model, value: object, *, kper: int | None = None) -> np.ndarray:
    """Coerce one recharge value to a flat (ncpl,) array."""
    if isinstance(value, Real) and not isinstance(value, bool):
        return scalar_to_flat(model, float(value))

    arr = np.asarray(value, dtype=float)
    if arr.ndim == 0:
        return scalar_to_flat(model, float(arr))
    if arr.ndim == 1:
        if arr.size == 0:
            return np.zeros(int(model.ncpl), dtype=float)
        if arr.size == int(model.ncpl):
            return arr.astype(float)
        if kper is None:
            return scalar_to_flat(model, float(arr[-1]))
        idx = min(max(int(kper), 0), int(arr.size) - 1)
        return scalar_to_flat(model, float(arr[idx]))
    if arr.ndim == 2:
        flat = arr.ravel()
        if flat.size == int(model.ncpl):
            return flat.astype(float)
        if flat.size == 0:
            return np.zeros(int(model.ncpl), dtype=float)
        return scalar_to_flat(model, float(flat[-1]))
    if arr.ndim >= 3:
        if kper is None:
            kper = 0
        idx = min(max(int(kper), 0), int(arr.shape[0]) - 1)
        flat = np.asarray(arr[idx], dtype=float).ravel()
        if flat.size == int(model.ncpl):
            return flat
        if flat.size == 0:
            return np.zeros(int(model.ncpl), dtype=float)
        return scalar_to_flat(model, float(flat[-1]))

    return np.zeros(int(model.ncpl), dtype=float)


def series_like_to_scalar(model, kper: int) -> float:
    return series_payload_value(model.recharge, kper, first_clim=model.first_clim)


def recharge_to_spd(model) -> dict[int, np.ndarray]:
    spd: dict[int, np.ndarray] = {}
    if isinstance(model.recharge, Mapping):
        for kper in range(model.nper):
            arr = model.recharge.get(kper)
            if arr is None:
                arr = 0.0
            spd[kper] = as_recharge_flat(model, arr, kper=kper)
        return spd

    if isinstance(model.recharge, Real) and not isinstance(model.recharge, bool):
        scalar = float(model.recharge)
        for kper in range(model.nper):
            spd[kper] = scalar_to_flat(model, scalar)
        return spd

    for kper in range(model.nper):
        scalar = series_like_to_scalar(model, kper)
        spd[kper] = scalar_to_flat(model, scalar)
    return spd


def empty_recharge_aux(model) -> dict[int, list[np.ndarray]]:
    return {k: [np.zeros(int(model.ncpl), dtype=float)] for k in range(int(model.nper))}


def finalize_pending_recharge_evt(model) -> None:
    """Apply deferred negative-recharge routing once `nper` is known."""
    if not getattr(model, "_pending_negative_to_evt", False):
        return
    model.recharge, model._evt_rate_payload = extract_evt_payload(model, model.recharge, True)
    model._pending_negative_to_evt = False


def build_evt_stress_period_data(
    model,
    solver_mesh,
    *,
    ocean_support_mask: np.ndarray,
    stream_support_mask: np.ndarray,
) -> dict[int, list[list[float]]] | None:
    """Build MF6 EVT stress-period data from recharge negatives routed to EVT."""
    evt_payload = getattr(model, "_evt_rate_payload", None)
    if evt_payload is None:
        return None

    top_flat = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
    dem_mask_flat = np.asarray(model.dem_mask, dtype=bool).reshape(-1)
    ocean_mask_flat = np.asarray(ocean_support_mask, dtype=bool).reshape(-1)
    stream_mask_flat = np.asarray(stream_support_mask, dtype=bool).reshape(-1)
    evt_depth = max(
        float(
            getattr(
                getattr(model.modflow_config, "process_specific", object()),
                "evt_extinction_depth",
                1.0,
            )
        ),
        1e-6,
    )

    evt_spd: dict[int, list[list[float]]] = {}
    for kper in range(int(model.nper)):
        raw_value = evt_payload.get(kper, 0.0) if isinstance(evt_payload, Mapping) else evt_payload
        rate_flat = as_recharge_flat(model, raw_value, kper=kper)
        period_cells: list[list[float]] = []
        for cid in range(int(model.ncpl)):
            if dem_mask_flat[cid] or ocean_mask_flat[cid] or stream_mask_flat[cid]:
                continue
            rate_value = float(rate_flat[cid])
            if rate_value <= 0.0:
                continue
            period_cells.append([0, cid, float(top_flat[cid]), rate_value, evt_depth])
        evt_spd[kper] = period_cells

    if any(len(v) > 0 for v in evt_spd.values()):
        return evt_spd
    return None


__all__ = [
    "as_recharge_flat",
    "bind_heterogeneous_recharge",
    "bind_recharge_from_flow",
    "build_evt_stress_period_data",
    "clip_negative_payload",
    "copy_runtime_payload",
    "empty_recharge_aux",
    "extract_evt_payload",
    "extract_evt_payload_2d",
    "finalize_pending_recharge_evt",
    "payload_has_negative_values",
    "recharge_to_spd",
    "resolve_deferred_heterogeneous_recharge",
    "sanitize_numeric_payload",
    "scalar_to_flat",
    "series_like_to_scalar",
    "series_payload_value",
]
