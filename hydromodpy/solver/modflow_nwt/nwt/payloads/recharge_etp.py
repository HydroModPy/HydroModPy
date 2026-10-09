"""RCH/EVT payload builders for the NWT flow-to-modflow adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.time import validate_recharge_coverage
from hydromodpy.core.units import convert_payload_to_m_per_s
from hydromodpy.physics.flow.regime import normalize_flow_regime
from hydromodpy.physics.forcing.steady_periods import apply_first_clim, steady_flags
from hydromodpy.physics.forcing.validation import (
    ensure_finite_numeric_payload,
    ensure_non_negative_numeric_payload,
    has_temporal_index,
)
from hydromodpy.solver.modflow_common.recharge_evt_routing import route_negative_recharge_to_evt
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt.payloads.chd import is_scalar_number

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import (
        FlowToModflowAdapter,
    )


def discretize_heterogeneous_source(
    het_source: object,
    *,
    solver_mesh: SolverMesh,
    nper: int,
    simulation_window: object,
    method: str = "nearest",
    source_unit: str = "m/s",
) -> dict[int, np.ndarray]:
    """Dispatch heterogeneous discretization for fields or located points."""
    from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import (
        discretize_fields_on_sgrid,
        discretize_points_on_sgrid,
    )

    if getattr(het_source, "has_fields", False):
        return discretize_fields_on_sgrid(
            load_result=het_source,
            sgrid=solver_mesh,
            nper=nper,
            simulation_window=simulation_window,
            method=method,
        )

    if getattr(het_source, "has_points", False):
        return discretize_points_on_sgrid(
            load_result=het_source,
            sgrid=solver_mesh,
            nper=nper,
            simulation_window=simulation_window,
            method=method,
            source_unit=source_unit,
        )

    nrow = solver_mesh.nrow
    ncol = solver_mesh.ncol
    return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(nper)}


def copy_payload(payload: object) -> object:
    """Return a defensive copy of a payload."""
    if isinstance(payload, Mapping):
        return dict(payload)
    if hasattr(payload, "copy"):
        try:
            return payload.copy()
        except Exception:
            return payload
    return payload


def series_value(payload: object, kper: int):
    """Read one stress-period value from a heterogeneous payload container."""
    if hasattr(payload, "iloc"):
        value = payload.iloc[kper]
        try:
            return value.values[0]
        except Exception:
            return value
    return payload[kper]


def resolve_flow_regime(flow: object) -> str:
    """Resolve and validate the flow regime string from the flow object."""
    flow_cfg = getattr(flow, "config", None)
    regime = None
    if flow_cfg is not None:
        regime = getattr(flow_cfg, "flow_regime", None)
    if regime is None:
        regime = getattr(flow, "flow_regime", None)
    if regime is None:
        raise ValueError("flow.flow_regime is required to build recharge payloads.")
    return normalize_flow_regime(regime)


def clip_etp_to_non_negative(payload: object) -> object:
    """Clip a homogeneous ETP payload to non-negative values."""
    if isinstance(payload, Mapping):
        return {k: max(0.0, float(v)) for k, v in payload.items()}
    if hasattr(payload, "clip"):
        return payload.clip(lower=0.0)
    if isinstance(payload, np.ndarray):
        return np.maximum(payload, 0.0)
    if isinstance(payload, list):
        return [max(0.0, float(v)) for v in payload]
    return max(0.0, float(payload))


def payload_has_negative_values(payload: object) -> bool:
    """Return True when a recharge payload contains at least one negative value."""
    if isinstance(payload, Mapping):
        return any(payload_has_negative_values(value) for value in payload.values())
    if is_scalar_number(payload):
        return float(payload) < 0.0
    arr = np.asarray(payload, dtype=float)
    return bool(np.any(arr < 0.0))


def clip_negative_payload(payload: object) -> object:
    """Clip negative recharge values to zero for RCH compatibility."""
    if isinstance(payload, Mapping):
        return {key: clip_negative_payload(value) for key, value in payload.items()}
    if is_scalar_number(payload):
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


def extract_negative_recharge_evt_payload(
    *,
    payload: object,
    nper: int,
    steady: object,
    first_clim: object = "mean",
) -> tuple[object, dict[int, object] | None]:
    """Route negative recharge values to EVT and keep RCH non-negative.

    ``payload`` holds the own rate of every period, before ``first_clim``. A
    transient period keeps its own split; a steady period takes the
    ``first_clim`` rate on each part (``route_negative_recharge_to_evt``, shared
    with MODFLOW 6). Without a negative value, nothing is routed.
    """
    if not payload_has_negative_values(payload):
        return payload, None

    if isinstance(payload, Mapping):
        normalized = {int(k): np.asarray(v, dtype=float) for k, v in payload.items()}
    else:
        values = np.asarray(payload, dtype=float)
        normalized = {
            kper: (values if values.ndim == 0 else np.asarray(series_value(values, kper)))
            for kper in range(int(nper))
        }
    clipped, deficit = route_negative_recharge_to_evt(
        normalized, steady=steady, first_clim=first_clim
    )
    return _scalars_as_floats(clipped), _scalars_as_floats(deficit)


def _scalars_as_floats(by_period: Mapping[int, np.ndarray]) -> dict[int, object]:
    """Return 0-d arrays as plain floats, the form the NWT packages take."""
    return {
        int(kper): (float(value) if np.ndim(value) == 0 else value)
        for kper, value in by_period.items()
    }


def steady_period_flags(adapter: FlowToModflowAdapter) -> np.ndarray:
    """Return which periods the NWT run solves steady.

    The flags the DIS package receives when the solver passed them; otherwise
    the same rule rebuilt from the flow regime and ``first_period_steady``.
    """
    steady = getattr(adapter, "steady", None)
    if steady is not None:
        return np.asarray(steady, dtype=bool).reshape(-1)
    from hydromodpy.solver.modflow_grid.discretization_temporal import (
        resolve_first_period_steady,
    )

    return steady_flags(
        nper=int(adapter.nper),
        flow_regime=resolve_flow_regime(adapter.flow),
        first_period_steady=resolve_first_period_steady(flow=adapter.flow),
    )


def merge_evt_payloads(
    primary: dict[int, object] | None,
    extra: dict[int, object] | None,
    *,
    nper: int,
) -> dict[int, object] | None:
    """Add two EVT stress-period payloads."""
    if primary is None:
        return extra
    if extra is None:
        return primary
    merged: dict[int, object] = {}
    for kper in range(int(nper)):
        left = primary.get(kper, 0.0)
        right = extra.get(kper, 0.0)
        merged[kper] = np.asarray(left, dtype=float) + np.asarray(right, dtype=float)
    return merged


def _own_rates_by_period(payload: object, *, nper: int) -> dict[int, np.ndarray]:
    """Return the own rate of every period of a recharge or ETP payload."""
    if isinstance(payload, Mapping):
        return {int(k): np.asarray(v, dtype=float) for k, v in payload.items()}
    if is_scalar_number(payload):
        return {kper: np.asarray(float(payload)) for kper in range(int(nper))}
    return {kper: np.asarray(series_value(payload, kper), dtype=float) for kper in range(int(nper))}


def assemble_rch_data(
    *,
    payload: object,
    first_clim: object,
    steady: object,
    nper: int,
    allow_negative: bool = False,
) -> dict[int, object]:
    """Convert a recharge payload into the period-indexed structure.

    Every steady period takes the rate ``first_clim`` states, a transient
    period keeps its own (:mod:`hydromodpy.physics.forcing.steady_periods`).
    """
    if allow_negative:
        ensure_finite_numeric_payload(payload, label="flow.sinks_sources.recharge.values")
    else:
        ensure_non_negative_numeric_payload(payload, label="flow.sinks_sources.recharge.values")
    if isinstance(payload, Mapping) and len(payload) == 0:
        raise ValueError("flow.sinks_sources.recharge.values mapping cannot be empty.")
    rows = _own_rates_by_period(payload, nper=nper)
    return _scalars_as_floats(apply_first_clim(rows, steady=steady, first_clim=first_clim))


def apply_first_clim_2d(
    *,
    raw_arrays: dict[int, np.ndarray],
    first_clim: object,
    steady: object,
    nper: int,
    nrow: int,
    ncol: int,
    allow_negative: bool = False,
) -> dict[int, np.ndarray]:
    """Give every steady period the ``first_clim`` array, keep the transient ones."""
    if allow_negative:
        ensure_finite_numeric_payload(raw_arrays, label="flow.sinks_sources.recharge.values")
    else:
        ensure_non_negative_numeric_payload(raw_arrays, label="flow.sinks_sources.recharge.values")
    if not raw_arrays:
        return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(int(nper))}
    return apply_first_clim(raw_arrays, steady=steady, first_clim=first_clim)


def build_heterogeneous_recharge_payload(
    adapter: FlowToModflowAdapter,
    recharge_cfg: object,
) -> dict[int, np.ndarray]:
    """Discretize gridded FieldRecords onto the MODFLOW grid."""
    het_source = recharge_cfg.heterogeneous_source
    interp_method = getattr(recharge_cfg, "interpolation_method", "nearest")
    source_unit = "mm/day"
    raw_arrays = discretize_heterogeneous_source(
        het_source,
        solver_mesh=adapter.solver_mesh,
        nper=adapter.nper,
        simulation_window=adapter.simulation_window,
        method=interp_method,
        source_unit=source_unit,
    )

    negative_to_evt = bool(getattr(recharge_cfg, "negative_to_evt", False))
    first_clim = getattr(recharge_cfg, "first_clim", "mean")
    steady = steady_period_flags(adapter)
    if negative_to_evt:
        ensure_finite_numeric_payload(raw_arrays, label="flow.sinks_sources.recharge.values")
        payload, evt_payload = extract_negative_recharge_evt_payload(
            payload=raw_arrays,
            nper=adapter.nper,
            steady=steady,
            first_clim=first_clim,
        )
        adapter._negative_recharge_evt_spd = evt_payload
        if evt_payload is not None:
            return payload
    return apply_first_clim_2d(
        raw_arrays=raw_arrays,
        first_clim=first_clim,
        steady=steady,
        nper=adapter.nper,
        nrow=adapter.nrow,
        ncol=adapter.ncol,
        allow_negative=False,
    )


def build_heterogeneous_etp_payload(
    adapter: FlowToModflowAdapter,
    etp_cfg: object,
) -> dict[int, np.ndarray]:
    """Discretize gridded FieldRecords / points onto the MODFLOW grid."""
    het_source = etp_cfg.heterogeneous_source
    interp_method = getattr(etp_cfg, "interpolation_method", "nearest")
    raw_arrays = discretize_heterogeneous_source(
        het_source,
        solver_mesh=adapter.solver_mesh,
        nper=adapter.nper,
        simulation_window=adapter.simulation_window,
        method=interp_method,
        source_unit="mm/day",
    )
    rate_arrays = apply_first_clim_2d(
        raw_arrays=raw_arrays,
        first_clim=getattr(etp_cfg, "first_clim", "mean"),
        steady=steady_period_flags(adapter),
        nper=adapter.nper,
        nrow=adapter.nrow,
        ncol=adapter.ncol,
    )
    return {
        kper: np.maximum(np.asarray(arr, dtype=float), 0.0) for kper, arr in rate_arrays.items()
    }


def build_recharge_payload(adapter: FlowToModflowAdapter) -> object | None:
    """Build the RCH payload from ``flow.sinks_sources["recharge"]``."""
    active = getattr(adapter.flow, "active_sinks_sources", [])
    if "recharge" not in active:
        return None

    sinks_sources = getattr(adapter.flow, "sinks_sources", {})
    recharge_cfg = sinks_sources.get("recharge") if isinstance(sinks_sources, Mapping) else None
    if recharge_cfg is None:
        return None

    het_source = getattr(recharge_cfg, "heterogeneous_source", None)
    if het_source is not None and (
        getattr(het_source, "has_fields", False) or getattr(het_source, "has_points", False)
    ):
        return build_heterogeneous_recharge_payload(adapter, recharge_cfg)

    recharge_payload = copy_payload(recharge_cfg.values)
    if has_temporal_index(recharge_payload):
        validate_recharge_coverage(recharge_payload, adapter.simulation_window)
    recharge_payload = convert_payload_to_m_per_s(
        recharge_payload,
        unit=str(getattr(recharge_cfg, "units", "mm/day")),
        label="flow.sinks_sources.recharge.values",
    )
    negative_to_evt = bool(getattr(recharge_cfg, "negative_to_evt", False))
    steady = steady_period_flags(adapter)
    if negative_to_evt:
        ensure_finite_numeric_payload(recharge_payload, label="flow.sinks_sources.recharge.values")
        rch_data, evt_payload = extract_negative_recharge_evt_payload(
            payload=_own_rates_by_period(recharge_payload, nper=adapter.nper),
            nper=adapter.nper,
            steady=steady,
            first_clim=recharge_cfg.first_clim,
        )
        adapter._negative_recharge_evt_spd = evt_payload
        if evt_payload is not None:
            return rch_data
    return assemble_rch_data(
        payload=recharge_payload,
        first_clim=recharge_cfg.first_clim,
        steady=steady,
        nper=adapter.nper,
        allow_negative=False,
    )


def build_etp_payload(
    adapter: FlowToModflowAdapter,
) -> tuple[dict[int, object] | None, float, float]:
    """Build the EVT payload from ``flow.sinks_sources["etp"]``."""
    negative_evt_spd = getattr(adapter, "_negative_recharge_evt_spd", None)
    active = getattr(adapter.flow, "active_sinks_sources", [])
    if "etp" not in active:
        return negative_evt_spd, 2.0, 1.0

    sinks_sources = getattr(adapter.flow, "sinks_sources", {})
    etp_cfg = sinks_sources.get("etp") if isinstance(sinks_sources, Mapping) else None
    if etp_cfg is None:
        return negative_evt_spd, 2.0, 1.0

    surface_offset_q = getattr(etp_cfg, "surface_offset", None)
    surface_offset = 2.0 if surface_offset_q is None else float(surface_offset_q.to("m").magnitude)
    extinction_depth_q = getattr(etp_cfg, "extinction_depth", None)
    extinction_depth = 1.0 if extinction_depth_q is None else float(extinction_depth_q)

    het_source = getattr(etp_cfg, "heterogeneous_source", None)
    if het_source is not None and (
        getattr(het_source, "has_fields", False) or getattr(het_source, "has_points", False)
    ):
        etp_spd = build_heterogeneous_etp_payload(adapter, etp_cfg)
        return (
            merge_evt_payloads(etp_spd, negative_evt_spd, nper=adapter.nper),
            surface_offset,
            extinction_depth,
        )

    etp_payload = copy_payload(etp_cfg.values)
    etp_payload = convert_payload_to_m_per_s(
        etp_payload,
        unit=str(getattr(etp_cfg, "units", "mm/day")),
        label="flow.sinks_sources.etp.values",
    )
    etp_payload = clip_etp_to_non_negative(etp_payload)
    evt_spd = assemble_rch_data(
        payload=etp_payload,
        first_clim=etp_cfg.first_clim,
        steady=steady_period_flags(adapter),
        nper=adapter.nper,
    )
    return (
        merge_evt_payloads(dict(evt_spd), negative_evt_spd, nper=adapter.nper),
        surface_offset,
        extinction_depth,
    )


__all__ = [
    "apply_first_clim_2d",
    "assemble_rch_data",
    "build_etp_payload",
    "build_heterogeneous_etp_payload",
    "build_heterogeneous_recharge_payload",
    "build_recharge_payload",
    "clip_etp_to_non_negative",
    "clip_negative_payload",
    "copy_payload",
    "discretize_heterogeneous_source",
    "extract_negative_recharge_evt_payload",
    "merge_evt_payloads",
    "payload_has_negative_values",
    "resolve_flow_regime",
    "series_value",
    "steady_period_flags",
]
