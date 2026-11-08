"""MF6 initial-condition and rewet builders."""

from __future__ import annotations

import numpy as np

from hydromodpy.model.initial.heads import (
    build_head_initial_condition_array,
    restart_start_heads,
)
from hydromodpy.model.initial.state import PriorState, SolvedState
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    apply_side_boundary_start_heads,
    ocean_chd_support_mask,
    resolve_ocean_boundary_series,
    resolve_stream_boundary_series,
    stream_chd_support_mask,
)


def rewet_is_enabled(model) -> bool:
    """Return whether MF6 rewetting is enabled for the current run."""
    runtime = getattr(model.modflow_config, "runtime", None)
    enable_rewet = getattr(runtime, "mf6_enable_rewet", None)
    return bool(enable_rewet) if enable_rewet is not None else False


def build_start_heads(model, solver_mesh) -> np.ndarray:
    """Build MF6 starting heads as flat (nlay, ncpl) for DISV.

    ``Model.initial`` says where the heads come from. A ``SolvedState`` is the
    head an auxiliary solve returned and is set as it is, without the constant
    heads laid over it. A ``PriorState`` is the last head of an earlier run, with
    the top of the grid in its inactive cells. The other states start from the
    rule they name, the top for a steady or a cyclic start, whose auxiliary
    solve replaces the array once it has run. The constant heads of the ocean,
    the stream and the sides are laid over every state but a ``SolvedState``.
    """
    ncpl = solver_mesh.n_cells
    top_flat = solver_mesh.top  # (ncpl,)
    botm_flat = solver_mesh.botm  # (nlay, ncpl)
    nlay = int(model.nlay)
    initial = model.inputs.initial

    if isinstance(initial, SolvedState):
        return _solved_start_heads(initial, nlay=nlay, ncpl=int(ncpl))
    if isinstance(initial, PriorState):
        strt = restart_start_heads(initial.head, nlay=nlay, ncpl=int(ncpl), top=top_flat)
    else:
        strt = build_head_initial_condition_array(
            initial,
            top=top_flat,
            bottom=botm_flat[-1],
            target_shape=(nlay, int(ncpl)),
            location_prefix="flow.ic",
        )
    ocean_series = resolve_ocean_boundary_series(model)
    ocean_mask = ocean_chd_support_mask(model, ocean_series)
    if np.any(ocean_mask):
        for ilay in range(nlay):
            strt[ilay][ocean_mask] = float(ocean_series[0])
    stream_series = resolve_stream_boundary_series(model)
    stream_mask = stream_chd_support_mask(model, stream_series)
    if np.any(stream_mask):
        for ilay in range(nlay):
            strt[ilay][stream_mask] = float(stream_series[0])
    return apply_side_boundary_start_heads(model, strt)


def _solved_start_heads(initial: SolvedState, *, nlay: int, ncpl: int) -> np.ndarray:
    """The head of an auxiliary solve as a writable ``(nlay, ncpl)`` array."""
    if initial.head.size != nlay * ncpl:
        raise ValueError(
            f"The start head of a {initial.solver} solve holds {initial.head.size} value(s), "
            f"and this run has {nlay} layer(s) of {ncpl} cell(s)."
        )
    return np.array(initial.head, dtype=float, copy=True).reshape(nlay, ncpl)


def resolve_rewet_npf_options(
    model,
    solver_mesh,
) -> tuple[list[object] | None, np.ndarray | None]:
    """Return MF6 NPF rewet options and the matching WETDRY array."""
    runtime = getattr(model.modflow_config, "runtime", None)
    if not rewet_is_enabled(model):
        return None, None

    wetdry_value = abs(float(runtime.mf6_rewet_wetdry))
    if wetdry_value <= 0.0:
        raise ValueError("modflow6.runtime.mf6_rewet_wetdry must be > 0 when rewetting is enabled.")

    # FloPy injects the REWET keyword itself and expects only the labeled payload.
    # rewet_is_enabled() above guarantees runtime is set, so read the fields directly
    # (their defaults live on the Pydantic runtime config, not here).
    rewet_record = [
        "WETFCT",
        float(runtime.mf6_rewet_wetfct),
        "IWETIT",
        int(runtime.mf6_rewet_iwetit),
        "IHDWET",
        int(runtime.mf6_rewet_ihdwet),
    ]
    wetdry = np.where(
        np.asarray(solver_mesh.inactive_mask, dtype=bool),
        0.0,
        wetdry_value,
    ).astype(float)
    return rewet_record, wetdry


__all__ = [
    "build_start_heads",
    "resolve_rewet_npf_options",
    "rewet_is_enabled",
]
