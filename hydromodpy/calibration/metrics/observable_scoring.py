"""Score model observables without a live workflow context.

One route scores every trial: named observables in, a cost and its components
out, through :class:`ObservableScorer` and the blocks of
:mod:`hydromodpy.calibration.optim.objective`. Nothing here touches a trial
context, a solver adapter or a mesh, which is what lets a model that is not
HydroModPy be scored by the criteria of a HydroModPy document.

:class:`ObservableScorer` reads ``[calibration.outputs]`` and
``[[calibration.objective_blocks]]``. :class:`StationBlockScorer` is the
one-line form, ``variable`` and ``objective``: it turns the records a project
loaded into one implicit output and one implicit block per station
(:func:`hydromodpy.calibration.config.implicit_station_scoring`) and hands the
answers, keyed by station, to an :class:`ObservableScorer`.

What stays with the producer is everything measured in one model's own terms:
resolving the flow adapter, placing a station on a mesh, adding the runoff
forcing to a drain budget and scaling it by the area a cell drains, preparing
the two distances of a stream network. A scorer that carried those would be
advertising a shape only HydroModPy can produce.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.config import STATION_VARIABLES, implicit_station_scoring
from hydromodpy.calibration.metrics.downslope_network import MAXIMAL_SUFFIX, MINIMAL_SUFFIX
from hydromodpy.calibration.metrics.observed_pairing import (
    PairedOutputs,
    observing_outputs,
    output_time_methods,
    pair_outputs_with_observations,
)
from hydromodpy.calibration.optim.objective import SimulationOutput, build_objective_from_config
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.period_aggregation import period_edges, periods_in_window
from hydromodpy.core.time.selection import TimeSelectionError, period_label, resolve_state
from hydromodpy.results.derive.time_alignment import first_period_start

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibOutputDecl, OutputTime
    from hydromodpy.calibration.metrics.series import ObservedSeries
    from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink
    from hydromodpy.calibration.optim.objective import Objective

logger = get_logger(__name__)


def sampling_step_days(index: pd.Index) -> float | None:
    """Median spacing of a dated index, in days.

    ``None`` when the index is not dated or holds fewer than two distinct
    stamps.
    """
    if not isinstance(index, pd.DatetimeIndex) or index.size < 2:
        return None
    gaps = np.diff(index.sort_values().asi8) / 86_400e9
    gaps = gaps[gaps > 0.0]
    return float(np.median(gaps)) if gaps.size else None


def elapsed_days(index: pd.DatetimeIndex) -> np.ndarray:
    """Date of each stamp of *index*, in days since the epoch."""
    return np.asarray(index.asi8, dtype=float) / 86_400e9


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
    if time == "all":
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
    """Rebuild a pandas series from an observable, for the producers.

    An observable that carries a time index keeps it; one that does not falls
    back to a positional index, exactly as the binary readers did before.
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
    positionally has no date to compare a bound against: honoring the window
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


def refuse_a_network_state_outside_the_window(
    outputs: Mapping[str, CalibOutputDecl],
    objective_blocks: list[CalibObjectiveBlockDecl],
    scoring_window: tuple[Any, Any] | None,
    boundaries: Sequence[Any] | None,
) -> None:
    """Refuse a network state the window does not hold, naming both.

    A network output read in one state is dated at the stamp that closes the
    period it reads, and the window keeps a state whose stamp falls on a day
    from ``start`` to ``end``, both included, as it keeps the states of a
    series (:func:`~hydromodpy.core.time.period_aggregation.periods_in_window`).
    A state outside the window would be scored under the name of a windowed
    cost. A date the run
    does not hold is refused here too, by the output that names it. Nothing is
    checked without a time grid: the stamp is unknown there.
    """
    if scoring_window is None or not any(bound is not None for bound in scoring_window):
        return
    if boundaries is None or len(boundaries) < 2:
        return
    start, end = (naive_utc(bound) for bound in scoring_window)
    read = {str(name) for block in objective_blocks for name in block.uses_outputs}
    for name in sorted(read):
        output = outputs.get(name)
        if output is None or output.support != "network":
            continue
        if getattr(output, "extent", None) is not None:
            continue
        time = getattr(output, "time", "last")
        try:
            index = resolve_state(time, boundaries, n_periods=len(boundaries) - 1)
        except TimeSelectionError as exc:
            raise ValueError(f"network output {name!r} has time = {time!r}: {exc}") from exc
        stamp = naive_utc(boundaries[index + 1])
        if periods_in_window([stamp], method="point", start=start, end=end)[0]:
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
    whose lengths were not published is left out, and a block that normalizes
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


def naive_utc(value: Any) -> pd.Timestamp | None:
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
        series_sink: TrialSeriesSink | None = None,
    ) -> None:
        refuse_window_without_dates(
            outputs, objective_blocks, scoring_window, observing_outputs(outputs)
        )
        self._outputs: dict[str, CalibOutputDecl] = dict(outputs)
        self._series_sink = series_sink
        self._stations: dict[str, str] = {
            str(name): str(getattr(decl, "observes", None))
            for name, decl in outputs.items()
            if getattr(decl, "observes", None)
        }
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
        # A normalized network distance is divided by the validity length the
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
        self._warned_dry: set[str] = set()

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
            series_sink=self._series_sink,
            stations=self._stations,
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
        paired_times: dict[str, np.ndarray] = {}
        lost: dict[str, int] = {}
        observed_by_output: Mapping[str, Sequence[float]] | None = None
        if self._observed:
            paired = self._align(series, starts)
            simulated.update(paired.simulated)
            paired_counts = dict(paired.n_paired)
            lost = dict(paired.n_simulated_nan)
            self._say_pairs_were_lost(lost)
            paired_dates = dict(paired.dates)
            paired_times = {name: elapsed_days(index) for name, index in paired.times.items()}
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
        # The sampling step and the paired dates of each dated output travel
        # with the values: a seasonal criterion counts a year in the samples of
        # the series, and reads a gap the pairing left as a gap.
        trial = SimulationOutput(
            sim_id="",
            stations=(),
            times=np.empty(0),
            values=simulated,
            metadata={"sample_days": _sample_days(series), "sample_times": paired_times},
        )
        try:
            value = objective.evaluate(trial)
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
        components.update({f"{name}.n_sim_nan": float(count) for name, count in lost.items()})
        # Dates are not a float, and components carries only floats, so the
        # retained span travels as an ordinal day number -- day precision is
        # all a hydrological record needs, and it survives the round trip
        # through EvaluationResult.components with no timezone ambiguity.
        for name, (start, end) in paired_dates.items():
            components[f"{name}.date_start"] = float(pd.Timestamp(start).toordinal())
            components[f"{name}.date_end"] = float(pd.Timestamp(end).toordinal())
        return float(value.total), components

    def _say_pairs_were_lost(self, lost: Mapping[str, int]) -> None:
        """Warn once per output that a NaN simulated value took pairs out of its cost.

        Once, not once per trial: the count of every trial is in its
        components, ``<output>.n_sim_nan``. A race between threads can at
        worst print the line twice.
        """
        for name, count in lost.items():
            if count == 0 or name in self._warned_dry:
                continue
            self._warned_dry.add(name)
            logger.warning(
                "Output %r lost %d pair(s) of the window because the simulated value is NaN "
                "(a dry cell?): the sample its cost is scored on depends on the trial. "
                "Each trial records the count as %s.n_sim_nan.",
                name,
                count,
                name,
            )


def _sample_days(series: Mapping[str, pd.Series]) -> dict[str, float]:
    """Median spacing of each dated output, in days. Outputs with one stamp are left out."""
    steps: dict[str, float] = {}
    for name, dated in series.items():
        step = sampling_step_days(dated.index)
        if step is not None:
            steps[str(name)] = step
    return steps


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


def discharge_target(observed: Sequence[ObservedSeries], declared_station_id: str | None):
    """Return the discharge station the one-line form scores.

    The gauge is compared to the simulated discharge AT ITS OWN POSITION, the
    way ``head`` already is: the producer gives it its cell and reads the
    discharge routed to it, with its runoff scaled by the area that cell
    drains. One gauge and not several, because a weighted sum across gauges
    needs weights, an error model and a decision about nested gauges sharing
    the same water, none of which ``variable`` + ``objective`` carries: those
    are written as blocks.
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
        "read one simulated discharge series here, the whole-catchment outlet: "
        "variable + objective holds one variable and one objective, nothing to weigh a cost "
        "per gauge. Comparing each gauge at its own position needs the weighted-block route "
        "instead, one per-cell discharge observable per station: declare "
        '[calibration.outputs.<name>] variable = "discharge", support = "cell", its own '
        'row/col/layer, and observes = "<station>", one block per output. Score the gauge '
        "that sits at the outlet here by naming it in calibration.observed_station_id (or on "
        "the phase), or load only that one with station_ids on the hydrometry source."
    )


class StationBlockScorer:
    """Score ``variable`` + ``objective`` through one implicit block per station.

    The records the project loaded are bound once, before the search: each
    scored station becomes an output that observes it and a block that reads
    that output (:func:`~hydromodpy.calibration.config.implicit_station_scoring`),
    and an :class:`ObservableScorer` scores them, as it scores any declared
    block. A discharge scores the one gauge :func:`discharge_target` picks; a
    head or a lake level scores every loaded station, at equal weights.

    A producer answers by station id, the vocabulary the project loaded. A
    station it could not serve, a piezometer whose cell falls outside the mesh,
    is left out of that trial rather than invented, and said so once. The one
    exception is the discharge gauge, whose absence is refused by name.
    """

    def __init__(
        self,
        variable: str,
        objective: str,
        observed: Sequence[ObservedSeries],
        *,
        observed_station_id: str | None = None,
        warmup_periods: int = 0,
        scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
        min_samples: int = 1,
        series_sink: TrialSeriesSink | None = None,
    ) -> None:
        if str(variable) not in STATION_VARIABLES:
            raise NotImplementedError(
                f"Calibration variable {variable!r} is not supported by variable + objective. "
                f"Supported: {', '.join(STATION_VARIABLES)}."
            )
        self._variable = str(variable)
        # Which gauge drives the search is a property of the document, so it is
        # resolved once here and not re-derived for every sample.
        self._target: ObservedSeries | None = (
            discharge_target(observed, observed_station_id)
            if self._variable == "discharge"
            else None
        )
        self._records: list[ObservedSeries] = (
            [self._target] if self._target is not None else _one_record_per_station(observed)
        )
        outputs, blocks = implicit_station_scoring(
            self._variable, str(objective), [record.station_id for record in self._records]
        )
        self._outputs = outputs
        self._blocks = blocks
        self._output_of: dict[str, str] = {
            record.station_id: name for record, name in zip(self._records, outputs, strict=True)
        }
        self._observed: dict[str, pd.Series] = {
            self._output_of[record.station_id]: record.series for record in self._records
        }
        self._options: dict[str, Any] = {
            "warmup_periods": int(warmup_periods),
            "scoring_window": scoring_window,
            "min_samples": int(min_samples),
            "series_sink": series_sink,
        }
        # One scorer per set of served stations; the full set is built here, so
        # what the scorer refuses is refused before the search.
        self._scorers: dict[frozenset[str], ObservableScorer] = {}
        self._scorer_for(frozenset(outputs))
        self._unscored: set[str] = set()

    @property
    def stations(self) -> list[ObservedSeries]:
        """The records a producer is asked to answer for, in scoring order."""
        return list(self._records)

    def _scorer_for(self, served: frozenset[str]) -> ObservableScorer:
        scorer = self._scorers.get(served)
        if scorer is None:
            scorer = ObservableScorer(
                {name: decl for name, decl in self._outputs.items() if name in served},
                [block for block in self._blocks if set(block.uses_outputs) <= served],
                observed_records={
                    name: series for name, series in self._observed.items() if name in served
                },
                **self._options,
            )
            self._scorers[served] = scorer
        return scorer

    def score(
        self,
        simulated: Mapping[str, ObservableResult],
        *,
        source: str = "the model",
        boundaries: Sequence[Any] | None = None,
    ) -> tuple[float, dict[str, float]]:
        """Return the cost and its components from answers keyed by station.

        ``boundaries`` are the run's time-grid bounds, from which each series
        takes the start of its first period.
        """
        answered: dict[str, ObservableResult] = {}
        for record in self._records:
            station = record.station_id
            result = simulated.get(station)
            if result is None:
                if self._target is not None:
                    raise NotImplementedError(
                        f"{source} served no {self._variable} for station {station!r}, "
                        "which is the one the search follows."
                    )
                self._say_it_went_unscored(station, source)
                continue
            if np.asarray(result.values).size == 0:
                raise NotImplementedError(
                    f"{source} returned no {self._variable} calibration series for station "
                    f"{station!r}"
                )
            name = self._output_of[station]
            answered[name] = replace(result, request_id=name)
        if not answered:
            raise ValueError(
                f"{source} served no {self._variable} at any of the stations "
                f"{sorted(self._output_of)}, so no cost can be computed."
            )
        return self._scorer_for(frozenset(answered)).score(answered, boundaries=boundaries)

    def _say_it_went_unscored(self, station_id: str, source: str) -> None:
        """Say once that a station is left out of the cost.

        Once per scorer, not once per trial, because a search calls this a
        thousand times. Trials share this scorer across threads, so the worst
        a race can do here is print the same line twice.
        """
        if station_id in self._unscored:
            return
        self._unscored.add(station_id)
        logger.warning(
            "%s served no %s for station %r: it is left out of the cost and the search "
            "does not follow it.",
            source,
            self._variable,
            station_id,
        )


def _one_record_per_station(observed: Sequence[ObservedSeries]) -> list[ObservedSeries]:
    """Keep the first record of each station, and say which ones were dropped."""
    kept: dict[str, ObservedSeries] = {}
    for record in observed:
        if record.station_id in kept:
            logger.warning(
                "Station %r is loaded twice; the first record is scored and the other ignored.",
                record.station_id,
            )
            continue
        kept[record.station_id] = record
    return list(kept.values())
