"""MF6 initial-condition and rewet builders."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    apply_side_boundary_start_heads,
    ocean_chd_support_mask,
    resolve_ocean_boundary_series,
    resolve_stream_boundary_series,
    stream_chd_support_mask,
)


def resolve_head_initial_condition(model):
    """Return the head initial-condition payload from the flow configuration."""
    initial_conditions = getattr(model.flow, "initial_conditions", None)
    if initial_conditions is None:
        return None
    if isinstance(initial_conditions, Mapping):
        return initial_conditions.get("h")
    return getattr(initial_conditions, "h", None)


def initial_condition_field(initial_condition, field_name: str, default=None):
    """Read one field from either a mapping payload or a typed IC object."""
    if isinstance(initial_condition, Mapping):
        return initial_condition.get(field_name, default)
    return getattr(initial_condition, field_name, default)


def rewet_is_enabled(model) -> bool:
    """Return whether MF6 rewetting is enabled for the current run."""
    runtime = getattr(model.modflow_config, "runtime", None)
    enable_rewet = getattr(runtime, "mf6_enable_rewet", None)
    return bool(enable_rewet) if enable_rewet is not None else False


def build_start_heads(model, solver_mesh) -> np.ndarray:
    """Build MF6 starting heads as flat (nlay, ncpl) for DISV."""
    h_ic = resolve_head_initial_condition(model)
    if h_ic is None:
        raise ValueError("flow.initial_conditions.h is required for Modflow6 pre_processing")

    ncpl = solver_mesh.n_cells
    top_flat = solver_mesh.top  # (ncpl,)
    botm_flat = solver_mesh.botm  # (nlay, ncpl)
    initial_type = str(initial_condition_field(h_ic, "type", "")).strip().lower()
    if initial_type == "top":
        strt = np.tile(top_flat, (model.nlay, 1))
    elif initial_type == "top_offset":
        head_value = initial_condition_field(h_ic, "value")
        if head_value is None:
            raise ValueError("flow.initial_conditions.h.value is required for top_offset")
        offset_m = float(getattr(head_value, "magnitude", head_value))
        strt = np.tile(top_flat - offset_m, (model.nlay, 1))
    elif initial_type in {"bot", "bottom"}:
        strt = np.tile(botm_flat[-1], (model.nlay, 1))
    elif initial_type == "custom":
        head_value = initial_condition_field(h_ic, "value")
        head_magnitude = getattr(head_value, "magnitude", head_value)
        strt = np.full(
            (model.nlay, ncpl),
            float(head_magnitude),
            dtype=float,
        )
    else:
        raise ValueError(
            "flow.initial_conditions.h.type must be one of: top, top_offset, bottom, custom"
        )
    ocean_series = resolve_ocean_boundary_series(model)
    ocean_mask = ocean_chd_support_mask(model, ocean_series)
    if np.any(ocean_mask):
        for ilay in range(int(model.nlay)):
            strt[ilay][ocean_mask] = float(ocean_series[0])
    stream_series = resolve_stream_boundary_series(model)
    stream_mask = stream_chd_support_mask(model, stream_series)
    if np.any(stream_mask):
        for ilay in range(int(model.nlay)):
            strt[ilay][stream_mask] = float(stream_series[0])
    return apply_side_boundary_start_heads(model, strt)


def resolve_rewet_npf_options(
    model,
    solver_mesh,
) -> tuple[list[object] | None, np.ndarray | None]:
    """Return MF6 NPF rewet options and the matching WETDRY array."""
    runtime = getattr(model.modflow_config, "runtime", None)
    if not rewet_is_enabled(model):
        return None, None

    wetdry_value = abs(float(getattr(runtime, "mf6_rewet_wetdry", 0.1)))
    if wetdry_value <= 0.0:
        raise ValueError("modflow6.runtime.mf6_rewet_wetdry must be > 0 when rewetting is enabled.")

    # FloPy injects the REWET keyword itself and expects only the labeled payload.
    rewet_record = [
        "WETFCT",
        float(getattr(runtime, "mf6_rewet_wetfct", 0.1)),
        "IWETIT",
        int(getattr(runtime, "mf6_rewet_iwetit", 1)),
        "IHDWET",
        int(getattr(runtime, "mf6_rewet_ihdwet", 0)),
    ]
    wetdry = np.where(
        np.asarray(solver_mesh.inactive_mask, dtype=bool),
        0.0,
        wetdry_value,
    ).astype(float)
    return rewet_record, wetdry


__all__ = [
    "build_start_heads",
    "initial_condition_field",
    "resolve_head_initial_condition",
    "resolve_rewet_npf_options",
    "rewet_is_enabled",
]
