"""The rate a steady stress period takes: one rule for every solver.

A steady period stands for the long-term state a run starts from. It does not
take the rate of its own dates. ``first_clim`` picks its rate from the rates of
all the periods of the run:

- ``"mean"``: the time mean of the per-period rates, each weighted by the length
  of its period, so the steady period receives the mean volume of the record;
- ``"first"``: the rate of period 0;
- a number: that rate.

Every steady period takes that rate, and only the steady periods. A transient
period keeps its own rate, whatever its index. The steady periods are every
period of a steady run, and period 0 of a transient run whose first period is
steady. The rule holds for every form of the rates: one value per period or one
array per period.

A net recharge can be negative. With ``negative_to_evt``, it is split into a
recharge part ``max(R, 0)`` and a deficit part ``max(-R, 0)``. On a steady
period, ``first_clim`` acts on each part with the same rule. A number ``F``
gives the parts ``max(F, 0)`` and ``max(-F, 0)``. So the net rate of a steady
period, recharge minus deficit, is always the one ``first_clim`` states: the
mean of the net rates, the net rate of period 0, or ``F``. A negative ``F``
gives a steady deficit even when no period of the record is negative.

A run of one period may read a record longer than itself. That period's own
rate is the mean of the record, and when it is steady ``first_clim`` reads the
record itself: ``"first"`` is the first value of the record. A record that holds
the rates of a longer run, as the auxiliary steady solve of ``flow.ic`` reads,
weighs them by the lengths of that run's periods. A record with no such lengths
counts each value once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from numbers import Real

import numpy as np

from hydromodpy.model.forcing.types import FirstClimKeyword

FIRST_CLIM_KEYWORDS: tuple[str, ...] = ("mean", "first")


def _is_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def normalize_first_clim(value: object) -> FirstClimKeyword | float:
    """Normalize a ``first_clim`` policy: 'mean'/'first' or a numeric scalar."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized not in FIRST_CLIM_KEYWORDS:
            raise ValueError("first_clim must be 'mean', 'first', or a numeric value.")
        return normalized
    if not _is_number(value):
        raise TypeError("first_clim must be 'mean', 'first', or a numeric value.")
    return float(value)


def _check_first_clim(first_clim: object) -> None:
    if first_clim in FIRST_CLIM_KEYWORDS or _is_number(first_clim):
        return
    raise ValueError(f"first_clim must be 'mean', 'first', or a numeric value; got {first_clim!r}.")


def _is_steady(steady: Sequence[bool] | np.ndarray, kper: int) -> bool:
    flags = np.asarray(steady, dtype=bool).reshape(-1)
    return bool(flags[kper]) if 0 <= kper < flags.size else False


def _period_weights(durations: Sequence[float] | np.ndarray, size: int) -> np.ndarray:
    """Return one positive finite length per rate, or refuse them."""
    weights = np.asarray(durations, dtype=float).reshape(-1)
    if weights.size != size:
        raise ValueError(f"{size} period rates need {size} period lengths, got {weights.size}.")
    if not np.all(np.isfinite(weights) & (weights > 0.0)):
        raise ValueError(f"a period length must be positive and finite, got {weights.tolist()}.")
    return weights


def steady_rate(
    rates: Sequence[object], first_clim: object, *, durations: Sequence[float] | np.ndarray
) -> np.ndarray:
    """Return the rate of a steady period, from the rates of every period.

    ``rates`` holds one scalar or one array per period, in period order, and
    ``durations`` the length of each period, in any unit. The result has the
    shape of one entry.
    """
    _check_first_clim(first_clim)
    if len(rates) == 0:
        raise ValueError("steady_rate needs the rate of at least one period.")
    weights = _period_weights(durations, len(rates))
    arrays = np.broadcast_arrays(*[np.asarray(rate, dtype=float) for rate in rates])
    stacked = np.stack(arrays, axis=0)
    if first_clim == "mean":
        return np.average(stacked, axis=0, weights=weights)
    if first_clim == "first":
        return np.array(stacked[0], dtype=float, copy=True)
    return np.full(stacked.shape[1:], float(first_clim), dtype=float)


def apply_first_clim(
    rates_by_period: Mapping[int, object],
    *,
    steady: Sequence[bool] | np.ndarray,
    first_clim: object,
    durations: Sequence[float] | np.ndarray,
) -> dict[int, np.ndarray]:
    """Give every steady period the rate ``first_clim`` states.

    Transient periods keep their own rate. ``rates_by_period`` maps each period
    index to a scalar or an array, and ``durations`` holds the length of every
    period of the run, indexed like those keys.
    """
    periods = sorted(int(k) for k in rates_by_period)
    rates = {k: np.asarray(rates_by_period[k], dtype=float) for k in periods}
    out = {k: np.array(rates[k], dtype=float, copy=True) for k in periods}
    steady_periods = [k for k in periods if _is_steady(steady, k)]
    if not steady_periods:
        return out
    lengths = np.asarray(durations, dtype=float).reshape(-1)
    if periods[-1] >= lengths.size:
        raise ValueError(f"period {periods[-1]} has no length among {lengths.size} periods.")
    value = steady_rate(
        [rates[k] for k in periods], first_clim, durations=[lengths[k] for k in periods]
    )
    for k in steady_periods:
        out[k] = np.array(value, dtype=float, copy=True)
    return out


def first_clim_on_part(
    parts_by_period: Mapping[int, object],
    *,
    steady: Sequence[bool] | np.ndarray,
    first_clim: object,
    sign: float,
    durations: Sequence[float] | np.ndarray,
) -> dict[int, np.ndarray]:
    """Apply ``first_clim`` to one part of a split net recharge.

    ``sign`` is ``+1`` for the recharge part and ``-1`` for the deficit part.
    A keyword acts on the part itself; a number ``F`` gives ``max(sign * F, 0)``.
    """
    if not _is_number(first_clim):
        return apply_first_clim(
            parts_by_period, steady=steady, first_clim=first_clim, durations=durations
        )
    periods = sorted(int(k) for k in parts_by_period)
    out = {k: np.array(parts_by_period[k], dtype=float, copy=True) for k in periods}
    value = max(float(sign) * float(first_clim), 0.0)
    for k in periods:
        if _is_steady(steady, k):
            out[k] = np.full(out[k].shape, value, dtype=float)
    return out


def first_clim_sets_a_deficit(
    first_clim: object, steady: Sequence[bool] | np.ndarray | None
) -> bool:
    """Return True when a negative ``first_clim`` sets the rate of a steady period.

    That steady period needs a deficit part even if the record has no negative
    value.
    """
    if not _is_number(first_clim) or float(first_clim) >= 0.0 or steady is None:
        return False
    return bool(np.any(np.asarray(steady, dtype=bool)))


def one_period_rate(
    record: Sequence[float] | np.ndarray,
    *,
    steady: bool,
    first_clim: object,
    durations: Sequence[float] | np.ndarray | None = None,
) -> float:
    """Return the own rate of the only period of a run, from a longer record.

    The mean of the record; the first value when the period is steady and
    ``first_clim`` is ``"first"``. :func:`apply_first_clim` then gives the
    same rate, so ``"first"`` stays the first value of the record.
    ``durations`` holds the length of each value when the record has them; a
    record without counts each value once.
    """
    values = np.asarray(record, dtype=float).reshape(-1)
    if values.size == 0:
        raise ValueError("one_period_rate needs at least one value.")
    if steady and first_clim == "first":
        return float(values[0])
    if durations is None:
        return float(np.mean(values))
    return float(np.average(values, weights=_period_weights(durations, values.size)))


def split_net_recharge(
    rates_by_period: Mapping[int, object],
    *,
    steady: Sequence[bool] | np.ndarray,
    first_clim: object,
    durations: Sequence[float] | np.ndarray,
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """Split a net recharge into its recharge part and its deficit part.

    Returns ``(recharge, deficit)``, both non-negative, keyed like the input.
    A transient period keeps its own split. A steady period takes, on each
    part, the rate ``first_clim`` states (module docstring).
    """
    _check_first_clim(first_clim)
    periods = sorted(int(k) for k in rates_by_period)
    net = {k: np.asarray(rates_by_period[k], dtype=float) for k in periods}
    recharge = {k: np.maximum(net[k], 0.0) for k in periods}
    deficit = {k: np.maximum(-net[k], 0.0) for k in periods}
    return (
        first_clim_on_part(
            recharge, steady=steady, first_clim=first_clim, sign=1.0, durations=durations
        ),
        first_clim_on_part(
            deficit, steady=steady, first_clim=first_clim, sign=-1.0, durations=durations
        ),
    )


def steady_flags(*, nper: int, flow_regime: str, first_period_steady: bool) -> np.ndarray:
    """Return which periods a MODFLOW run solves steady.

    Every period of a steady run; period 0 of a transient run whose first
    period is steady; none otherwise.
    """
    if str(flow_regime).strip().lower() == "steady":
        return np.ones(int(nper), dtype=bool)
    flags = np.zeros(int(nper), dtype=bool)
    if first_period_steady and int(nper) > 0:
        flags[0] = True
    return flags


__all__ = [
    "FIRST_CLIM_KEYWORDS",
    "apply_first_clim",
    "first_clim_on_part",
    "first_clim_sets_a_deficit",
    "normalize_first_clim",
    "one_period_rate",
    "split_net_recharge",
    "steady_flags",
    "steady_rate",
]
