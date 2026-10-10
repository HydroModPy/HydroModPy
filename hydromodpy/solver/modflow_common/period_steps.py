"""Put the saved time steps of a MODFLOW run on its stress periods.

A stamp closes its period. The store keeps one slice per stress period: the
state at the end of the period, and every flux as its mean over the period.
MODFLOW cuts a period into time steps (NSTP, ATS) and writes one record per
saved step. These helpers say which saved step closes each period, and which
saved steps a stamp averages, with which weight: the step length over the
length of the steps the stamp closes. A stamp that closes a single step keeps
that step, bit for bit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

StepKey = tuple[int, int]
"""``(kstp, kper)`` of one saved step, both on the same base (0 or 1)."""


@dataclass(frozen=True)
class StampSteps:
    """The saved steps one stamp closes, in time order.

    ``stamp`` indexes the stamps, ``positions`` the saved steps. ``weights``
    are the step lengths over their sum, so they add up to one.
    """

    stamp: int
    positions: tuple[int, ...]
    weights: tuple[float, ...]


def period_end_positions(step_keys: Sequence[StepKey]) -> list[int]:
    """Position of the last saved step of each stress period, in time order.

    The state of a period is read there: a stamp closes its period.
    """
    keys = [(int(kstp), int(kper)) for kstp, kper in step_keys]
    ends: list[int] = []
    for position, (_kstp, kper) in enumerate(keys):
        if position + 1 == len(keys) or keys[position + 1][1] != kper:
            ends.append(position)
    return ends


def step_lengths_from_times(times: Sequence[float]) -> np.ndarray:
    """Length of each saved step from the simulated time at its end.

    The run starts at time zero. A step saved after unsaved ones takes their
    length too, which is the length of what it closes.
    """
    ends = np.asarray(times, dtype=float).reshape(-1)
    starts = np.concatenate([[0.0], ends[:-1]])
    return ends - starts


def group_steps_by_stamp(
    step_keys: Sequence[StepKey],
    step_lengths: Sequence[float],
    stamp_keys: Sequence[StepKey],
) -> list[StampSteps]:
    """Group the saved steps under the stamp that closes them.

    A step belongs to the first stamp at or after it in time. ``step_keys``
    and ``stamp_keys`` are ``(kstp, kper)`` in time order. Steps after the
    last stamp close no period and are left out, and a stamp no saved step
    reaches gets an empty group. A stamp that closes one step gets the
    weight 1.0 exactly.
    """
    keys = [(int(kstp), int(kper)) for kstp, kper in step_keys]
    lengths = np.asarray(step_lengths, dtype=float).reshape(-1)
    if lengths.size != len(keys):
        raise ValueError(
            f"{len(keys)} saved steps but {lengths.size} step lengths; "
            "each saved step needs its length."
        )
    order = [(int(kper), int(kstp)) for kstp, kper in stamp_keys]
    groups: list[StampSteps] = []
    position = 0
    for stamp, closing in enumerate(order):
        start = position
        while position < len(keys) and (keys[position][1], keys[position][0]) <= closing:
            position += 1
        groups.append(
            StampSteps(
                stamp=stamp,
                positions=tuple(range(start, position)),
                weights=_weights(lengths[start:position]),
            )
        )
    return groups


@dataclass(frozen=True)
class BudgetFileSteps:
    """The saved steps of a FloPy budget file and where each record sits.

    ``keys`` are the 0-based ``(kstp, kper)`` in file order, ``lengths``
    their step length and ``ends`` the simulated time at their end, in the
    model time unit. ``record`` maps a stripped record name and a step key to
    the position of its first record, so a record is read by position, with
    no scan of the index per read.
    """

    keys: tuple[StepKey, ...]
    lengths: tuple[float, ...]
    ends: tuple[float, ...]
    record: dict[tuple[str, StepKey], int]

    def stamps(self) -> list[StampSteps]:
        """Group the steps under the last saved step of each stress period."""
        closing = [self.keys[i] for i in period_end_positions(self.keys)]
        return group_steps_by_stamp(self.keys, self.lengths, closing)


def budget_file_steps(cbb: Any) -> BudgetFileSteps:
    """Index a FloPy ``CellBudgetFile`` by saved step.

    The step length is the ``delt`` of the compact record header. A
    non-compact file carries none: its lengths are NaN, which a stamp that
    closes a single step does without and a stamp that closes several
    refuses.
    """
    records = cbb.recordarray
    keys: list[StepKey] = []
    lengths: list[float] = []
    ends: list[float] = []
    record: dict[tuple[str, StepKey], int] = {}
    known: set[StepKey] = set()
    for idx, row in enumerate(records):
        key = (int(row["kstp"]) - 1, int(row["kper"]) - 1)
        if key not in known:
            known.add(key)
            keys.append(key)
            compact = int(row["imeth"]) > 0
            delt = float(row["delt"])
            lengths.append(delt if compact and delt > 0.0 else float("nan"))
            ends.append(float(row["totim"]) if compact else float("nan"))
        text = row["text"]
        name = (text.decode() if isinstance(text, bytes) else str(text)).strip()
        record.setdefault((name, key), idx)
    return BudgetFileSteps(
        keys=tuple(keys), lengths=tuple(lengths), ends=tuple(ends), record=record
    )


def group_ends_by_stamp(
    step_ends: Sequence[float], stamp_ends: Sequence[float]
) -> list[StampSteps]:
    """Group steps under the stamp that closes them, by simulated time.

    For outputs that carry a time and no step key, such as an observation
    file. A step belongs to the first stamp at or after its end; the step
    lengths are the differences of the ends, from time zero. The match
    allows a relative 1e-8, the rounding of a time written as text.
    """
    ends = np.asarray(step_ends, dtype=float).reshape(-1)
    lengths = step_lengths_from_times(ends)
    groups: list[StampSteps] = []
    position = 0
    for stamp, closing in enumerate(stamp_ends):
        limit = float(closing) + 1e-8 * max(1.0, abs(float(closing)))
        start = position
        while position < ends.size and ends[position] <= limit:
            position += 1
        groups.append(
            StampSteps(
                stamp=stamp,
                positions=tuple(range(start, position)),
                weights=_weights(lengths[start:position]),
            )
        )
    return groups


def _weights(lengths: np.ndarray) -> tuple[float, ...]:
    if lengths.size == 0:
        return ()
    if lengths.size == 1:
        return (1.0,)
    total = float(lengths.sum())
    if not np.isfinite(total) or total <= 0.0 or np.any(lengths < 0.0):
        raise ValueError(
            f"a stamp closes several steps but their lengths are {lengths.tolist()}; "
            "a period mean needs the length of each step (a non-compact MODFLOW "
            "budget file carries none)."
        )
    return tuple(float(length) / total for length in lengths)


def weighted_period_mean(values: Sequence[np.ndarray], weights: Sequence[float]) -> np.ndarray:
    """Return the step-length-weighted mean of the step values of one period.

    A step left out of ``values`` counts as zero. One step of weight 1.0
    returns its value unchanged, so a run of one step per period stores
    exactly what MODFLOW wrote.
    """
    if len(values) != len(weights) or not values:
        raise ValueError(f"{len(values)} step values for {len(weights)} weights.")
    if len(values) == 1 and float(weights[0]) == 1.0:
        return np.asarray(values[0])
    total = float(weights[0]) * np.asarray(values[0], dtype="float64")
    for weight, value in zip(weights[1:], values[1:], strict=True):
        total = total + float(weight) * np.asarray(value, dtype="float64")
    return total


def weighted_period_scalar(values: Sequence[float], weights: Sequence[float]) -> float:
    """Scalar form of :func:`weighted_period_mean`."""
    if len(values) == 1 and float(weights[0]) == 1.0:
        return float(values[0])
    return float(weighted_period_mean([np.float64(v) for v in values], weights))


BALANCE_TOTALS: tuple[str, ...] = ("total_in", "total_out", "storage_in", "storage_out")


def period_mean_balance(
    rows: Sequence[dict[str, float]], weights: Sequence[float]
) -> dict[str, float]:
    """Mean of the listing budget rows a stamp closes, weighted by step length.

    Each row holds the :data:`BALANCE_TOTALS`, ``in_minus_out`` and
    ``percent_error``. One row keeps its totals and discrepancy unchanged.
    Over several, the totals are averaged and the discrepancy is recomputed
    the way MODFLOW computes it, ``100 (in - out) / ((in + out) / 2)``, with
    ``in - out`` from its own listing column: it is printed at its own
    magnitude, where the difference of the rounded totals is noise.
    """
    if len(rows) == 1 and float(weights[0]) == 1.0:
        row = rows[0]
        return {key: row[key] for key in (*BALANCE_TOTALS, "percent_error")}
    mean = {
        key: weighted_period_scalar([row[key] for row in rows], weights) for key in BALANCE_TOTALS
    }
    in_minus_out = weighted_period_scalar([row["in_minus_out"] for row in rows], weights)
    half_sum = 0.5 * (mean["total_in"] + mean["total_out"])
    mean["percent_error"] = 100.0 * in_minus_out / half_sum if half_sum != 0.0 else 0.0
    return mean


__all__ = [
    "BALANCE_TOTALS",
    "BudgetFileSteps",
    "StampSteps",
    "StepKey",
    "budget_file_steps",
    "group_ends_by_stamp",
    "group_steps_by_stamp",
    "period_end_positions",
    "period_mean_balance",
    "step_lengths_from_times",
    "weighted_period_mean",
    "weighted_period_scalar",
]
