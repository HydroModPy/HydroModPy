"""When a simulated cell flows, how often it flows in a year, and the two extent masks.

A mapped network is a classification by flow duration: a permanent reach flows
all year, an intermittent one part of the year. The object a map of that kind
is compared to is a mask of the same definition, drawn from the stack of
simulated states of a transient run, and never one instantaneous state. This
module builds it in four steps, each a pure function the criterion and the
figures share:

1. "Flowing" at one timestep (:func:`flowing_cells`). A cell seeps when its
   release exceeds ``tau * R * A``. It flows when it lies in the downstream
   closure of the seeping cells and, when a visible flow is set, when its
   routed discharge reaches it. The routed discharge
   (:func:`routed_discharge`) is the release of the seeping cells accumulated
   down the criterion graph. It never falls downstream, so the flowing mask
   stays closed downstream whatever the threshold.
2. Calendar years (:func:`calendar_years`). A timestep belongs to the year its
   middle falls in; a year the run does not cover from 1 January to
   31 December is left out. When a scoring window is given, a complete year
   the window does not hold from 1 January to 31 December is left out too:
   that is how a spin-up year leaves the score.
3. Counts (:func:`yearly_flow_counts`). Per complete year and per cell, the
   number of timesteps the cell flows. The stack is read one year at a time,
   in chunks of timesteps, and never copied whole.
4. Masks (:func:`extent_masks`). In a year, the maximal mask holds the cells
   flowing at least ``maximal_flowing_steps`` timesteps, the minimal mask the
   cells flowing at every timestep but at most ``minimal_dry_steps``. Across
   years, a cell belongs to a climatological mask when it meets the rule in at
   least ``year_quorum`` of the scored years.

Durations are counted in TIMESTEPS, never in days: a rule in days would mean
nothing on a weekly or a monthly run. Nothing here names a solver package or a
calibration setting; the release flux arrives aggregated by the adapter.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_network import SimulatedNetwork
from hydromodpy.core.topographic_distance import DownslopeMetric
from hydromodpy.core.units.volumetric_flow import parse_to_m3_per_s

logger = get_logger(__name__)

Bound = Literal["minimal", "maximal"]

DEFAULT_VISIBLE_FLOW = "1 L/s"
"""The routed discharge a cell must carry to flow in the two-bound mode.

No value is agreed in the literature. The closest precedent thresholds a
simulated discharge at 10 L/s (Zanetti et al., 2024, doi:10.1029/2023WR035631),
and field zero-flow thresholds of about 1 to 3 L/s are in use (Zimmer et al.,
2020, doi:10.1002/wat2.1436). One litre per second is the low end of both."""

CHUNK_ELEMENTS = 8_000_000
"""Cells times timesteps accumulated in one pass, 64 MB of float64."""

FEW_YEARS_WARNING = 3
"""Below this many scored years the quorum is warned about: with two years a
quorum of one half is the union of the two."""


@dataclass(frozen=True, slots=True)
class VisibleFlow:
    """The routed discharge below which a cell of the closure does not flow.

    Exactly one of the two is positive, or neither: ``discharge_m3_s`` is an
    absolute discharge, ``outlet_share`` a share of the routed discharge at the
    outlet at the same timestep. Neither positive is the geometric definition,
    the downstream closure alone. A cell size never enters it: the size of a
    cell is a numerical choice, the discharge a cartographer sees is not.
    """

    discharge_m3_s: float = 0.0
    outlet_share: float = 0.0

    def __post_init__(self) -> None:
        for name in ("discharge_m3_s", "outlet_share"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"visible flow {name} must be finite and positive, got {value}.")
        if self.discharge_m3_s > 0.0 and self.outlet_share > 0.0:
            raise ValueError("a visible flow is either a discharge or an outlet share, not both.")
        if self.outlet_share > 1.0:
            raise ValueError(
                f"a visible flow share of the outlet discharge is at most 100%, got "
                f"{100.0 * self.outlet_share:g}%."
            )

    @property
    def geometric(self) -> bool:
        """True when no discharge is required: the downstream closure alone."""
        return self.discharge_m3_s == 0.0 and self.outlet_share == 0.0

    def label(self) -> str:
        """Return the threshold as a user would write it."""
        if self.outlet_share > 0.0:
            return f"{100.0 * self.outlet_share:g}%"
        return f"{1000.0 * self.discharge_m3_s:g} L/s"


GEOMETRIC = VisibleFlow()
"""No visible-flow threshold: a cell flows when it is in the closure."""

_SHARE = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*%\s*$")
_HAS_UNIT = re.compile(r"[A-Za-z]")


def parse_visible_flow(value: str | VisibleFlow) -> VisibleFlow:
    """Read ``"1 L/s"``, ``"0.002 m3/s"`` or ``"1%"`` into a :class:`VisibleFlow`.

    A percentage is a share of the routed discharge at the outlet at the same
    timestep. A discharge needs its unit: a bare number would be read in
    litres by one user and in cubic metres by the next. ``"0 L/s"`` is the
    geometric definition.
    """
    if isinstance(value, VisibleFlow):
        return value
    text = str(value).strip()
    share = _SHARE.match(text)
    if share is not None:
        return VisibleFlow(outlet_share=float(share.group(1)) / 100.0)
    if not _HAS_UNIT.search(text):
        raise ValueError(
            f"visible_flow = {value!r} carries no unit. Write a discharge with its unit, "
            "such as '1 L/s', or a share of the outlet discharge, such as '1%'."
        )
    discharge, _ = parse_to_m3_per_s(text, location="visible_flow", default_unit="m3/s")
    return VisibleFlow(discharge_m3_s=float(discharge))


@dataclass(frozen=True, slots=True)
class FlowingCells:
    """Who seeps and who flows, at one timestep or over a stack of them.

    Both arrays are ``(n_cells,)`` or ``(n_times, n_cells)`` bool. ``seepage``
    holds the flowing cells that are sources themselves, so it is a subset of
    ``flowing`` by construction.
    """

    seepage: np.ndarray
    flowing: np.ndarray


def routed_discharge(
    metric: DownslopeMetric, release_flux: np.ndarray, seepage: np.ndarray
) -> np.ndarray:
    """Return the release of the seeping cells accumulated down the criterion graph.

    ``release_flux`` and ``seepage`` are ``(n_cells,)`` or ``(n_times,
    n_cells)``, in m3/s. The result has the same shape, in m3/s, NaN on the
    inactive cells. It is a routed seepage discharge, not a river discharge:
    no runoff and no loss in the bed enter it. It never decreases downstream.
    """
    flux = np.asarray(release_flux, dtype=float)
    mask = np.asarray(seepage, dtype=bool)
    if flux.shape != mask.shape:
        raise ValueError(f"release_flux has shape {flux.shape} and the seepage mask {mask.shape}.")
    return accumulate_on_downhill_graph(metric.graph, np.where(mask, flux, 0.0))


def flowing_cells(
    release_flux: np.ndarray,
    *,
    threshold_m3_s: np.ndarray,
    metric: DownslopeMetric,
    visible_flow: VisibleFlow = GEOMETRIC,
    outlet: int | None = None,
) -> FlowingCells:
    """Return the one definition of "flowing", at every timestep of a stack.

    A cell seeps when its release exceeds its own ``threshold_m3_s``, strictly.
    It flows when it lies in the downstream closure of the seeping cells and,
    unless ``visible_flow`` is geometric, when its routed discharge is at least
    the visible flow. A share of the outlet discharge reads the routed
    discharge at ``outlet`` at the same timestep, so ``outlet`` is required
    then. With the geometric definition this is exactly the network
    :func:`hydromodpy.core.stream_network.build_simulated_network` builds.
    """
    flux = np.asarray(release_flux, dtype=float)
    single = flux.ndim == 1
    stack = flux.reshape(1, -1) if single else flux
    active = metric.graph.active
    threshold = np.asarray(threshold_m3_s, dtype=float).reshape(-1)
    if stack.ndim != 2 or stack.shape[1] != active.size:
        raise ValueError(f"release_flux must hold {active.size} cells, got shape {flux.shape}.")
    if threshold.size != active.size:
        raise ValueError(
            f"the threshold holds {threshold.size} cells, the mesh holds {active.size}."
        )
    seepage = np.isfinite(stack) & (stack > threshold[None, :]) & active[None, :]
    if visible_flow.geometric:
        reached = accumulate_on_downhill_graph(metric.graph, seepage.astype(float))
        flowing = np.nan_to_num(reached, nan=0.0) > 0.0
    else:
        discharge = np.nan_to_num(routed_discharge(metric, stack, seepage), nan=0.0)
        if visible_flow.outlet_share > 0.0:
            if outlet is None:
                raise ValueError("a visible flow given as an outlet share needs the outlet cell.")
            required = visible_flow.outlet_share * discharge[:, int(outlet)][:, None]
        else:
            required = np.full((stack.shape[0], 1), visible_flow.discharge_m3_s)
        flowing = (discharge > 0.0) & (discharge >= required)
    flowing &= active[None, :]
    seepage &= flowing
    if single:
        return FlowingCells(seepage=seepage[0], flowing=flowing[0])
    return FlowingCells(seepage=seepage, flowing=flowing)


@dataclass(frozen=True, slots=True)
class CalendarYears:
    """The calendar years a run scores, and the timesteps of each.

    ``steps[i]`` holds the indices of the timesteps whose middle falls in
    ``years[i]``. ``incomplete`` names the years the run touches without
    covering them from 1 January to 31 December. ``outside_window`` names the
    complete years a scoring window left out, a spin-up year for one; it is
    empty when no window was given.
    """

    years: tuple[int, ...]
    steps: tuple[np.ndarray, ...]
    incomplete: tuple[int, ...]
    outside_window: tuple[int, ...] = ()

    @property
    def n_steps(self) -> np.ndarray:
        """``(n_years,)`` the number of timesteps in each scored year."""
        return np.asarray([block.size for block in self.steps], dtype=np.int64)


def _window_bound(value: Any, label: str) -> np.datetime64 | None:
    """Return one bound of a scoring window as ``datetime64[ns]``, or None when open."""
    if value is None:
        return None
    try:
        bound = np.asarray([value], dtype="datetime64[ns]")[0]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"scoring window {label} {value!r} is not a date.") from exc
    return None if np.isnat(bound) else bound


def calendar_years(
    edges: Sequence[Any] | np.ndarray,
    *,
    window: tuple[Any, Any] | None = None,
) -> CalendarYears:
    """Split a run's timesteps into the complete calendar years it scores.

    ``edges`` are the ``n_steps + 1`` bounds of the timesteps, the start of the
    first step followed by the end of every step, as ``datetime64`` or
    anything numpy converts to it (naive, in one time zone). A step belongs to
    the year of its middle, which is where a monthly January stamped
    1 February still falls. A year is complete when the run starts on or
    before its 1 January and ends on or after the next one.

    ``window`` is the ``(start, end)`` of a scoring window, naive and in the
    time zone of ``edges``, either bound None when open. A complete year is
    scored only when the window starts on or before its 1 January and ends on
    or after its 31 December; the others go to ``outside_window``. The end is
    a date, inclusive, as a window reads everywhere else: ``"2002-12-31"``
    holds 2002. A window is how a spin-up year, whose first step starts from
    the initial condition, leaves the score.
    """
    start_bound, end_bound = (None, None) if window is None else window
    first = _window_bound(start_bound, "start")
    last = _window_bound(end_bound, "end")
    if first is not None and last is not None and first > last:
        raise ValueError(f"scoring window start {start_bound} is after its end {end_bound}.")
    bounds = np.asarray(edges, dtype="datetime64[ns]").reshape(-1)
    if bounds.size < 2:
        return CalendarYears(years=(), steps=(), incomplete=())
    if np.any(bounds[1:] <= bounds[:-1]):
        raise ValueError("the timestep bounds must increase strictly.")
    middles = bounds[:-1] + (bounds[1:] - bounds[:-1]) / 2
    step_year = middles.astype("datetime64[Y]").astype(np.int64) + 1970
    indices = np.arange(step_year.size)
    years: list[int] = []
    steps: list[np.ndarray] = []
    incomplete: list[int] = []
    outside: list[int] = []
    for year in np.unique(step_year).tolist():
        start = np.datetime64(f"{int(year):04d}-01-01", "ns")
        end = np.datetime64(f"{int(year) + 1:04d}-01-01", "ns")
        if not (bounds[0] <= start and bounds[-1] >= end):
            incomplete.append(int(year))
        elif (first is not None and first > start) or (
            last is not None and last < np.datetime64(f"{int(year):04d}-12-31", "ns")
        ):
            outside.append(int(year))
        else:
            years.append(int(year))
            steps.append(indices[step_year == year])
    return CalendarYears(
        years=tuple(years),
        steps=tuple(steps),
        incomplete=tuple(incomplete),
        outside_window=tuple(outside),
    )


@dataclass(frozen=True, slots=True)
class YearlyFlowCounts:
    """How many timesteps each cell flowed, per complete year.

    ``flowing`` and ``seepage`` are ``(n_years, n_cells)`` counts; ``seepage``
    counts the timesteps a flowing cell was a source itself.
    """

    years: tuple[int, ...]
    n_steps: np.ndarray
    flowing: np.ndarray
    seepage: np.ndarray


def yearly_flow_counts(
    release_flux: np.ndarray,
    *,
    years: CalendarYears,
    threshold_m3_s: np.ndarray,
    metric: DownslopeMetric,
    visible_flow: VisibleFlow = GEOMETRIC,
    outlet: int | None = None,
    chunk_elements: int = CHUNK_ELEMENTS,
) -> YearlyFlowCounts:
    """Count, per complete year and per cell, the timesteps the cell flows.

    ``release_flux`` is the ``(n_times, n_cells)`` stack in m3/s. It is read
    through views, one year at a time and at most ``chunk_elements`` values per
    pass, so the only full-size array is the one the caller already holds.
    """
    flux = np.asarray(release_flux)
    if flux.ndim != 2:
        raise ValueError(f"release_flux must be (n_times, n_cells), got shape {flux.shape}.")
    n_times, n_cells = flux.shape
    last = max((int(block.max()) for block in years.steps if block.size), default=-1)
    if last >= n_times:
        raise ValueError(
            f"the calendar names timestep {last} and the release stack holds {n_times}."
        )
    per_pass = max(1, int(chunk_elements) // max(1, n_cells))
    flowing = np.zeros((len(years.years), n_cells), dtype=np.int32)
    seepage = np.zeros((len(years.years), n_cells), dtype=np.int32)
    for row, block in enumerate(years.steps):
        for first in range(0, block.size, per_pass):
            chunk = block[first : first + per_pass]
            # A contiguous block is a slice, hence a view of the caller's stack.
            rows = (
                flux[int(chunk[0]) : int(chunk[-1]) + 1]
                if chunk.size and np.all(np.diff(chunk) == 1)
                else flux[chunk]
            )
            state = flowing_cells(
                rows,
                threshold_m3_s=threshold_m3_s,
                metric=metric,
                visible_flow=visible_flow,
                outlet=outlet,
            )
            flowing[row] += state.flowing.sum(axis=0, dtype=np.int32)
            seepage[row] += state.seepage.sum(axis=0, dtype=np.int32)
    return YearlyFlowCounts(
        years=years.years, n_steps=years.n_steps, flowing=flowing, seepage=seepage
    )


def flow_persistence(counts: YearlyFlowCounts) -> np.ndarray:
    """Return ``(n_years, n_cells)``: the share of each year's timesteps a cell flows."""
    steps = np.maximum(counts.n_steps, 1).astype(float)[:, None]
    return counts.flowing / steps


def extent_step_problems(
    n_steps: Sequence[int] | np.ndarray,
    *,
    maximal_flowing_steps: int,
    minimal_dry_steps: int,
) -> list[str]:
    """Return why the two step rules cannot be read on these years, or nothing.

    ``n_steps`` is the number of timesteps in each complete year. The maximal
    rule needs ``1 <= maximal_flowing_steps <= n``. The minimal rule keeps the
    cells flowing at least ``n - minimal_dry_steps`` timesteps, which has to
    stay at least ``maximal_flowing_steps`` so the minimal mask is inside the
    maximal one, and at least one.
    """
    counts = [int(value) for value in np.asarray(n_steps).reshape(-1)]
    problems: list[str] = []
    if not counts:
        return ["the run holds no complete calendar year"]
    fewest = min(counts)
    n_max = int(maximal_flowing_steps)
    n_min = int(minimal_dry_steps)
    if n_max < 1:
        problems.append(f"maximal_flowing_steps = {n_max} is below one timestep")
    elif n_max > fewest:
        problems.append(
            f"maximal_flowing_steps = {n_max} exceeds the {fewest} timestep(s) of the "
            "shortest complete year"
        )
    if n_min < 0:
        problems.append(f"minimal_dry_steps = {n_min} is negative")
    elif fewest - n_min < max(n_max, 1):
        problems.append(
            f"minimal_dry_steps = {n_min} leaves {fewest - n_min} flowing timestep(s) of "
            f"{fewest} for the minimal mask, fewer than the {max(n_max, 1)} the maximal one "
            "asks, so the permanent network would be looser than the complete one"
        )
    return problems


def quorum_count(n_years: int, year_quorum: float) -> int:
    """Return how many scored years a cell must meet a rule in: ceil(q * n), at least one."""
    if not 0.0 < float(year_quorum) <= 1.0:
        raise ValueError(f"year_quorum must lie in (0, 1], got {year_quorum}.")
    if int(n_years) < 1:
        raise ValueError("a quorum needs at least one scored year.")
    return max(1, math.ceil(float(year_quorum) * int(n_years) - 1e-9))


@dataclass(frozen=True, slots=True)
class ExtentMasks:
    """The maximal and minimal simulated masks, per year and climatological.

    Every mask is closed downstream and ``minimal`` is inside ``maximal``, year
    by year and across years. The ``*_seepage`` masks hold the cells of each
    mask that were sources under the same rule: a diagnostic only.
    """

    years: tuple[int, ...]
    n_years_required: int
    maximal: np.ndarray
    minimal: np.ndarray
    maximal_seepage: np.ndarray
    minimal_seepage: np.ndarray
    yearly_maximal: np.ndarray
    yearly_minimal: np.ndarray
    yearly_maximal_seepage: np.ndarray
    yearly_minimal_seepage: np.ndarray

    def network(
        self, bound: Bound, *, threshold_m3_s: np.ndarray, year: int | None = None
    ) -> SimulatedNetwork:
        """Return one mask as the network the distance criterion scores.

        ``year`` picks that year's mask; ``None`` the climatological one.
        """
        if bound not in ("minimal", "maximal"):
            raise ValueError(f"bound must be 'minimal' or 'maximal', got {bound!r}.")
        if year is None:
            network = self.maximal if bound == "maximal" else self.minimal
            sources = self.maximal_seepage if bound == "maximal" else self.minimal_seepage
        else:
            row = self.years.index(int(year))
            network = (self.yearly_maximal if bound == "maximal" else self.yearly_minimal)[row]
            sources = (
                self.yearly_maximal_seepage if bound == "maximal" else self.yearly_minimal_seepage
            )[row]
        return SimulatedNetwork(
            seepage=sources,
            network=network,
            threshold_m3_s=np.asarray(threshold_m3_s, dtype=float).reshape(-1),
        )


def extent_masks(
    counts: YearlyFlowCounts,
    *,
    maximal_flowing_steps: int = 1,
    minimal_dry_steps: int = 1,
    year_quorum: float = 0.5,
) -> ExtentMasks:
    """Turn yearly flow counts into the two extent masks.

    In a year of ``n`` timesteps the maximal mask holds the cells flowing at
    least ``maximal_flowing_steps`` of them and the minimal mask the cells
    flowing at least ``n - minimal_dry_steps``. A cell enters a climatological
    mask when it meets that year's rule in at least ``ceil(year_quorum * n)``
    of the scored years. Refused, with every reason at once, when a rule
    cannot be read on these years; warned when fewer than three years are
    scored, since a quorum of one half over two years is their union.
    """
    problems = extent_step_problems(
        counts.n_steps,
        maximal_flowing_steps=maximal_flowing_steps,
        minimal_dry_steps=minimal_dry_steps,
    )
    if problems:
        raise ValueError("; ".join(problems) + ".")
    n_years = len(counts.years)
    required = quorum_count(n_years, year_quorum)
    if n_years < FEW_YEARS_WARNING:
        logger.warning(
            "Network extent: %d complete year(s) scored (%s). A cell enters a mask when it "
            "meets the rule in %d of them, so with fewer than %d years the quorum %.2f is "
            "close to a union or an intersection rather than an ordinary year.",
            n_years,
            ", ".join(str(year) for year in counts.years),
            required,
            FEW_YEARS_WARNING,
            float(year_quorum),
        )
    steps = counts.n_steps.astype(np.int64)[:, None]
    yearly_maximal = counts.flowing >= int(maximal_flowing_steps)
    yearly_minimal = counts.flowing >= steps - int(minimal_dry_steps)
    yearly_maximal_seepage = yearly_maximal & (counts.seepage >= int(maximal_flowing_steps))
    yearly_minimal_seepage = yearly_minimal & (counts.seepage >= steps - int(minimal_dry_steps))

    def climatological(yearly: np.ndarray) -> np.ndarray:
        return yearly.sum(axis=0) >= required

    return ExtentMasks(
        years=counts.years,
        n_years_required=required,
        maximal=climatological(yearly_maximal),
        minimal=climatological(yearly_minimal),
        maximal_seepage=climatological(yearly_maximal_seepage),
        minimal_seepage=climatological(yearly_minimal_seepage),
        yearly_maximal=yearly_maximal,
        yearly_minimal=yearly_minimal,
        yearly_maximal_seepage=yearly_maximal_seepage,
        yearly_minimal_seepage=yearly_minimal_seepage,
    )


__all__ = (
    "CHUNK_ELEMENTS",
    "DEFAULT_VISIBLE_FLOW",
    "GEOMETRIC",
    "Bound",
    "CalendarYears",
    "ExtentMasks",
    "FlowingCells",
    "VisibleFlow",
    "YearlyFlowCounts",
    "calendar_years",
    "extent_masks",
    "extent_step_problems",
    "flow_persistence",
    "flowing_cells",
    "parse_visible_flow",
    "quorum_count",
    "routed_discharge",
    "yearly_flow_counts",
)
