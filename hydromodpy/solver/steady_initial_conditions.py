"""Shared helpers for same-solver steady-state initial conditions."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from pydantic import TypeAdapter

from hydromodpy.core.units import FluxDensityMPerS
from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s
from hydromodpy.physics.flow.initial_conditions import (
    FlowICTop,
    FlowICTopOffset,
    FlowInitialCondition,
    FlowInitialConditions,
)
from hydromodpy.solver.initial_conditions import (
    head_initial_condition_type,
    initial_condition_field,
    resolve_head_initial_condition,
)

_RATE_ADAPTER: TypeAdapter[float] = TypeAdapter(FluxDensityMPerS)


@dataclass(frozen=True)
class SteadyStateInitialConditionStrategy:
    """Validated strategy payload for ``flow.ic.type='steady_state'``."""

    source: str = "mean_recharge"
    recharge_statistic: str | None = "time_mean"
    boundary_condition_policy: str = "first_period"
    rate_m_s: float | None = None
    """Rate the steady solve is held at, set only by ``source='prescribed'``."""


def flow_uses_steady_state_initial_condition(flow: object) -> bool:
    """Return whether the flow IC requests same-solver steady initialization."""
    head_ic = resolve_head_initial_condition(flow)
    return head_initial_condition_type(head_ic) == "steady_state"


def steady_state_initial_condition_strategy(
    flow: object,
) -> SteadyStateInitialConditionStrategy | None:
    """Return the validated steady-state IC strategy, or ``None`` if unused."""
    head_ic = resolve_head_initial_condition(flow)
    if head_initial_condition_type(head_ic) != "steady_state":
        return None

    source = str(
        initial_condition_field(head_ic, "source", "mean_recharge") or "mean_recharge"
    ).strip()
    boundary_policy = str(
        initial_condition_field(head_ic, "boundary_condition_policy", "first_period")
        or "first_period"
    ).strip()
    raw_rate = initial_condition_field(head_ic, "rate", None)

    if source not in {"recharge", "mean_recharge", "prescribed"}:
        raise ValueError("flow.ic.source must be 'recharge', 'mean_recharge', or 'prescribed'")
    if boundary_policy != "first_period":
        raise ValueError("flow.ic.boundary_condition_policy must be 'first_period'")

    if source == "prescribed":
        if raw_rate is None:
            raise ValueError(
                "flow.ic.rate is required when flow.ic.source='prescribed'; "
                "write the equilibrium rate with its unit, for example rate = '500 mm/yr'"
            )
        return SteadyStateInitialConditionStrategy(
            source=source,
            recharge_statistic=None,
            boundary_condition_policy=boundary_policy,
            rate_m_s=_RATE_ADAPTER.validate_python(raw_rate),
        )

    if raw_rate is not None:
        raise ValueError(
            "flow.ic.rate is only read when flow.ic.source='prescribed'; "
            f"got source={source!r}, which reads the recharge chronicle instead"
        )
    recharge_statistic = str(
        initial_condition_field(head_ic, "recharge_statistic", "time_mean") or "time_mean"
    ).strip()
    if recharge_statistic != "time_mean":
        raise ValueError("flow.ic.recharge_statistic must be 'time_mean'")

    return SteadyStateInitialConditionStrategy(
        source=source,
        recharge_statistic=recharge_statistic,
        boundary_condition_policy=boundary_policy,
    )


def apply_steady_state_initial_condition_strategy(
    flow: object,
    *,
    strategy: SteadyStateInitialConditionStrategy | None = None,
) -> None:
    """Apply the supported steady-state IC forcing strategy to a flow object."""
    strategy = strategy or steady_state_initial_condition_strategy(flow)
    if strategy is None:
        return
    sinks_sources = getattr(flow, "sinks_sources", None)
    if not isinstance(sinks_sources, dict):
        return
    recharge = sinks_sources.get("recharge")
    if recharge is None or not hasattr(recharge, "model_copy"):
        return
    if strategy.rate_m_s is None:
        sinks_sources["recharge"] = recharge.model_copy(update={"first_clim": "mean"})
        return

    # A prescribed rate must reach the solve whatever shape the payload has:
    # `first_clim` alone is ignored for a scalar payload and overridden by a
    # per-cell field, so the whole payload is replaced by the stated rate.
    payload_units = str(getattr(recharge, "units", "m/s") or "m/s")
    rate_in_payload_units = strategy.rate_m_s / factor_to_m_per_s(payload_units)
    sinks_sources["recharge"] = recharge.model_copy(
        update={
            "values": rate_in_payload_units,
            "first_clim": rate_in_payload_units,
            "heterogeneous_source": None,
        }
    )


def _flow_config_value(flow: object, name: str) -> object:
    value = getattr(flow, name, None)
    if value not in (None, ""):
        return value
    flow_config = getattr(flow, "config", None)
    return getattr(flow_config, name, "")


def steady_state_initialization_surface_interaction_model(flow: object) -> str | None:
    """Return the surface model override needed for an auxiliary steady solve."""
    runtime_backend = str(_flow_config_value(flow, "runtime_backend") or "").strip().lower()
    surface_model = str(_flow_config_value(flow, "surface_interaction_model") or "").strip().lower()
    if runtime_backend == "petsc" and surface_model == "ts_vi_obstacle":
        return "regularized_partition"
    return None


def _steady_state_initialization_head_guess(flow: object) -> FlowInitialCondition:
    """Return a robust initial head guess for the auxiliary steady solve."""
    runtime_backend = str(_flow_config_value(flow, "runtime_backend") or "").strip().lower()
    surface_model = str(_flow_config_value(flow, "surface_interaction_model") or "").strip().lower()
    if runtime_backend == "petsc" and surface_model == "vi_obstacle":
        return FlowICTopOffset(
            id="h",
            value=0.01,
            units="m",
            description=("Interior initial guess for steady-state initial-condition VI solve"),
        )
    return FlowICTop(
        id="h",
        units="m",
        description="Initial guess for steady-state initial-condition solve",
    )


def steady_flow_copy_for_initialization(flow: object) -> object:
    """Return a flow copy configured for the auxiliary steady solve."""
    strategy = steady_state_initial_condition_strategy(flow)
    steady_flow = copy.deepcopy(flow)
    steady_ic = FlowInitialConditions(h=_steady_state_initialization_head_guess(steady_flow))
    flow_config = getattr(steady_flow, "config", None)
    config_update = {"flow_regime": "steady", "ic": steady_ic}
    steady_surface_model = steady_state_initialization_surface_interaction_model(steady_flow)
    if steady_surface_model is not None:
        config_update["surface_interaction_model"] = steady_surface_model
        steady_flow.surface_interaction_model = steady_surface_model

    if flow_config is not None and hasattr(flow_config, "model_copy"):
        steady_flow.config = flow_config.model_copy(update=config_update)
    steady_flow.flow_regime = "steady"
    if hasattr(steady_flow, "set_initial_conditions"):
        steady_flow.set_initial_conditions(steady_ic)
    else:
        steady_flow.initial_conditions = steady_ic
        steady_flow.initial_condition_types = {"h": "top"}

    apply_steady_state_initial_condition_strategy(steady_flow, strategy=strategy)
    return steady_flow


__all__ = [
    "SteadyStateInitialConditionStrategy",
    "apply_steady_state_initial_condition_strategy",
    "flow_uses_steady_state_initial_condition",
    "steady_flow_copy_for_initialization",
    "steady_state_initialization_surface_interaction_model",
    "steady_state_initial_condition_strategy",
]
