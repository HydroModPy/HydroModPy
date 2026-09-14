"""How well the trials determined each calibrated value.

A calibration reports one number per parameter, and a number on its own says
nothing about its own standing. Two searches can return the same conductivity
from entirely different traces: one where the cost climbs steeply on both sides,
one where it is flat over three decades. The first identifies the value, the
second does not, and the report looked the same.

The interval here is read off the trials the search already ran: the range of
sampled values whose cost stays within a stated tolerance of the best. It rests
on no error model and on no extra run, which is what makes it always available.
It is a statement about what the search saw, not a posterior: a parameter the
search never varied far has a narrow interval because nothing else was tried,
not because the record constrains it. ``reaches_lower_bound`` and
``reaches_upper_bound`` are what separate the two cases, and they are the part
of this to read first.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from hydromodpy.calibration.optim.diagnostics import _META_COLUMNS, iterations_to_dataframe

DEFAULT_TOLERANCE = 0.05
"""Five per cent of the best cost, the default width of the interval."""

ToleranceMode = Literal["relative", "absolute"]


@dataclass(frozen=True)
class ParameterInterval:
    """The range of one parameter the trials could not tell from the best."""

    name: str
    best: float
    lower: float
    upper: float
    tolerance: float
    mode: ToleranceMode
    threshold: float
    n_within: int
    n_trials: int
    reaches_lower_bound: bool
    reaches_upper_bound: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly record for a report or a session row."""
        return {
            "name": self.name,
            "best": self.best,
            "lower": self.lower,
            "upper": self.upper,
            "tolerance": self.tolerance,
            "mode": self.mode,
            "threshold": self.threshold,
            "n_within": self.n_within,
            "n_trials": self.n_trials,
            "reaches_lower_bound": self.reaches_lower_bound,
            "reaches_upper_bound": self.reaches_upper_bound,
        }


def tolerance_intervals(
    iterations: Iterable[Mapping[str, Any]] | pd.DataFrame,
    parameters: Iterable[str] | None = None,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    mode: ToleranceMode = "relative",
    objective: str = "objective_value",
    bounds: Mapping[str, tuple[float, float]] | None = None,
) -> list[ParameterInterval]:
    """Return, per parameter, the range of trials whose cost matched the best.

    Parameters
    ----------
    iterations
        The calibration trace, in the ``calibration_iterations`` shape.
    parameters
        Which columns to read. ``None`` takes every non-meta column.
    tolerance
        Width of the interval. Read as a fraction of the best cost under
        ``mode="relative"``, and in cost units under ``mode="absolute"``.
    mode
        ``"relative"`` is refused when the best cost is not strictly positive:
        a criterion solved at zero, such as the stream-network gap, has no
        fraction of itself to speak of, and the tolerance has to be stated in
        the unit of the cost.
    objective
        Name of the cost column.
    bounds
        The search range per parameter. Given, an interval that runs into one
        is marked, which is the difference between a determined value and one
        the search merely ran out of room to vary.
    """
    if tolerance < 0.0:
        raise ValueError(f"tolerance must not be negative, got {tolerance}")

    frame = iterations_to_dataframe(iterations)
    column = objective if objective in frame.columns else "objective"
    costs = pd.to_numeric(frame.get(column, pd.Series(dtype=float)), errors="coerce")
    costs = np.asarray(costs, dtype=float).ravel()
    finite = np.isfinite(costs)
    if not finite.any():
        return []

    best_cost = float(np.min(costs[finite]))
    if mode == "relative":
        if best_cost <= 0.0:
            raise ValueError(
                f"a relative tolerance is a fraction of the best cost, which is "
                f"{best_cost:g} here and leaves nothing to take a fraction of. State "
                'the width in cost units instead: mode="absolute".'
            )
        threshold = best_cost * (1.0 + tolerance)
    elif mode == "absolute":
        threshold = best_cost + tolerance
    else:
        raise ValueError(f"mode must be 'relative' or 'absolute', got {mode!r}")

    names = (
        [str(name) for name in parameters]
        if parameters is not None
        else [str(name) for name in frame.columns if name not in _META_COLUMNS]
    )
    within = finite & (costs <= threshold)
    best_row = int(np.argmin(np.where(finite, costs, np.inf)))

    intervals: list[ParameterInterval] = []
    for name in names:
        if name not in frame.columns:
            continue
        values = np.asarray(pd.to_numeric(frame[name], errors="coerce"), dtype=float).ravel()
        selected = values[within & np.isfinite(values)]
        if selected.size == 0:
            continue
        lower = float(np.min(selected))
        upper = float(np.max(selected))
        low_bound, high_bound = (bounds or {}).get(name, (None, None))
        intervals.append(
            ParameterInterval(
                name=name,
                best=float(values[best_row]),
                lower=lower,
                upper=upper,
                tolerance=float(tolerance),
                mode=mode,
                threshold=float(threshold),
                n_within=int(selected.size),
                n_trials=int(np.count_nonzero(finite)),
                reaches_lower_bound=low_bound is not None and lower <= float(low_bound),
                reaches_upper_bound=high_bound is not None and upper >= float(high_bound),
            )
        )
    return intervals


__all__ = ["DEFAULT_TOLERANCE", "ParameterInterval", "ToleranceMode", "tolerance_intervals"]
