"""Score model observables without a live workflow context.

Two scorers live here, one per scoring route a document can take, and they hold
the same contract: named observables in, a cost and its components out. Neither
touches a trial context, a solver adapter or a mesh, which is what lets a model
that is not HydroModPy be scored by the criteria of a HydroModPy document.

:class:`ObservableScorer` serves the composite route, the
``[calibration.outputs]`` and ``[[calibration.objective_blocks]]`` of F6.
:class:`StationScorer` serves the single-metric route, ``variable`` and
``objective``, where the observations are the records a project loaded and the
cost is reported per station.

What stays with the producer is everything measured in one model's own terms:
resolving the flow adapter, placing a station on a mesh, adding the runoff
forcing to a drain budget and scaling it by the area a cell drains, preparing
the two distances of a stream network. A scorer that carried those would be
advertising a shape only HydroModPy can produce.

:class:`ObservableScorer` already has a second consumer, the evaluator that
scores a named forward model. :class:`StationScorer` has only the pipeline
today: what the split buys there is that the route can acquire one without the
criterion moving, not that it already has.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
import pandas as pd

from hydromodpy.calibration.metrics.downslope_network import MAXIMAL_SUFFIX, MINIMAL_SUFFIX
from hydromodpy.calibration.metrics.observed_pairing import (
    PairedOutputs,
    observing_outputs,
    output_time_methods,
    pair_outputs_with_observations,
)
from hydromodpy.calibration.metrics.scalar import score as score_series
from hydromodpy.calibration.optim.objective import build_objective_from_config
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.period_aggregation import period_edges
from hydromodpy.core.time.selection import TimeSelectionError, period_label, resolve_instant
from hydromodpy.results.derive.time_alignment import first_period_start, time_method_for

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibOutputDecl, OutputTime
    from hydromodpy.calibration.metrics.series import ObservedSeries
    from hydromodpy.calibration.optim.objective import Objective

logger = get_logger(__name__)


def slice_time(values: np.ndarray, time: Any, reducer: str) -> list[float]:
    """Apply ``time`` selector and ``reducer`` to a 1D array of simulated values."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        return []
    if time == "first":
        arr = arr[:1]
    elif time == "last":
        arr = arr[-1:]
    if reducer == "mean":
        return [float(np.nanmean(arr))]
    if reducer == "sum":
        return [float(np.nansum(arr))]
    if reducer == "last":
        return [float(arr[-1])]
    return [float(v) for v in arr]


def select_observable_times(result: ObservableResult, time: OutputTime) -> ObservableResult:
    """Select first or last values with their timestamps before pairing."""
    if time == "all" or isinstance(time, list):
        return result
    values = np.asarray(result.values).reshape(-1)
    times = None if result.times is None else pd.DatetimeIndex(result.times)
    if times is not None and len(times) != values.size:
        raise ValueError(f"Output {result.request_id!r} has mismatched timestamps and values")
    if time == "first":
        selected = np.arange(min(1, values.size))
    else:
        selected = np.arange(max(0, values.size - 1), values.size)
    return replace(
        result,
        values=values[selected],
        times=None if times is None else times[selected],
    )


def observable_series(result: ObservableResult, *, name: str) -> pd.Series:
    """Rebuild a pandas series from an observable, for the scoring helpers.

    ``score`` aligns on a time index, so an observable that carries one keeps
    it; one that does not falls back to a positional index, exactly as the
    binary readers did before.
    """
    values = np.asarray(result.values, dtype=float).reshape(-1)
    if result.times is not None and len(result.times) == values.size:
        return pd.Series(values, index=result.times, name=name)
    return pd.Series(values, name=name)


def dated_series(result: ObservableResult) -> pd.Series | None:
    """Return the result as a timestamped series, or ``None`` when it is not one."""
    times = getattr(result, "times", None)
    if times is None:
        return None
    values = np.asarray(result.values, dtype=float).ravel()
    index = pd.DatetimeIndex(times)
    if values.size == 0 or len(index) != values.size:
        return None
    return pd.Series(values, index=index)


def refuse_window_without_dates(
    outputs: Mapping[str, CalibOutputDecl],
    objective_blocks: list[CalibObjectiveBlockDecl],
    scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None,
    observing: Mapping[str, str],
    *,
    boundaries: Sequence[Any] | None = None,
) -> None:
    """Refuse a window on the blocks whose outputs carry no dates to cut on.

    An output that names a station is aligned on the simulated timestamps, so a
    window applies to it exactly. A network output with an extent table is
    scored by calendar year, and the window picks those years at extraction.
    A network output read in one state is dated at the stamp of that state:
    the window holds it or not, which needs the run's time grid, so it is
    checked when ``boundaries`` are given
    (:func:`refuse_a_network_state_outside_the_window`). One scored
    positionally has no date to compare a bound against: honouring the window
    is impossible, and dropping it would report a cost over the whole run under
    the name of a windowed one.
    """
    if scoring_window is None or not any(bound is not None for bound in scoring_window):
        return
    dated = set(observing) | {
        str(name) for name, output in outputs.items() if output.support == "network"
    }
    dateless_by_block: dict[str, list[str]] = {}
    for block in objective_blocks:
        dateless = sorted(
            str(name)
            for name in block.uses_outputs
            if str(name) in outputs and str(name) not in dated
        )
        if dateless:
            dateless_by_block[str(block.name)] = dateless
    if dateless_by_block:
        start, end = scoring_window
        listed = "; ".join(
            f"block {name!r} on output(s) {outputs_}"
            for name, outputs_ in dateless_by_block.items()
        )
        raise ValueError(
            f"scoring_window {_day(start)} to {_day(end)} cannot be applied to {listed}: "
            "those outputs are scored on extracted value vectors, which carry no time axis "
            "to cut on. Point them at a loaded record with 'observes', or score on a single "
            "variable."
        )
    if boundaries is not None:
        refuse_a_network_state_outside_the_window(
            outputs, objective_blocks, scoring_window, boundaries
        )


def network_state_period(time: Any, boundaries: Sequence[Any] | None, *, n_periods: int) -> int:
    """Return the index of the period a one-state network output reads.

    ``time`` is the output's ``"first"``, ``"last"`` or ISO date, resolved as
    :func:`hydromodpy.core.time.selection.resolve_instant` does: a date reads
    the period ``[s, e)`` that holds it. A steady phase runs one period over
    its window, so every date of that window reads its one state. A run of one
    period with no dates serves that state to any selector: nothing is there to
    tell a date from another. ``boundaries`` are the run's ``n_periods + 1``
    time-grid bounds, or ``None``.
    """
    edges = boundaries if boundaries is not None and len(boundaries) >= 2 else None
    if edges is None and n_periods == 1:
        return 0
    return resolve_instant(time, edges, n_periods=n_periods)


def network_state_stamp(time: Any, boundaries: Sequence[Any] | None) -> pd.Timestamp | None:
    """Return the stamp of the state a one-state network output reads, or ``None``.

    The stamp closes its period, as every state of the run is stamped. ``None``
    when the run carries no time grid to date it with.
    """
    if boundaries is None or len(boundaries) < 2:
        return None
    index = network_state_period(time, boundaries, n_periods=len(boundaries) - 1)
    return _naive_utc(boundaries[index + 1])


def refuse_a_network_state_outside_the_window(
    outputs: Mapping[str, CalibOutputDecl],
    objective_blocks: list[CalibObjectiveBlockDecl],
    scoring_window: tuple[Any, Any] | None,
    boundaries: Sequence[Any] | None,
) -> None:
    """Refuse a network state the window does not hold, naming both.

    A network output read in one state is dated at the stamp that closes the
    period it reads, and the window keeps a stamp from ``start`` to ``end``,
    both included, as it keeps the stamps of a series. A state outside the
    window would be scored under the name of a windowed cost. A date the run
    does not hold is refused here too, by the output that names it. Nothing is
    checked without a time grid: the stamp is unknown there.
    """
    if scoring_window is None or not any(bound is not None for bound in scoring_window):
        return
    if boundaries is None or len(boundaries) < 2:
        return
    start, end = (_naive_utc(bound) for bound in scoring_window)
    read = {str(name) for block in objective_blocks for name in block.uses_outputs}
    for name in sorted(read):
        output = outputs.get(name)
        if output is None or output.support != "network":
            continue
        if getattr(output, "extent", None) is not None:
            continue
        time = getattr(output, "time", "last")
        try:
            index = network_state_period(time, boundaries, n_periods=len(boundaries) - 1)
        except TimeSelectionError as exc:
            raise ValueError(f"network output {name!r} has time = {time!r}: {exc}") from exc
        stamp = _naive_utc(boundaries[index + 1])
        if (start is None or stamp >= start) and (end is None or stamp <= end):
            continue
        raise ValueError(
            f"scoring_window {_day(start)} to {_day(end)} does not hold the network state "
            f"output {name!r} is scored on: time = {time!r} reads the state of "
            f"{period_label(index, boundaries)}, stamped {_day(stamp)} at the end of its "
            "period. Move the window, or set the output's time to a date inside it."
        )


def network_distance_scales(
    outputs: Mapping[str, CalibOutputDecl], diagnostics: Mapping[str, float] | None
) -> dict[str, list[float]]:
    """Return, per network output, the validity length of each value it produces.

    A one-bound output produces the pair ``(D_so, D_os)`` of its scored bound,
    whose validity length it publishes unsuffixed. A two-bound output produces
    the minimal pair then the maximal one, each with its own length. The
    lengths are the scale ``normalize_cost`` divides a distance by. An output
    whose lengths were not published is left out, and a block that normalises
    it refuses the trial by name.
    """
    scales: dict[str, list[float]] = {}
    found = diagnostics or {}
    for name, output in outputs.items():
        if output.support != "network":
            continue
        n_bounds = int(found.get(f"{name}.n_bounds_scored", 1.0))
        if n_bounds == 2:
            keys = (
                f"{name}.validity_length_m{MINIMAL_SUFFIX}",
                f"{name}.validity_length_m{MAXIMAL_SUFFIX}",
            )
        else:
            keys = (f"{name}.validity_length_m",)
        if not all(key in found for key in keys):
            continue
        scales[str(name)] = [float(found[key]) for key in keys for _ in (0, 1)]
    return scales


def _naive_utc(value: Any) -> pd.Timestamp | None:
    """Return an instant as a naive UTC timestamp, ``None`` when unset."""
    if value is None:
        return None
    stamp = pd.Timestamp(value)
    if stamp.tz is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp


def _day(value: Any) -> str:
    """Return a window bound as a reader writes it: its date at midnight, else the instant."""
    if value is None:
        return "open"
    stamp = pd.Timestamp(value)
    if stamp == stamp.normalize():
        return stamp.strftime("%Y-%m-%d")
    return stamp.isoformat()


class ObservableScorer:
    """Score comparable series and separately prepared network distances.

    Producers own spatial extraction and runoff corrections. Network values
    are prepared distance pairs, never raw release fields. Observations are
    keyed by output name and are loaded before this scorer is built.
    """

    def __init__(
        self,
        outputs: Mapping[str, CalibOutputDecl],
        objective_blocks: list[CalibObjectiveBlockDecl],
        *,
        observed_records: Mapping[str, pd.Series] | None = None,
        warmup_periods: int = 0,
        scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
        min_samples: int = 1,
    ) -> None:
        refuse_window_without_dates(
            outputs, objective_blocks, scoring_window, observing_outputs(outputs)
        )
        self._outputs: dict[str, CalibOutputDecl] = dict(outputs)
        self._cfg: SimpleNamespace = SimpleNamespace(
            outputs=dict(outputs),
            objective_blocks=list(objective_blocks),
            warmup_periods=int(warmup_periods),
        )
        self._observed: dict[str, pd.Series] = dict(observed_records or {})
        self._scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = (
            scoring_window
        )
        self._min_samples: int = min_samples
        # A discharge is averaged over each period, a head or a lake stage is
        # read at the stamp: fixed by the declared variable, once.
        self._time_methods: dict[str, str] = output_time_methods(outputs)
        # A normalised network distance is divided by the validity length the
        # trial itself publishes, so its objective is built per trial.
        self._scales_distances: bool = any(
            block.normalize_cost
            and any(
                getattr(outputs.get(str(name)), "support", None) == "network"
                for name in block.uses_outputs
            )
            for block in objective_blocks
        )
        self._composite: Objective | None = (
            None
            if self._observed or self._scales_distances
            else build_objective_from_config(self._cfg)
        )
        # The window is faced with the network states once, on the first time
        # grid a trial brings: every trial of a search runs the same grid.
        self._states_checked: bool = False

    def pair(
        self,
        observables: Mapping[str, ObservableResult],
        *,
        boundaries: Sequence[Any] | None = None,
    ) -> PairedOutputs:
        """Return the vectors a cost is computed from, without computing it.

        A linearized covariance needs the simulated value AT EACH OBSERVATION,
        which scoring reduces to one number. This stops one step earlier, on
        the same alignment: same records, same window, same minimum overlap,
        because residuals taken against a different pairing than the one the
        search followed would describe the slope of a surface nobody climbed.

        Only the outputs that name a station are aligned. A network pair, or a
        vector typed into the document, carries no date and no record to take
        a residual against.

        ``boundaries`` are the run's time-grid bounds, from which each series
        takes the start of its first period, as in :meth:`score`.
        """
        if not self._observed:
            raise ValueError(
                "no calibration output names a station to be compared against, so there is "
                'no residual to align. Declare observes = "<station>" on the outputs this '
                "calibration is fitted to."
            )
        dated: dict[str, pd.Series] = {}
        starts: dict[str, Any] = {}
        for name in self._observed:
            result = observables.get(name)
            if result is None:
                continue
            series = dated_series(select_observable_times(result, self._outputs[name].time))
            if series is not None:
                dated[name] = series
                starts[name] = selected_period_start(result, series, boundaries)
        return self._align(dated, starts)

    def _align(self, series: Mapping[str, pd.Series], starts: Mapping[str, Any]) -> PairedOutputs:
        """The one place a record meets an answer, for the cost and the residuals."""
        return pair_outputs_with_observations(
            observed=self._observed,
            simulated={name: series[name] for name in self._observed if name in series},
            scoring_window=self._scoring_window,
            min_samples=self._min_samples,
            time_methods=self._time_methods,
            period_starts=starts,
        )

    def score(
        self,
        observables: Mapping[str, ObservableResult],
        *,
        network_values: Mapping[str, Sequence[float]] | None = None,
        diagnostics: Mapping[str, float] | None = None,
        boundaries: Sequence[Any] | None = None,
    ) -> tuple[float, dict[str, float]]:
        """Return the cost and components from one model's outputs.

        ``boundaries`` are the run's time-grid bounds. A dated output takes
        the start of its first period from them, which a single steady stamp
        cannot tell on its own (:func:`selected_period_start`). They also date
        the state a network output is read at, which the window has to hold.
        """
        if not self._states_checked and boundaries is not None and len(boundaries) >= 2:
            refuse_a_network_state_outside_the_window(
                self._outputs, self._cfg.objective_blocks, self._scoring_window, boundaries
            )
            self._states_checked = True
        simulated: dict[str, Sequence[float]] = {}
        series: dict[str, pd.Series] = {}
        starts: dict[str, Any] = {}
        for name, output in self._outputs.items():
            if output.support == "network":
                if network_values is None or name not in network_values:
                    raise ValueError(f"Output {name!r} needs prepared network distances")
                simulated[name] = network_values[name]
                continue
            result = observables.get(name)
            if result is None or np.asarray(result.values).size == 0:
                raise NotImplementedError(
                    f"Model returned no calibration values for output {name!r}"
                )
            selected = select_observable_times(result, output.time)
            simulated[name] = slice_time(selected.values, "all", output.reducer)
            dated = dated_series(selected)
            if dated is not None:
                series[name] = dated
                starts[name] = selected_period_start(result, dated, boundaries)

        objective = self._composite
        paired_counts: dict[str, int] = {}
        paired_dates: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
        observed_by_output: Mapping[str, Sequence[float]] | None = None
        if self._observed:
            paired = self._align(series, starts)
            simulated.update(paired.simulated)
            paired_counts = dict(paired.n_paired)
            paired_dates = dict(paired.dates)
            observed_by_output = paired.observed
        if objective is None:
            objective = build_objective_from_config(
                self._cfg,
                observed_by_output=observed_by_output,
                distance_scales=(
                    network_distance_scales(self._outputs, diagnostics)
                    if self._scales_distances
                    else None
                ),
            )
        try:
            value = objective.evaluate(simulated)
        except Exception as exc:
            logger.exception("Composite objective evaluation failed")
            raise RuntimeError(
                f"Composite objective evaluation failed: {type(exc).__name__}: {exc}"
            ) from exc
        components = {key: float(val) for key, val in value.components.items()}
        components.update({key: float(val) for key, val in (diagnostics or {}).items()})
        components.update(
            {f"{name}.n_paired": float(count) for name, count in paired_counts.items()}
        )
        # Dates are not a float, and components carries only floats, so the
        # retained span travels as an ordinal day number -- day precision is
        # all a hydrological record needs, and it survives the round trip
        # through EvaluationResult.components with no timezone ambiguity.
        for name, (start, end) in paired_dates.items():
            components[f"{name}.date_start"] = float(pd.Timestamp(start).toordinal())
            components[f"{name}.date_end"] = float(pd.Timestamp(end).toordinal())
        return float(value.total), components


def selected_period_start(
    result: ObservableResult,
    selected: pd.Series,
    boundaries: Sequence[Any] | None,
) -> pd.Timestamp | None:
    """Return the start of the first period a time-selected output stands for.

    The run's time-grid bounds answer when the caller has them. Otherwise the
    output's own stamps, before ``time`` selected among them, do: an output
    kept at ``time = "last"`` closes the period that starts at the stamp
    before it, not the whole run. ``None`` when neither can tell, for a single
    stamp with no grid.
    """
    bounds: Sequence[Any] | None = boundaries
    if bounds is None or len(bounds) == 0:
        times = getattr(result, "times", None)
        if times is None or pd.DatetimeIndex(times).nunique() < 2:
            return None
        bounds = tuple(period_edges(times))
    return first_period_start(selected.index, bounds)


def _first_period_start(series: pd.Series, boundaries: Sequence[Any] | None) -> Any:
    """Return the start of the first period of a dated series, or ``None``."""
    if not isinstance(series.index, pd.DatetimeIndex):
        return None
    return first_period_start(series.index, boundaries)


def discharge_target(observed: Sequence[ObservedSeries], declared_station_id: str | None):
    """Return the observed station whose cost the optimizer minimises.

    Every loaded gauge is compared to the simulated discharge AT ITS OWN
    POSITION, the way ``head`` already is: the producer gives each one its cell
    and reads the discharge routed to it, with its runoff scaled by the area
    that cell drains. Each cost is reported as ``cost:<objective>@<station_id>``.

    What this function picks is which of those costs the search follows. One
    station drives it and the others stay diagnostic, because a weighted sum
    across gauges needs weights, an error model and a decision about nested
    gauges sharing the same water, none of which this single-metric route
    carries. Averaging them, which is what this did before, gave every gauge the
    same say whatever its record was worth.
    """
    if not observed:
        raise ValueError("No observed discharge station is available for calibration")
    by_id = {rec.station_id: rec for rec in observed}
    if declared_station_id is not None:
        target = by_id.get(str(declared_station_id))
        if target is None:
            raise ValueError(
                f"calibration.observed_station_id={declared_station_id!r} is not among the "
                f"loaded discharge stations {sorted(by_id)}. Check the id, or the "
                "station_ids / extent of the hydrometry source that loads it."
            )
        return target
    if len(observed) == 1:
        return observed[0]
    raise ValueError(
        f"{len(observed)} discharge stations are loaded ({sorted(by_id)}) but a trial can only "
        "read one simulated discharge series here, the whole-catchment outlet: this "
        "single-metric route holds one variable and one objective, nothing to keep a cost per "
        "gauge. Comparing each gauge at its own position needs the weighted-block route "
        "instead, one per-cell discharge observable per station: declare "
        '[calibration.outputs.<name>] variable = "discharge", support = "cell", its own '
        'row/col/layer, and observes = "<station>", one block per output. Score the gauge '
        "that sits at the outlet here by naming it in calibration.observed_station_id (or on "
        "the phase), or load only that one with station_ids on the hydrometry source. The "
        "others stay reported, unscored."
    )


class StationScorer:
    """Score one variable at the stations a project loaded, out of a context.

    The single-metric route of a document -- ``variable`` and ``objective``,
    no block -- used to be one function that resolved the flow adapter, placed
    every gauge on the mesh, read its series and scored it. The second half of
    that is what this holds: the observed records, the criterion, the burn-in
    and the window are bound once, before the search, and one sample is scored
    from the observables a producer answered with. Nothing here reads a trial
    context, so a model that is not the HydroModPy pipeline is scored by the
    same criterion on the same terms.

    A station is keyed by its id, which is how the records are keyed, so a
    producer answers in the vocabulary the project loaded. One the producer
    could not serve is left unscored rather than invented: a gauge whose cell
    falls outside the mesh has no simulated counterpart, and that has always
    been reported as a missing component. The one exception is the station that
    drives the search, whose absence is refused by name.
    """

    SUPPORTED: ClassVar[tuple[str, ...]] = ("discharge", "head", "lake_level")
    """The variables a loaded observation family exists for."""

    def __init__(
        self,
        variable: str,
        objective: str,
        observed: Sequence[ObservedSeries],
        *,
        observed_station_id: str | None = None,
        warmup_periods: int = 0,
        scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    ) -> None:
        if str(variable) not in self.SUPPORTED:
            raise NotImplementedError(
                f"Calibration variable {variable!r} is not supported on the single-metric "
                f"route. Supported: {', '.join(self.SUPPORTED)}."
            )
        self._variable = str(variable)
        self._objective = str(objective)
        # A head or a lake level is the state at the stamp, a discharge the
        # mean over the period the stamp closes.
        self._time_method = time_method_for(self._variable)
        self._observed: list[ObservedSeries] = list(observed)
        self._warmup_periods = int(warmup_periods)
        self._scoring_window = scoring_window
        # Which gauge drives the search is a property of the document, so it is
        # resolved once here and not re-derived for every sample.
        self._target: ObservedSeries | None = (
            discharge_target(self._observed, observed_station_id)
            if self._variable == "discharge"
            else None
        )
        self._unscored: set[str] = set()

    @property
    def target_station_id(self) -> str | None:
        """The station the search follows, or ``None`` when every one is averaged."""
        return None if self._target is None else self._target.station_id

    def score(
        self,
        simulated: Mapping[str, ObservableResult],
        *,
        source: str = "the model",
        boundaries: Sequence[Any] | None = None,
    ) -> tuple[float, dict[str, float]]:
        """Return the cost the search follows and the cost of every station.

        ``boundaries`` are the run's time-grid bounds, from which each series
        takes the start of its first period.
        """
        components: dict[str, float] = {}
        finite: list[float] = []
        for record in self._observed:
            result = simulated.get(record.station_id)
            if result is None:
                if self._target is not None and record.station_id == self._target.station_id:
                    raise NotImplementedError(
                        f"{source} served no {self._variable} for station "
                        f"{record.station_id!r}, which is the one the search follows."
                    )
                self._say_it_went_unscored(record.station_id, source)
                continue
            series = observable_series(result, name=self._variable)
            if series.empty:
                raise NotImplementedError(
                    f"{source} returned no {self._variable} calibration series for station "
                    f"{record.station_id!r}"
                )
            cost = score_series(
                record.series,
                series,
                self._objective,
                warmup_periods=self._warmup_periods,
                scoring_window=self._scoring_window,
                time_method=self._time_method,
                period_start=_first_period_start(series, boundaries),
            )
            components[f"cost:{self._objective}@{record.station_id}"] = cost
            if np.isfinite(cost):
                finite.append(cost)
        return self._followed_cost(components, finite), components

    def _say_it_went_unscored(self, station_id: str, source: str) -> None:
        """Say once that a station is reported without a cost.

        A gauge whose cell falls outside the mesh has no simulated counterpart
        and is left out rather than invented, which is what this route has
        always done. Said out loud because the alternative is a station that
        disappears from a report between two runs without a line anywhere: the
        component it used to carry is simply absent. Once per scorer, not once
        per trial, because a search calls this a thousand times.

        The engine dispatches trials through a thread pool and this scorer is
        shared by all of them, so the worst a race can do here is print the
        same line twice. Nothing else on this object is written after
        construction.
        """
        if station_id in self._unscored:
            return
        self._unscored.add(station_id)
        logger.warning(
            "%s served no %s for station %r: it is reported without a cost and the search "
            "does not follow it.",
            source,
            self._variable,
            station_id,
        )

    def _followed_cost(self, components: Mapping[str, float], finite: Sequence[float]) -> float:
        """Reduce the per-station costs to the one number the optimizer reads."""
        if self._target is not None:
            primary = components[f"cost:{self._objective}@{self._target.station_id}"]
            if not np.isfinite(primary):
                raise ValueError(
                    f"Discharge cost at the calibration station {self._target.station_id!r} is "
                    f"{primary}. Check the observed record covers the scored window."
                )
            return float(primary)
        if not finite:
            raise ValueError(
                f"No finite {self._variable.replace('_', '-')} calibration costs were produced"
            )
        return float(np.mean(finite))
