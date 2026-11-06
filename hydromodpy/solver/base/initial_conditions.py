"""The head a run starts from, for every solver.

The array of a ``flow.ic`` (top, top offset, bottom, custom value), and the two
strategies that replace it with the state of an auxiliary solve of the same
solver: a steady solve (``steady_state``) or repeated cycles of the run's
period (``spinup_cyclic``).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from pydantic import TypeAdapter

from hydromodpy.core.units import FluxDensityMPerS
from hydromodpy.core.units.quantities import factor_to_m_per_s
from hydromodpy.core.units.types import LengthMeters
from hydromodpy.physics.flow.initial_conditions import (
    FlowICTop,
    FlowICTopOffset,
    FlowInitialCondition,
    FlowInitialConditions,
    known_ic_types,
)

HEAD_INITIAL_CONDITION_TYPES = tuple(sorted(known_ic_types()))
"""The accepted ``flow.ic.kind`` values, read off the union that defines them."""

_TYPES_STARTING_FROM_THE_TOP = frozenset({"top", "steady_state", "spinup_cyclic"})
"""Types whose resolved array is the water table at the topographic surface.

For the last two it is only the guess their auxiliary solve begins at; what they
produce replaces it once that solve has run."""
_HEAD_INITIAL_CONDITION_TYPES_TEXT = ", ".join(HEAD_INITIAL_CONDITION_TYPES)


def initial_condition_field(initial_condition: object, field_name: str, default=None):
    """Read one field from either a mapping payload or a typed IC object."""
    if isinstance(initial_condition, Mapping):
        return initial_condition.get(field_name, default)
    return getattr(initial_condition, field_name, default)


def resolve_head_initial_condition(model_or_flow: object):
    """Return the head initial-condition payload from a model or flow object."""
    flow = getattr(model_or_flow, "flow", model_or_flow)
    initial_conditions = getattr(flow, "initial_conditions", None)
    if initial_conditions is None:
        return None
    if isinstance(initial_conditions, Mapping):
        return initial_conditions.get("h")
    return getattr(initial_conditions, "h", None)


def head_initial_condition_type(initial_condition: object) -> str:
    """Return the normalized head IC type token."""
    return str(initial_condition_field(initial_condition, "kind", "")).strip().lower()


def _head_initial_condition_value_m(
    initial_condition: object,
    *,
    location_prefix: str,
    ic_type: str,
) -> float:
    """Return the scalar head IC value in meters or raise a contract error."""
    head_value = initial_condition_field(initial_condition, "value")
    if head_value is None:
        raise ValueError(
            f"{location_prefix}.value is required when {location_prefix}.kind='{ic_type}'"
        )
    return float(getattr(head_value, "magnitude", head_value))


def build_head_initial_condition_array(
    initial_condition: object,
    *,
    top: Any,
    bottom: Any,
    target_shape: tuple[int, ...],
    location_prefix: str = "flow.ic",
) -> np.ndarray:
    """
    Resolve the canonical flow head IC into an array shaped for one backend.

    ``steady_state`` and ``spinup_cyclic`` both resolve to the top surface here,
    because the array this returns is only the guess their auxiliary solves start
    from: the state they actually produce is injected afterwards by the same-solver
    initialization path, once it has run. A type added to the union without a branch
    here lands in the final ``else`` and is refused by name, which is what a reader
    wants over a silent fallback to the surface.
    """
    ic_type = head_initial_condition_type(initial_condition)
    if ic_type in _TYPES_STARTING_FROM_THE_TOP:
        base = np.asarray(top, dtype=float)
    elif ic_type == "top_offset":
        offset_m = _head_initial_condition_value_m(
            initial_condition,
            location_prefix=location_prefix,
            ic_type=ic_type,
        )
        base = np.asarray(top, dtype=float) - offset_m
    elif ic_type == "bottom":
        base = np.asarray(bottom, dtype=float)
    elif ic_type == "custom":
        head_m = _head_initial_condition_value_m(
            initial_condition,
            location_prefix=location_prefix,
            ic_type=ic_type,
        )
        return np.full(target_shape, head_m, dtype=float)
    else:
        raise ValueError(
            f"{location_prefix}.kind must be one of: {_HEAD_INITIAL_CONDITION_TYPES_TEXT}"
        )

    try:
        return np.broadcast_to(base, target_shape).astype(float, copy=True)
    except ValueError as exc:
        raise ValueError(
            f"{location_prefix} resolved shape {base.shape} cannot broadcast to {target_shape}."
        ) from exc


def summarize_head_initial_condition_bounds(
    *,
    head: Any,
    top: Any,
    bottom: Any,
    location_prefix: str = "flow.ic",
) -> dict[str, int | float | bool | None]:
    """Summarize whether an initial head field lies inside bottom/top bounds."""
    head_arr = np.asarray(head, dtype=float)
    try:
        top_arr = np.broadcast_to(np.asarray(top, dtype=float), head_arr.shape)
        bottom_arr = np.broadcast_to(np.asarray(bottom, dtype=float), head_arr.shape)
    except ValueError as exc:
        raise ValueError(
            f"{location_prefix} bounds cannot broadcast to head shape {head_arr.shape}."
        ) from exc

    finite = np.isfinite(head_arr) & np.isfinite(top_arr) & np.isfinite(bottom_arr)
    nonfinite_count = int(head_arr.size - np.count_nonzero(finite))
    below_gap = np.zeros(head_arr.shape, dtype=float)
    above_gap = np.zeros(head_arr.shape, dtype=float)
    below_gap[finite] = np.maximum(bottom_arr[finite] - head_arr[finite], 0.0)
    above_gap[finite] = np.maximum(head_arr[finite] - top_arr[finite], 0.0)

    finite_head = head_arr[finite]
    below_count = int(np.count_nonzero(below_gap > 0.0))
    above_count = int(np.count_nonzero(above_gap > 0.0))
    return {
        "cell_count": int(head_arr.size),
        "finite_cell_count": int(np.count_nonzero(finite)),
        "nonfinite_cell_count": nonfinite_count,
        "below_bottom_count": below_count,
        "above_top_count": above_count,
        "max_below_bottom_m": float(np.max(below_gap)) if below_gap.size else 0.0,
        "max_above_top_m": float(np.max(above_gap)) if above_gap.size else 0.0,
        "head_min_m": float(np.min(finite_head)) if finite_head.size else None,
        "head_max_m": float(np.max(finite_head)) if finite_head.size else None,
        "within_bounds": below_count == 0 and above_count == 0 and nonfinite_count == 0,
    }


_RATE_ADAPTER: TypeAdapter[float] = TypeAdapter(FluxDensityMPerS)
_LENGTH_ADAPTER: TypeAdapter[float] = TypeAdapter(LengthMeters)


@dataclass(frozen=True)
class SteadyStateInitialConditionStrategy:
    """Validated strategy payload for ``flow.ic.kind='steady_state'``."""

    source: str = "mean_recharge"
    recharge_statistic: str | None = "time_mean"
    boundary_condition_policy: str = "first_period"
    rate_m_s: float | None = None
    """Rate the steady solve is held at, set only by ``source='prescribed'``."""


@dataclass(frozen=True)
class CyclicSpinupStrategy:
    """Validated payload for ``flow.ic.kind='spinup_cyclic'``."""

    max_cycles: int = 4
    tol_head_m: float = 0.01
    first_cycle_from: str = "top"


def flow_uses_cyclic_spinup(flow: object) -> bool:
    """Return whether the flow IC asks for the run's period to be repeated."""
    head_ic = resolve_head_initial_condition(flow)
    return head_initial_condition_type(head_ic) == "spinup_cyclic"


def cyclic_spinup_strategy(flow: object) -> CyclicSpinupStrategy | None:
    """Return the validated cyclic-spinup strategy, or ``None`` if unused."""
    head_ic = resolve_head_initial_condition(flow)
    if head_initial_condition_type(head_ic) != "spinup_cyclic":
        return None
    max_cycles = int(initial_condition_field(head_ic, "max_cycles", 4) or 4)
    if max_cycles < 1:
        raise ValueError("flow.ic.max_cycles has to be at least one cycle.")
    raw_tol = initial_condition_field(head_ic, "tol_head", 0.01)
    tol = _LENGTH_ADAPTER.validate_python(raw_tol if raw_tol is not None else 0.01)
    if tol <= 0.0:
        raise ValueError(
            "flow.ic.tol_head has to be strictly positive: it is the head change below "
            "which two cycles count as the same state."
        )
    first = str(initial_condition_field(head_ic, "first_cycle_from", "top") or "top").strip()
    if first not in {"top", "steady_state"}:
        raise ValueError("flow.ic.first_cycle_from must be 'top' or 'steady_state'")
    return CyclicSpinupStrategy(
        max_cycles=max_cycles, tol_head_m=float(tol), first_cycle_from=first
    )


def cycles_have_settled(previous: object, current: object, *, tol_head_m: float) -> bool:
    """Tell whether two consecutive cycles ended on the same state.

    The measure is the largest change anywhere, not a mean: a basin settled on
    average while one compartment still drifts has not settled, and averaging is how
    that gets missed. Cells that are inactive in either cycle are left out; a cell
    that is dry in one and wet in the other is a change and counts.
    """
    if previous is None or current is None:
        return False
    before = np.asarray(previous, dtype=float).ravel()
    after = np.asarray(current, dtype=float).ravel()
    if before.shape != after.shape:
        raise ValueError(
            f"two cycles returned {before.size} and {after.size} head value(s); they have "
            "to be the same mesh."
        )
    both_finite = np.isfinite(before) & np.isfinite(after)
    if not both_finite.any():
        return False
    if np.any(np.isfinite(before) != np.isfinite(after)):
        return False
    return bool(np.max(np.abs(after[both_finite] - before[both_finite])) <= float(tol_head_m))


def cyclic_flow_copy_for_initialization(flow: object) -> object:
    """Return a flow copy for one spin-up cycle, with the cycling REMOVED.

    This is the whole reason the function exists. A cycle runs an auxiliary model
    built from a copy of the real flow, and that copy still asked for a cyclic
    spin-up, so the auxiliary model re-entered the same hook and spun up cycles of
    its own. Measured before it was fixed: a three-cycle spin-up ran 143 solves and
    was stopped by the machine, not by the loop. The copy therefore starts from the
    top surface, exactly as the steady initialization's copy does, and the caller
    overwrites that with the previous cycle's heads.
    """
    cycle_flow = copy.deepcopy(flow)
    cycle_ic = FlowInitialConditions(
        h=FlowICTop(id="h", units="m", description="Start of one cyclic spin-up cycle")
    )
    flow_config = getattr(cycle_flow, "config", None)
    if flow_config is not None and hasattr(flow_config, "model_copy"):
        cycle_flow.config = flow_config.model_copy(update={"ic": cycle_ic})
    if hasattr(cycle_flow, "set_initial_conditions"):
        cycle_flow.set_initial_conditions(cycle_ic)
    else:
        cycle_flow.initial_conditions = cycle_ic
        cycle_flow.initial_condition_types = {"h": "top"}
    if flow_uses_cyclic_spinup(cycle_flow):
        raise AssertionError(
            "a spin-up cycle's flow still asks for a cyclic spin-up; it would recurse."
        )
    return cycle_flow


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

    # A prescribed rate must reach every period of the auxiliary solve, not
    # only its steady periods, so the whole payload is replaced by the stated
    # rate; `first_clim` repeats it for the steady periods.
    payload_units = str(getattr(recharge, "units", "m/s") or "m/s")
    rate_in_payload_units = strategy.rate_m_s / factor_to_m_per_s(payload_units)
    sinks_sources["recharge"] = recharge.model_copy(
        update={
            "values": rate_in_payload_units,
            "first_clim": rate_in_payload_units,
            "heterogeneous_source": None,
        }
    )


_RUNTIME_KEY_OF = {"runtime_backend": "backend"}


def _flow_config_value(flow: object, name: str) -> object:
    """Return a setting of the flow, read from its ``[flow.runtime]`` when it has none."""
    value = getattr(flow, name, None)
    if value not in (None, ""):
        return value
    runtime = getattr(getattr(flow, "config", None), "runtime", None)
    return getattr(runtime, _RUNTIME_KEY_OF.get(name, name), "")


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
        if flow_config is not None and hasattr(flow_config, "runtime"):
            config_update["runtime"] = flow_config.runtime.model_copy(
                update={"surface_interaction_model": steady_surface_model}
            )
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
    "CyclicSpinupStrategy",
    "HEAD_INITIAL_CONDITION_TYPES",
    "SteadyStateInitialConditionStrategy",
    "apply_steady_state_initial_condition_strategy",
    "build_head_initial_condition_array",
    "cycles_have_settled",
    "cyclic_flow_copy_for_initialization",
    "cyclic_spinup_strategy",
    "flow_uses_cyclic_spinup",
    "flow_uses_steady_state_initial_condition",
    "head_initial_condition_type",
    "initial_condition_field",
    "resolve_head_initial_condition",
    "steady_flow_copy_for_initialization",
    "steady_state_initial_condition_strategy",
    "steady_state_initialization_surface_interaction_model",
    "summarize_head_initial_condition_bounds",
]
