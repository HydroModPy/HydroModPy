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

from hydromodpy.calibration.metrics.observed_pairing import (
    observing_outputs,
    pair_outputs_with_observations,
)
from hydromodpy.calibration.metrics.scalar import score as score_series
from hydromodpy.calibration.optim.objective import build_objective_from_config
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.logging import get_logger

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
) -> None:
    """Refuse a window on the blocks whose outputs carry no dates to cut on.

    An output that names a station is aligned on the simulated timestamps, so a
    window applies to it exactly. One scored positionally has no date to compare
    a bound against: honouring the window is impossible, and dropping it would
    report a cost over the whole run under the name of a windowed one.
    """
    if scoring_window is None or not any(bound is not None for bound in scoring_window):
        return
    dateless_by_block: dict[str, list[str]] = {}
    for block in objective_blocks:
        dateless = sorted(
            str(name)
            for name in block.uses_outputs
            if str(name) in outputs and str(name) not in observing
        )
        if dateless:
            dateless_by_block[str(block.name)] = dateless
    if not dateless_by_block:
        return
    start, end = scoring_window
    listed = "; ".join(
        f"block {name!r} on output(s) {outputs_}" for name, outputs_ in dateless_by_block.items()
    )
    raise ValueError(
        f"scoring_window {start} to {end} cannot be applied to {listed}: those outputs "
        "are scored on extracted value vectors, which carry no time axis to cut on. "
        "Point them at a loaded record with 'observes', use warmup_periods, which "
        "counts samples, or score on a single variable."
    )


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
        self._composite: Objective | None = (
            None if self._observed else build_objective_from_config(self._cfg)
        )

    def score(
        self,
        observables: Mapping[str, ObservableResult],
        *,
        network_values: Mapping[str, Sequence[float]] | None = None,
        diagnostics: Mapping[str, float] | None = None,
    ) -> tuple[float, dict[str, float]]:
        """Return the cost and components from one model's outputs."""
        simulated: dict[str, Sequence[float]] = {}
        series: dict[str, pd.Series] = {}
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
            result = select_observable_times(result, output.time)
            simulated[name] = slice_time(result.values, "all", output.reducer)
            dated = dated_series(result)
            if dated is not None:
                series[name] = dated

        objective = self._composite
        paired_counts: dict[str, int] = {}
        if self._observed:
            paired = pair_outputs_with_observations(
                observed=self._observed,
                simulated={name: series[name] for name in self._observed if name in series},
                scoring_window=self._scoring_window,
                min_samples=self._min_samples,
            )
            simulated.update(paired.simulated)
            paired_counts = dict(paired.n_paired)
            objective = build_objective_from_config(self._cfg, observed_by_output=paired.observed)
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
        return float(value.total), components


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
        "read one simulated discharge series, the whole-catchment outlet: comparing each gauge "
        "at its own position needs a per-cell discharge observable that no solver adapter "
        "serves yet. Score the gauge that sits at the outlet by naming it in "
        "calibration.observed_station_id (or on the phase), or load only that one with "
        "station_ids on the hydrometry source. The others stay reported, unscored."
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
    ) -> tuple[float, dict[str, float]]:
        """Return the cost the search follows and the cost of every station."""
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
