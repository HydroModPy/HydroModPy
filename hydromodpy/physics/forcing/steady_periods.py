"""The rate a steady stress period takes: one rule for every solver.

A steady period stands for the long-term state a run starts from. It does not
take the rate of its own dates. ``first_clim`` picks its rate from the rates of
all the periods of the run:

- ``"mean"``: the mean of the per-period rates, one weight per period;
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
mean of the net rates, the net rate of period 0, or ``F``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from numbers import Real

import numpy as np

FIRST_CLIM_KEYWORDS: tuple[str, ...] = ("mean", "first")


def _is_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _check_first_clim(first_clim: object) -> None:
    if first_clim in FIRST_CLIM_KEYWORDS or _is_number(first_clim):
        return
    raise ValueError(f"first_clim must be 'mean', 'first', or a numeric value; got {first_clim!r}.")


def _is_steady(steady: Sequence[bool] | np.ndarray, kper: int) -> bool:
    flags = np.asarray(steady, dtype=bool).reshape(-1)
    return bool(flags[kper]) if 0 <= kper < flags.size else False


def steady_rate(rates: Sequence[object], first_clim: object) -> np.ndarray:
    """Return the rate of a steady period, from the rates of every period.

    ``rates`` holds one scalar or one array per period, in period order. The
    result has the shape of one entry.
    """
    _check_first_clim(first_clim)
    if len(rates) == 0:
        raise ValueError("steady_rate needs the rate of at least one period.")
    arrays = np.broadcast_arrays(*[np.asarray(rate, dtype=float) for rate in rates])
    stacked = np.stack(arrays, axis=0)
    if first_clim == "mean":
        return np.mean(stacked, axis=0)
    if first_clim == "first":
        return np.array(stacked[0], dtype=float, copy=True)
    return np.full(stacked.shape[1:], float(first_clim), dtype=float)


def apply_first_clim(
    rates_by_period: Mapping[int, object],
    *,
    steady: Sequence[bool] | np.ndarray,
    first_clim: object,
) -> dict[int, np.ndarray]:
    """Give every steady period the rate ``first_clim`` states.

    Transient periods keep their own rate. ``rates_by_period`` maps each period
    index to a scalar or an array.
    """
    periods = sorted(int(k) for k in rates_by_period)
    rates = {k: np.asarray(rates_by_period[k], dtype=float) for k in periods}
    out = {k: np.array(rates[k], dtype=float, copy=True) for k in periods}
    steady_periods = [k for k in periods if _is_steady(steady, k)]
    if not steady_periods:
        return out
    value = steady_rate([rates[k] for k in periods], first_clim)
    for k in steady_periods:
        out[k] = np.array(value, dtype=float, copy=True)
    return out


def first_clim_on_part(
    parts_by_period: Mapping[int, object],
    *,
    steady: Sequence[bool] | np.ndarray,
    first_clim: object,
    sign: float,
) -> dict[int, np.ndarray]:
    """Apply ``first_clim`` to one part of a split net recharge.

    ``sign`` is ``+1`` for the recharge part and ``-1`` for the deficit part.
    A keyword acts on the part itself; a number ``F`` gives ``max(sign * F, 0)``.
    """
    if not _is_number(first_clim):
        return apply_first_clim(parts_by_period, steady=steady, first_clim=first_clim)
    periods = sorted(int(k) for k in parts_by_period)
    out = {k: np.array(parts_by_period[k], dtype=float, copy=True) for k in periods}
    value = max(float(sign) * float(first_clim), 0.0)
    for k in periods:
        if _is_steady(steady, k):
            out[k] = np.full(out[k].shape, value, dtype=float)
    return out


def split_net_recharge(
    rates_by_period: Mapping[int, object],
    *,
    steady: Sequence[bool] | np.ndarray,
    first_clim: object,
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
        first_clim_on_part(recharge, steady=steady, first_clim=first_clim, sign=1.0),
        first_clim_on_part(deficit, steady=steady, first_clim=first_clim, sign=-1.0),
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
    "split_net_recharge",
    "steady_flags",
    "steady_rate",
]
