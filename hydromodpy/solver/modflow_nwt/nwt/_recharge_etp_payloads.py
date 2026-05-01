"""RCH/EVT payload builders for the NWT flow-to-modflow adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.time import validate_recharge_coverage
from hydromodpy.core.units import convert_payload_to_m_per_s
from hydromodpy.physics.forcing.validation import (
    ensure_non_negative_numeric_payload,
    has_temporal_index,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt._chd_payloads import is_scalar_number

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
    flow_regime = str(regime).strip().lower()
    if flow_regime not in {"steady", "transient"}:
        raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")
    return flow_regime


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


def assemble_rch_data(
    *,
    payload: object,
    first_clim: object,
    flow_regime: str,
    nper: int,
) -> object:
    """Convert a recharge payload into the period-indexed structure."""
    ensure_non_negative_numeric_payload(payload, label="flow.sinks_sources.recharge.values")
    if isinstance(payload, Mapping):
        if flow_regime == "steady":
            if len(payload) == 0:
                raise ValueError(
                    "flow.sinks_sources.recharge.values mapping cannot be empty in steady regime."
                )
            return sum(payload.values()) / len(payload)
        return dict(payload)

    rch_dict: dict[int, object] = {}
    for kper in range(nper):
        if is_scalar_number(payload):
            rch_dict[kper] = float(payload)
        elif kper == 0:
            if first_clim == "mean":
                rch_dict[kper] = np.mean(payload)
            elif first_clim == "first":
                rch_dict[kper] = series_value(payload, 0)
            elif is_scalar_number(first_clim):
                rch_dict[kper] = float(first_clim)
            else:
                raise ValueError(
                    "flow.sinks_sources.recharge.first_clim must be "
                    "'mean', 'first', or a numeric value."
                )
        else:
            rch_dict[kper] = series_value(payload, kper)
    return rch_dict


def apply_first_clim_2d(
    *,
    raw_arrays: dict[int, np.ndarray],
    first_clim: object,
    flow_regime: str,
    nper: int,
    nrow: int,
    ncol: int,
) -> dict[int, np.ndarray]:
    """Apply ``first_clim`` policy to period 0 of 2-D recharge arrays."""
    ensure_non_negative_numeric_payload(raw_arrays, label="flow.sinks_sources.recharge.values")
    if flow_regime == "steady" or nper <= 1:
        if raw_arrays:
            all_vals = np.stack(list(raw_arrays.values()), axis=0)
            mean_arr = np.mean(all_vals, axis=0)
        else:
            mean_arr = np.zeros((nrow, ncol), dtype=float)
        return {0: mean_arr}

    result = dict(raw_arrays)
    if 0 not in result:
        return result

    if first_clim == "mean" and len(raw_arrays) > 0:
        all_vals = np.stack(list(raw_arrays.values()), axis=0)
        result[0] = np.mean(all_vals, axis=0)
    elif first_clim == "first":
        pass
    elif is_scalar_number(first_clim):
        result[0] = np.full((nrow, ncol), float(first_clim), dtype=float)

    return result


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

    return apply_first_clim_2d(
        raw_arrays=raw_arrays,
        first_clim=getattr(recharge_cfg, "first_clim", "mean"),
        flow_regime=resolve_flow_regime(adapter.flow),
        nper=adapter.nper,
        nrow=adapter.nrow,
        ncol=adapter.ncol,
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
        flow_regime=resolve_flow_regime(adapter.flow),
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
    return assemble_rch_data(
        payload=recharge_payload,
        first_clim=recharge_cfg.first_clim,
        flow_regime=resolve_flow_regime(adapter.flow),
        nper=adapter.nper,
    )


def build_etp_payload(
    adapter: FlowToModflowAdapter,
) -> tuple[dict[int, object] | None, float, float]:
    """Build the EVT payload from ``flow.sinks_sources["etp"]``."""
    active = getattr(adapter.flow, "active_sinks_sources", [])
    if "etp" not in active:
        return None, 2.0, 1.0

    sinks_sources = getattr(adapter.flow, "sinks_sources", {})
    etp_cfg = sinks_sources.get("etp") if isinstance(sinks_sources, Mapping) else None
    if etp_cfg is None:
        return None, 2.0, 1.0

    surface_offset_q = getattr(etp_cfg, "surface_offset", None)
    surface_offset = 2.0 if surface_offset_q is None else float(surface_offset_q.to("m").magnitude)
    extinction_depth_q = getattr(etp_cfg, "extinction_depth", None)
    extinction_depth = (
        1.0 if extinction_depth_q is None else float(extinction_depth_q.to("m").magnitude)
    )

    het_source = getattr(etp_cfg, "heterogeneous_source", None)
    if het_source is not None and (
        getattr(het_source, "has_fields", False) or getattr(het_source, "has_points", False)
    ):
        return (
            build_heterogeneous_etp_payload(adapter, etp_cfg),
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
        flow_regime=resolve_flow_regime(adapter.flow),
        nper=adapter.nper,
    )
    if not isinstance(evt_spd, Mapping):
        evt_spd = {0: float(evt_spd)}
    return evt_spd, surface_offset, extinction_depth


__all__ = [
    "apply_first_clim_2d",
    "assemble_rch_data",
    "build_etp_payload",
    "build_heterogeneous_etp_payload",
    "build_heterogeneous_recharge_payload",
    "build_recharge_payload",
    "clip_etp_to_non_negative",
    "copy_payload",
    "discretize_heterogeneous_source",
    "resolve_flow_regime",
    "series_value",
]
