"""Shared helpers for same-solver steady-state initial conditions."""

from __future__ import annotations

import copy

from hydromodpy.physics.flow.initial_conditions import (
    FlowInitialCondition,
    FlowInitialConditions,
)


def flow_uses_steady_state_initial_condition(flow: object) -> bool:
    """Return whether the flow IC requests same-solver steady initialization."""
    initial_conditions = getattr(flow, "initial_conditions", None)
    head_ic = (
        None if initial_conditions is None else getattr(initial_conditions, "h", None)
    )
    return str(getattr(head_ic, "type", "")).strip().lower() == "steady_state"


def steady_flow_copy_for_initialization(flow: object) -> object:
    """Return a flow copy configured for the auxiliary steady solve."""
    steady_flow = copy.deepcopy(flow)
    steady_ic = FlowInitialConditions(
        h=FlowInitialCondition(
            id="h",
            type="top",
            units="m",
            description="Initial guess for steady-state initial-condition solve",
        )
    )
    flow_config = getattr(steady_flow, "config", None)
    if flow_config is not None and hasattr(flow_config, "model_copy"):
        steady_flow.config = flow_config.model_copy(
            update={"flow_regime": "steady", "ic": steady_ic}
        )
    steady_flow.flow_regime = "steady"
    if hasattr(steady_flow, "set_initial_conditions"):
        steady_flow.set_initial_conditions(steady_ic)
    else:
        steady_flow.initial_conditions = steady_ic
        steady_flow.initial_condition_types = {"h": "top"}

    sinks_sources = getattr(steady_flow, "sinks_sources", None)
    if isinstance(sinks_sources, dict):
        recharge = sinks_sources.get("recharge")
        if recharge is not None and hasattr(recharge, "model_copy"):
            sinks_sources["recharge"] = recharge.model_copy(
                update={"first_clim": "mean"}
            )
    return steady_flow


__all__ = [
    "flow_uses_steady_state_initial_condition",
    "steady_flow_copy_for_initialization",
]
