"""The head a run starts from, as arrays on a backend's own grid.

A ``HeadRule`` gives the array of the top, the top minus an offset, the bottom
or one value. A ``SteadyStart`` and a ``CyclicStart`` start from the top too,
because the state their auxiliary solve returns replaces that array once it has
run. The head of a ``PriorState`` is copied cell by cell and its inactive cells
take the top of the grid. Two checks complete the module: whether a head lies
between the bottom and the top, and whether two spin-up cycles ended on the
same state.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.model.initial.state import (
    CyclicStart,
    HeadRule,
    PriorState,
    SolvedState,
    SteadyStart,
)

_START_FROM_THE_TOP = HeadRule("top")


def head_rule_of(initial: HeadRule | SteadyStart | CyclicStart) -> HeadRule:
    """The rule the start array is built from before any auxiliary solve.

    A steady or cyclic start begins at the top: the state its auxiliary solve
    returns is set over this array afterwards. A state read from a run or a
    solve is not a rule, and is refused by name.
    """
    if isinstance(initial, HeadRule):
        return initial
    if isinstance(initial, SteadyStart | CyclicStart):
        return _START_FROM_THE_TOP
    if isinstance(initial, PriorState | SolvedState):
        raise TypeError(
            f"A {type(initial).__name__} holds its head already; it is set as it is, "
            "not resolved by a rule."
        )
    raise TypeError(f"Not a start state: {initial!r}")


def build_head_initial_condition_array(
    initial: HeadRule | SteadyStart | CyclicStart,
    *,
    top: Any,
    bottom: Any,
    target_shape: tuple[int, ...],
    location_prefix: str = "flow.ic",
) -> np.ndarray:
    """Resolve a start rule into a float array of ``target_shape``, in metres.

    ``top`` and ``bottom`` broadcast to ``target_shape``. ``custom`` fills the
    array with its value whatever the grid.
    """
    rule = head_rule_of(initial)
    if rule.kind == "custom":
        return np.full(target_shape, float(rule.value_m), dtype=float)
    if rule.kind == "top":
        base = np.asarray(top, dtype=float)
    elif rule.kind == "top_offset":
        base = np.asarray(top, dtype=float) - float(rule.value_m)
    else:
        base = np.asarray(bottom, dtype=float)
    try:
        return np.broadcast_to(base, target_shape).astype(float, copy=True)
    except ValueError as exc:
        raise ValueError(
            f"{location_prefix} resolved shape {base.shape} cannot broadcast to {target_shape}."
        ) from exc


def restart_start_heads(head: Any, *, nlay: int, ncpl: int, top: Any) -> np.ndarray:
    """Return the start heads ``(nlay, ncpl)`` of a restart, inactive cells at the top.

    ``head`` is the last head of the earlier run with NaN on its inactive
    cells (``PriorState.head``). It must have this run's shape, because the
    heads are copied cell by cell. MODFLOW ignores the start head of an
    inactive cell but needs a finite one, so each NaN takes the top of its
    cell, as the default start does. ``head`` is not changed.
    """
    start = np.array(head, dtype=float, copy=True)
    if start.shape != (nlay, ncpl):
        raise ValueError(
            f"restart_from: prior head shape {start.shape} does not match this run "
            f"({nlay}, {ncpl}). Use the same [mesh] settings as the prior run so the "
            f"cell count is identical between the two runs."
        )
    top_flat = np.asarray(top, dtype=float).reshape(-1)
    for ilay in range(nlay):
        missing = ~np.isfinite(start[ilay])
        start[ilay][missing] = top_flat[missing]
    return start


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


__all__ = [
    "build_head_initial_condition_array",
    "cycles_have_settled",
    "head_rule_of",
    "restart_start_heads",
    "summarize_head_initial_condition_bounds",
]
