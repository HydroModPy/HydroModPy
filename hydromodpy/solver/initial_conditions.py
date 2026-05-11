"""Shared helpers for solver head initial-condition resolution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

HEAD_INITIAL_CONDITION_TYPES = (
    "top",
    "top_offset",
    "bottom",
    "custom",
    "steady_state",
)
HEAD_INITIAL_CONDITION_TYPES_TEXT = ", ".join(HEAD_INITIAL_CONDITION_TYPES)


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
    return str(initial_condition_field(initial_condition, "type", "")).strip().lower()


def head_initial_condition_value_m(
    initial_condition: object,
    *,
    location_prefix: str,
    ic_type: str,
) -> float:
    """Return the scalar head IC value in meters or raise a contract error."""
    head_value = initial_condition_field(initial_condition, "value")
    if head_value is None:
        raise ValueError(
            f"{location_prefix}.value is required when {location_prefix}.type='{ic_type}'"
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

    ``steady_state`` uses the top surface as the auxiliary steady-solve initial
    guess. The materialized steady heads are injected later by each same-solver
    initialization path.
    """
    ic_type = head_initial_condition_type(initial_condition)
    if ic_type in {"top", "steady_state"}:
        base = np.asarray(top, dtype=float)
    elif ic_type == "top_offset":
        offset_m = head_initial_condition_value_m(
            initial_condition,
            location_prefix=location_prefix,
            ic_type=ic_type,
        )
        base = np.asarray(top, dtype=float) - offset_m
    elif ic_type == "bottom":
        base = np.asarray(bottom, dtype=float)
    elif ic_type == "custom":
        head_m = head_initial_condition_value_m(
            initial_condition,
            location_prefix=location_prefix,
            ic_type=ic_type,
        )
        return np.full(target_shape, head_m, dtype=float)
    else:
        raise ValueError(
            f"{location_prefix}.type must be one of: {HEAD_INITIAL_CONDITION_TYPES_TEXT}"
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


__all__ = [
    "HEAD_INITIAL_CONDITION_TYPES",
    "HEAD_INITIAL_CONDITION_TYPES_TEXT",
    "build_head_initial_condition_array",
    "head_initial_condition_type",
    "head_initial_condition_value_m",
    "initial_condition_field",
    "resolve_head_initial_condition",
    "summarize_head_initial_condition_bounds",
]
