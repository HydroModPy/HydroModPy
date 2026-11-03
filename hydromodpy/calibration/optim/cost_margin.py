"""How well the trials determined each calibrated value.

A calibration reports one number per parameter, and a number on its own says
nothing about its own standing. Two searches can return the same conductivity
from entirely different traces: one where the cost climbs steeply on both sides,
one where it is flat over three decades. The first identifies the value, the
second does not, and the report looked the same.

The interval here is read off the trials the search already ran: the range of
sampled values whose cost stays within a stated margin of the best. It rests
on no error model and on no extra run, which is what makes it always available.
It is a statement about what the search saw, not a posterior: a parameter the
search never varied far has a narrow interval because nothing else was tried,
not because the record constrains it. ``reaches_lower_bound`` and
``reaches_upper_bound`` are what separate the two cases, and they are the part
of this to read first.

The margin a file leaves unwritten follows what the search scores
(:func:`choose_interval_width`): one mesh cell on network distances, five per
cent of the best cost otherwise.

"One mesh cell" is ``h_obs``: the median distance between neighbouring cell
centres over the mapped cells of the catchment, the length ``r_optim`` is also
divided by. On a mesh refined along the streams it is the fine cell the
distances start from, not the median cell of the catchment; on a regular grid
it is the cell size. The criterion measures it and publishes it per trial as
``<output>.cell_spacing_m``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np
import pandas as pd

from hydromodpy.calibration.optim.diagnostics import _META_COLUMNS, iterations_to_dataframe
from hydromodpy.core.cost_margin import CostMargin, MarginKind

DEFAULT_MARGIN = 0.05
"""Five per cent of the best cost, the default width of the interval."""

WidthSource = Literal["phase", "section", "default"]
"""Where a margin was written: in the phase, in [calibration.uncertainty], or nowhere."""

ONE_MESH_CELL = "one mesh cell"
FIVE_PER_CENT = "5 % of the best cost"


@dataclass(frozen=True)
class IntervalWidth:
    """The margin a search reads its interval with, and where it comes from.

    ``margin`` is a fraction of the best cost when ``kind`` is ``"relative"``
    and metres when it is ``"absolute"``. It is ``None`` for one mesh cell
    until a trial measured the mesh: the network criterion measures the cell,
    ``h_obs``, on the geometry it builds, and the run reads it back through
    :meth:`measured`. ``source`` says where the margin was written, and
    ``rule`` names the default when nothing wrote it. ``on_distances`` is true
    when every block of the search is a network distance left in metres.
    """

    margin: float | None
    kind: MarginKind
    source: WidthSource
    on_distances: bool
    rule: str | None = None

    def measured(self, cell_m: float) -> IntervalWidth:
        """Return this width with the one mesh cell set to ``cell_m`` metres."""
        return replace(self, margin=float(cell_m))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly record for a report or a phase listing."""
        return {
            "margin": self.margin,
            "kind": self.kind,
            "source": self.source,
            "on_distances": self.on_distances,
            "rule": self.rule,
        }


def choose_interval_width(
    on_distances: bool,
    *,
    margin: tuple[CostMargin, WidthSource] | None = None,
) -> IntervalWidth:
    """Return the width a search reads its interval with.

    ``on_distances`` says the search is scored only by network distances
    (``distance_gap``, ``distance_mean``) left in metres. ``margin`` is what the
    file wrote, with where it was written, or ``None``. A written margin wins.
    Left unwritten, it follows what the search scores. A search on network
    distances takes one mesh cell, ``h_obs``, in metres: a stream cannot move
    by less than a cell, so two gaps closer than that are not told apart. Any
    other search takes five per cent of the best cost.
    """
    if margin is not None:
        written, source = margin
        return IntervalWidth(float(written.value), written.kind, source, on_distances)
    if on_distances:
        return IntervalWidth(None, "absolute", "default", on_distances, ONE_MESH_CELL)
    return IntervalWidth(DEFAULT_MARGIN, "relative", "default", on_distances, FIVE_PER_CENT)


@dataclass(frozen=True)
class ParameterInterval:
    """The range of one parameter the trials could not tell from the best."""

    name: str
    best: float
    lower: float
    upper: float
    margin: float
    kind: MarginKind
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
            "margin": self.margin,
            "kind": self.kind,
            "threshold": self.threshold,
            "n_within": self.n_within,
            "n_trials": self.n_trials,
            "reaches_lower_bound": self.reaches_lower_bound,
            "reaches_upper_bound": self.reaches_upper_bound,
        }


def margin_intervals(
    iterations: Iterable[Mapping[str, Any]] | pd.DataFrame,
    parameters: Iterable[str] | None = None,
    *,
    margin: float = DEFAULT_MARGIN,
    kind: MarginKind = "relative",
    objective: str = "cost",
    bounds: Mapping[str, tuple[float, float]] | None = None,
) -> list[ParameterInterval]:
    """Return, per parameter, the range of trials whose cost matched the best.

    Parameters
    ----------
    iterations
        The calibration trace, in the ``calibration_iterations`` shape.
    parameters
        Which columns to read. ``None`` takes every non-meta column.
    margin
        Width of the interval. Read as a fraction of the best cost under
        ``kind="relative"``, and in cost units under ``kind="absolute"``.
    kind
        ``"relative"`` is refused when the best cost is not strictly positive:
        a criterion solved at zero, such as the stream-network gap, has no
        fraction of itself to speak of, and the margin has to be stated as a
        length.
    objective
        Name of the cost column.
    bounds
        The search range per parameter. Given, an interval that runs into one
        is marked, which is the difference between a determined value and one
        the search merely ran out of room to vary.
    """
    if margin < 0.0:
        raise ValueError(f"margin must not be negative, got {margin}")

    frame = iterations_to_dataframe(iterations)
    column = objective if objective in frame.columns else "objective"
    costs = pd.to_numeric(frame.get(column, pd.Series(dtype=float)), errors="coerce")
    costs = np.asarray(costs, dtype=float).ravel()
    finite = np.isfinite(costs)
    if not finite.any():
        return []

    best_cost = float(np.min(costs[finite]))
    if kind == "relative":
        if best_cost <= 0.0:
            raise ValueError(
                f"a share of the best cost has nothing to take a fraction of when the "
                f"best cost is {best_cost:g}. State the margin in the unit of the cost "
                "instead, as a length such as '25 m'."
            )
        threshold = best_cost * (1.0 + margin)
    elif kind == "absolute":
        threshold = best_cost + margin
    else:
        raise ValueError(f"kind must be 'relative' or 'absolute', got {kind!r}")

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
                margin=float(margin),
                kind=kind,
                threshold=float(threshold),
                n_within=int(selected.size),
                n_trials=int(np.count_nonzero(finite)),
                reaches_lower_bound=low_bound is not None and lower <= float(low_bound),
                reaches_upper_bound=high_bound is not None and upper >= float(high_bound),
            )
        )
    return intervals


__all__ = [
    "DEFAULT_MARGIN",
    "FIVE_PER_CENT",
    "ONE_MESH_CELL",
    "IntervalWidth",
    "ParameterInterval",
    "WidthSource",
    "choose_interval_width",
    "margin_intervals",
]
