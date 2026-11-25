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

"One mesh cell" is ``h_obs``: the median distance between neighboring cell
centers over the mapped cells of the catchment, the length ``r_optim`` is also
divided by. On a mesh refined along the streams it is the fine cell the
distances start from, not the median cell of the catchment; on a regular grid
it is the cell size. The criterion measures it and publishes it per trial as
``<output>.cell_spacing_m``.

A root search answers with one value on one parameter, and its trials pile up
around the root, so their envelope only gives the neighbor of the sweep or the
bracket. There the cost against the search variable is a curve, and
:func:`root_interval` interpolates where it crosses the margin. Each end of an
interval says what it is: ``crossed`` when the cost was seen to cross the margin,
``bound`` when the search ran out of room, ``open`` when nothing says.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np
import pandas as pd

from hydromodpy.calibration.optim.diagnostics import _META_COLUMNS, iterations_to_dataframe
from hydromodpy.calibration.optim.optimizer import EvaluationResult
from hydromodpy.core.scoring.cost_margin import CostMargin, MarginKind

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
    and meters when it is ``"absolute"``. It is ``None`` for one mesh cell
    until a trial measured the mesh: the network criterion measures the cell,
    ``h_obs``, on the geometry it builds, and the run reads it back through
    :meth:`measured`. ``source`` says where the margin was written, and
    ``rule`` names the default when nothing wrote it. ``on_distances`` is true
    when every block of the search is a network distance left in meters.
    """

    margin: float | None
    kind: MarginKind
    source: WidthSource
    on_distances: bool
    rule: str | None = None

    def measured(self, cell_m: float) -> IntervalWidth:
        """Return this width with the one mesh cell set to ``cell_m`` meters."""
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
    (``distance_gap``, ``distance_mean``) left in meters. ``margin`` is what the
    file wrote, with where it was written, or ``None``. A written margin wins.
    Left unwritten, it follows what the search scores. A search on network
    distances takes one mesh cell, ``h_obs``, in meters: a stream cannot move
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
    lower_crossed: bool = False
    upper_crossed: bool = False

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
            "lower_end": _end(self.lower_crossed, self.reaches_lower_bound),
            "upper_end": _end(self.upper_crossed, self.reaches_upper_bound),
        }


def _end(crossed: bool, reached: bool) -> str:
    return "crossed" if crossed else "bound" if reached else "open"


def _cost_threshold(best_cost: float, margin: float, kind: MarginKind) -> float:
    """Return the cost a margin allows above the best one."""
    if kind == "relative":
        if best_cost <= 0.0:
            raise ValueError(
                f"a share of the best cost has nothing to take a fraction of when the "
                f"best cost is {best_cost:g}. State the margin in the unit of the cost "
                "instead, as a length such as '25 m'."
            )
        return best_cost * (1.0 + margin)
    if kind == "absolute":
        return best_cost + margin
    raise ValueError(f"kind must be 'relative' or 'absolute', got {kind!r}")


def margin_intervals(
    iterations: Iterable[Mapping[str, Any]] | pd.DataFrame,
    parameters: Iterable[str] | None = None,
    *,
    margin: float = DEFAULT_MARGIN,
    kind: MarginKind = "relative",
    objective: str = "cost",
    bounds: Mapping[str, tuple[float, float]] | None = None,
    samples_the_box: bool = False,
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
        the search merely ran out of room to vary. An end runs into its bound
        when a trial sits on it.
    samples_the_box
        Whether the search drew its points over the whole box (grid, Latin
        hypercube, random draws, a population). Such a design never puts a
        sample exactly on a bound, so an end then runs into its bound when no
        solved trial lies beyond it. A local search that never went that far
        leaves the end open instead.
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
    threshold = _cost_threshold(best_cost, margin, kind)

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
        solved = values[finite & np.isfinite(values)]
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
                reaches_lower_bound=low_bound is not None
                and (
                    lower <= float(low_bound)
                    or (samples_the_box and not bool(np.any(solved < lower)))
                ),
                reaches_upper_bound=high_bound is not None
                and (
                    upper >= float(high_bound)
                    or (samples_the_box and not bool(np.any(solved > upper)))
                ),
            )
        )
    return intervals


ZoneEnd = Literal["bound", "crossed"]
"""What stops one end of a zone: the bound of the search, or a solved trial beyond it."""


@dataclass(frozen=True)
class Zone:
    """The range of the search variable a next level of a zoomed design draws in.

    ``lower`` and ``upper`` are in the variable the search walks, and each end
    says what stops it: ``bound`` when no solved trial lies beyond it, so the
    zone runs to the bound of the search, ``crossed`` when a solved trial does.
    ``best_cost`` and ``threshold`` are the cost of the best trial and the cost
    its margin allows, ``n_within`` the solved trials under the threshold and
    ``n_lost`` the trials that gave no finite cost. A zone with both ends at a
    bound is the whole box: the trials did not narrow it.
    """

    lower: float
    upper: float
    lower_end: ZoneEnd
    upper_end: ZoneEnd
    best_cost: float | None
    threshold: float | None
    n_within: int
    n_lost: int

    @property
    def narrowed(self) -> bool:
        """Whether the zone is smaller than the box of the search."""
        return self.lower_end == "crossed" or self.upper_end == "crossed"


def zone_of_the_trials(
    values: Sequence[float],
    costs: Sequence[float | None],
    *,
    margin: float | None,
    kind: MarginKind,
    bounds: tuple[float, float],
    stratum: float,
) -> Zone:
    """Return the zone of the search variable the trials leave open for the best cost.

    ``values`` and ``costs`` hold one entry per trial, in the search variable.
    A trial with no finite cost is lost and counts neither in the margin nor as
    a neighbor. The zone runs over the solved trials whose cost is within
    ``margin`` of the best one, widened to the solved trial just below and just
    above them, and by at least ``stratum`` on each side, then clipped to
    ``bounds``. With no solved trial, no margin to read (``None``, or a share of
    a best cost that is not positive) or a cost that no trial tells apart, the
    zone is the whole box.
    """
    if margin is not None and margin < 0.0:
        raise ValueError(f"margin must not be negative, got {margin}")
    low_bound, high_bound = float(bounds[0]), float(bounds[1])
    x = np.asarray(values, dtype=float)
    cost = np.asarray([np.nan if c is None else c for c in costs], dtype=float)
    solved = np.isfinite(x) & np.isfinite(cost)
    lost = int(x.size - np.count_nonzero(solved))
    whole = Zone(low_bound, high_bound, "bound", "bound", None, None, 0, lost)
    if margin is None or not solved.any():
        return whole
    best_cost = float(np.min(cost[solved]))
    try:
        threshold = _cost_threshold(best_cost, margin, kind)
    except ValueError:
        return replace(whole, best_cost=best_cost)
    within = solved & (cost <= threshold)
    first, last = float(np.min(x[within])), float(np.max(x[within]))
    below, above = x[solved & (x < first)], x[solved & (x > last)]
    lower = float(np.max(below)) if below.size else low_bound
    upper = float(np.min(above)) if above.size else high_bound
    lower = max(low_bound, min(lower, first - stratum))
    upper = min(high_bound, max(upper, last + stratum))
    return Zone(
        lower,
        upper,
        "bound" if lower <= low_bound else "crossed",
        "bound" if upper >= high_bound else "crossed",
        best_cost,
        float(threshold),
        int(np.count_nonzero(within)),
        lost,
    )


def cell_measured_by_the_criterion(results: Iterable[EvaluationResult | None]) -> float | None:
    """Return the mesh cell the network criterion measured on a trial, or ``None``.

    Every trial of one search scores the same mesh, so the first finite value
    is the cell. ``None`` when no trial scored a network output.
    """
    for result in results:
        if result is None:
            continue
        for key, value in (result.components or {}).items():
            if str(key).endswith(".cell_spacing_m") and math.isfinite(float(value)):
                return float(value)
    return None


def _solved(cost: float | None) -> bool:
    """Whether a trial gave a cost: not None and finite."""
    return cost is not None and bool(np.isfinite(cost))


def _walk_the_curve(
    side: Iterable[tuple[float, float | None]], x: float, cost: float, threshold: float
) -> tuple[float, bool]:
    """Follow one side of a curve to the first crossing of ``threshold``: its place, and if any.

    A trial with no cost stops the walk: a line drawn to it would claim a crossing
    no solve showed.
    """
    for next_x, next_cost in side:
        if not _solved(next_cost):
            return x, False
        if next_cost > threshold:
            return x + (next_x - x) * (threshold - cost) / (next_cost - cost), True
        x, cost = next_x, next_cost
    return x, False


def root_interval(
    curve: Mapping[float, float | None],
    root: tuple[float, float],
    margin: float,
    kind: MarginKind,
    parameter: Any,
    declared: tuple[float, float],
) -> ParameterInterval:
    """Return the interval around a root, read on the curve the trials trace.

    ``curve`` holds one cost per point of the search variable, the cost None on a
    point that did not solve, and ``declared`` is the search interval in that
    variable. ``root`` is the answer of the search. The margin is read from its
    cost, since the lowest cost may be a trial elsewhere. From the root the cost is
    followed on each side up to its first crossing of the margin, by a straight
    line between two points, so no solve is added.
    """
    root_x, root_cost = root
    threshold = _cost_threshold(root_cost, margin, kind)
    below = [(x, curve[x]) for x in sorted((x for x in curve if x < root_x), reverse=True)]
    above = [(x, curve[x]) for x in sorted(x for x in curve if x > root_x)]
    lower, lower_crossed = _walk_the_curve(below, root_x, root_cost, threshold)
    upper, upper_crossed = _walk_the_curve(above, root_x, root_cost, threshold)
    solved = [(x, cost) for x, cost in curve.items() if _solved(cost)]
    return ParameterInterval(
        name=parameter.name,
        best=float(parameter.to_physical(root_x)),
        lower=float(parameter.to_physical(lower)),
        upper=float(parameter.to_physical(upper)),
        margin=float(margin),
        kind=kind,
        threshold=float(threshold),
        n_within=sum(1 for x, _ in solved if lower <= x <= upper),
        n_trials=len(solved),
        reaches_lower_bound=not lower_crossed and lower <= declared[0],
        reaches_upper_bound=not upper_crossed and upper >= declared[1],
        lower_crossed=lower_crossed,
        upper_crossed=upper_crossed,
    )


__all__ = [
    "DEFAULT_MARGIN",
    "FIVE_PER_CENT",
    "ONE_MESH_CELL",
    "IntervalWidth",
    "ParameterInterval",
    "WidthSource",
    "Zone",
    "ZoneEnd",
    "cell_measured_by_the_criterion",
    "choose_interval_width",
    "margin_intervals",
    "root_interval",
    "zone_of_the_trials",
]
