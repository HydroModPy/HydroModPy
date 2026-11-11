"""What a trial context can answer with, for both scoring routes.

The ``build_metric_extractor`` factory lives here and so does every producer
behind it: resolving the flow adapter, placing a gauge on the mesh, reading the
discharge routed to its cell, adding the runoff forcing to a drain budget and
scaling it by the area that cell drains. All of it is measured in the
pipeline's own terms and none of it can be asked of a model that is not it.

Scoring is the other half and it is not here. Every trial is scored by the
block route of :mod:`hydromodpy.calibration.metrics.observable_scoring`, which
holds no context: ``[calibration.outputs]`` and
``[[calibration.objective_blocks]]`` go to
:class:`~hydromodpy.calibration.metrics.observable_scoring.ObservableScorer`
directly, ``variable`` and ``objective`` through the implicit blocks of
:class:`~hydromodpy.calibration.metrics.observable_scoring.StationBlockScorer`.
What this module produces is therefore the same thing a forward model produces,
and the criterion that scores it cannot tell which one answered.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.metrics.observable_scoring import (
    ObservableScorer,
    StationBlockScorer,
    observable_series,
    refuse_window_without_dates,
)
from hydromodpy.calibration.metrics.observed_pairing import (
    OBSERVED_FAMILY_BY_VARIABLE,
    observed_series_for_outputs,
    observing_outputs,
)
from hydromodpy.calibration.metrics.series import (
    add_runoff_to_discharge,
    load_observed,
    resolve_time_index,
    time_grid_boundaries,
)
from hydromodpy.calibration.metrics.solver_extract import (
    catchment_area_the_discharge_sums,
    extract_outputs,
    report_the_area_a_gauge_drains,
    resolve_flow_adapter,
    resolve_station_cells,
)
from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import CATCHMENT

if TYPE_CHECKING:
    from hydromodpy.calibration.config_objective import CalibObjectiveBlockDecl
    from hydromodpy.calibration.config_outputs import CalibOutputDecl
    from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink

logger = get_logger(__name__)


def _cell_id(station_id: str) -> str:
    return f"_cell:{station_id}"


def _area_id(station_id: str) -> str:
    return f"_area:{station_id}"


def _result_for(results: Mapping[str, Any], request_id: str, *, name: str) -> ObservableResult:
    """Read one observable out of a batch, or say which one is missing."""
    result = results.get(request_id)
    if result is None:
        raise NotImplementedError(f"Solver returned no {name} observable for {request_id!r}")
    return result


def _corrected(result: ObservableResult, series: pd.Series, *, request_id: str) -> ObservableResult:
    """Carry a runoff-corrected series back into the observable it was read from.

    The correction is a producer's business -- it needs the forcing of this run
    and the area a cell drains -- so what leaves here is the observable a model
    would have answered with had it served the whole streamflow itself.
    """
    index = series.index if isinstance(series.index, pd.DatetimeIndex) else None
    return replace(
        result,
        request_id=request_id,
        values=series.to_numpy(dtype=float),
        times=index,
        includes_runoff=True,
    )


def _discharge_by_station(
    adapter: Any,
    run_ctx: Any,
    trial_ctx: Any,
    observed: list,
    *,
    time_index: Any,
) -> dict[str, ObservableResult]:
    """Return, per station, the simulated discharge AT THAT STATION'S cell.

    A gauge away from the outlet closes a smaller catchment. It is asked for on
    ``support="cell"``, which routes the per-cell aquifer release of every
    package downstream of that cell, and its runoff is scaled by the area that
    cell drains rather than by the whole basin.

    A station whose cell cannot be placed on the mesh falls back to the
    whole-catchment series, which is right for the outlet gauge and says so for
    the others.
    """
    station_cells = resolve_station_cells(trial_ctx, observed, variable="discharge")
    requests = [ObservableRequest(id=CATCHMENT, name="discharge", support="domain")]
    for obs_rec in observed:
        cell = station_cells.get(obs_rec.station_id)
        if cell is None:
            continue
        requests.append(
            ObservableRequest(
                id=_cell_id(obs_rec.station_id), name="discharge", support="cell", cell=cell
            )
        )
        requests.append(
            ObservableRequest(
                id=_area_id(obs_rec.station_id), name="upstream_area", support="cell", cell=cell
            )
        )

    try:
        results = adapter.observables(run_ctx.solver_run, requests, time_index=time_index)
    except Exception as exc:
        if len(requests) == 1:
            raise
        logger.warning(
            "Per-cell discharge is unavailable on solver %r (%s); every gauge is scored "
            "against the catchment outlet series, which is only right for the outlet one.",
            run_ctx.run.solver,
            exc,
        )
        results = adapter.observables(run_ctx.solver_run, requests[:1], time_index=time_index)
        station_cells = {}

    whole = _result_for(results, CATCHMENT, name="discharge")
    catchment = observable_series(whole, name="discharge")
    if catchment.empty:
        raise NotImplementedError(
            f"Solver {run_ctx.run.solver!r} returned no discharge calibration series"
        )
    # A routed SFR network already carries the runoff: it was injected into the
    # reaches, so adding the forcing again would count it twice. Only a
    # drain-budget discharge is baseflow alone.
    if not whole.includes_runoff:
        catchment = add_runoff_to_discharge(
            catchment,
            trial_ctx,
            area_m2=catchment_area_the_discharge_sums(run_ctx, trial_ctx),
        )

    out: dict[str, ObservableResult] = {}
    for obs_rec in observed:
        station_id = obs_rec.station_id
        if station_id not in station_cells:
            # Named after the catchment, so the run does not write it under a station.
            out[station_id] = _corrected(whole, catchment, request_id=CATCHMENT)
            continue
        result = results[_cell_id(station_id)]
        series = observable_series(result, name="discharge")
        # Same guard as the catchment series, on the same reason: a reach the
        # network routed already carries the runoff it was fed with, and adding
        # the forcing again would count it twice.
        if not result.includes_runoff:
            area = float(np.asarray(results[_area_id(station_id)].values).reshape(-1)[0])
            report_the_area_a_gauge_drains(station_id, trial_ctx, area_m2=area)
            series = add_runoff_to_discharge(series, trial_ctx, area_m2=area)
        out[station_id] = _corrected(result, series, request_id=station_id)
    return out


def _head_by_station(
    adapter: Any,
    run_ctx: Any,
    trial_ctx: Any,
    observed: list,
    *,
    time_index: Any,
) -> dict[str, ObservableResult]:
    """Return, per piezometer, the head simulated in the cell it sits in.

    One batch for every station: the head file opens once. A station the mesh
    cannot place is absent from the answer, and the scorer reports it unscored.
    """
    station_cells = resolve_station_cells(trial_ctx, observed)
    if not station_cells:
        raise NotImplementedError("No station-to-cell mapping available for head calibration")
    placed = [obs_rec for obs_rec in observed if obs_rec.station_id in station_cells]
    results = adapter.observables(
        run_ctx.solver_run,
        [
            ObservableRequest(
                id=obs_rec.station_id,
                name="head",
                support="cell",
                cell=station_cells[obs_rec.station_id],
            )
            for obs_rec in placed
        ],
        time_index=time_index,
    )
    return {
        obs_rec.station_id: _result_for(results, obs_rec.station_id, name="head")
        for obs_rec in placed
    }


def _lake_level_by_station(
    adapter: Any,
    run_ctx: Any,
    trial_ctx: Any,
    observed: list,
    *,
    time_index: Any,
) -> dict[str, ObservableResult]:
    """Return, per lake, the stage simulated for it, in one batch."""
    del trial_ctx
    results = adapter.observables(
        run_ctx.solver_run,
        [
            ObservableRequest(
                id=obs_rec.station_id,
                name="stage",
                support="lake",
                key=obs_rec.station_id,
            )
            for obs_rec in observed
        ],
        time_index=time_index,
    )
    return {
        obs_rec.station_id: _result_for(results, obs_rec.station_id, name="stage")
        for obs_rec in observed
    }


PRODUCERS: Mapping[str, Callable[..., dict[str, ObservableResult]]] = {
    "discharge": _discharge_by_station,
    "head": _head_by_station,
    "lake_level": _lake_level_by_station,
}
"""How the pipeline answers a station request, per calibration variable.

Keyed on :data:`hydromodpy.calibration.config.STATION_VARIABLES`, so the
variable a document names is either produced and scored or refused by the
scorer before a search starts. A test holds the two in step."""


def series_at_the_stations(
    ctx: Any, outputs: Mapping[str, CalibOutputDecl]
) -> dict[tuple[str, str], ObservableResult]:
    """Return, per observed station and variable, what the solve simulates there.

    The readers of a trial on the solver files of the run, so a run is scored on
    the numbers its cost was: the same cell, runoff and upstream area, in float64,
    where the stored fields are rounded. An output that observes a station replaces
    the answer of its family, since its declaration (a snap, a support) says where
    it is read. A family the backend cannot serve is logged and left out, and the
    score of the run lists its stations as unscored.
    """
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        if any(load_observed(ctx, family) for family in PRODUCERS):
            logger.warning(
                "The run holds no solver model, as a run resumed at its derive step: "
                "no station series is written and its observed stations are left unscored."
            )
        return {}
    answers: dict[tuple[str, str], ObservableResult] = {}
    variable_of: dict[tuple[str, str], str] = {}
    for family, producer in PRODUCERS.items():
        observed = load_observed(ctx, family)
        try:
            time_index = resolve_time_index(ctx)
            produced = producer(*resolved, ctx, observed, time_index=time_index) if observed else {}
        except Exception:
            logger.warning("The run has no simulated %s at its stations.", family, exc_info=True)
            produced = {}
        for record in observed:
            variable_of[family, record.station_id] = record.variable
            if record.station_id in produced:
                answers[record.station_id, record.variable] = produced[record.station_id]
    for name in observing_outputs(outputs):
        output = outputs[name]
        try:
            family = OBSERVED_FAMILY_BY_VARIABLE[str(output.variable)]
            station = str(output.observes)
            observables = extract_outputs(ctx, {name: output}).observables
            answers[station, variable_of[family, station]] = observables[name]
        except Exception:
            logger.warning("The run has no series for its output %r.", name, exc_info=True)
    return answers


def refuse_a_call_that_renames_the_route(
    route: str | None,
    criterion: str | None,
    *,
    called_variable: str | None,
    called_objective: str | None,
) -> None:
    """Refuse a trial that asks a built extractor for another route.

    ``variable`` picks the producer, the observed family and the gauge the
    search follows; ``objective`` picks the criterion and keys every reported
    component. All four are resolved once, from one document, when the
    extractor is built. Honoring a different pair at call time would score a
    record loaded for one variable through the producer of another, and report
    it under a criterion the session never recorded.
    """
    called_route = str(called_variable) if called_variable else None
    called_criterion = str(called_objective) if called_objective else None
    if called_route == route and called_criterion == criterion:
        return
    raise ValueError(
        f"this metric extractor was built on variable={route!r} objective={criterion!r} "
        f"and was called with variable={called_route!r} objective={called_criterion!r}. "
        "The producer, the observed records and the station the search follows are all "
        "chosen at build time, so the two cannot differ. Build a second extractor."
    )


def build_metric_extractor(
    variable: str | None,
    objective: str | None,
    ctx: Any,
    *,
    outputs: Mapping[str, CalibOutputDecl] | None = None,
    objective_blocks: list[CalibObjectiveBlockDecl] | None = None,
    window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    validation_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    gauge: str | None = None,
    min_samples: int = 1,
    series_sink: TrialSeriesSink | None = None,
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Return a metric function closed over the loaded observations.

    The returned callable matches the ``TrialMetricFn`` signature:
    ``metric_fn(ctx, *, objective=..., variable=...) -> (primary, metrics)``.
    Both arguments have to repeat what the extractor was built on, and a call
    that renames either is refused: the producer, the loaded records and the
    gauge the search follows are all chosen here, so a criterion swapped at
    call time would report a cost the document cannot account for.

    When ``outputs`` and ``objective_blocks`` are both provided, they are
    scored as declared. Otherwise ``variable`` + ``objective`` is read against
    the records the project loaded, as one implicit output and one implicit
    block per scored station (:class:`StationBlockScorer`), and scored by the
    same blocks. Each station is answered by its producer in :data:`PRODUCERS`.

    ``window`` and ``min_samples`` reach both. ``gauge`` is ``[site] gauge``, the
    station a discharge calibration follows when several are loaded.
    ``window`` bounds the scored samples in dates. On declared blocks
    it cuts the outputs that name a station and picks the years of a two-bound
    network output; a block on any other output carries no time axis to cut
    on, so the window is refused there rather than ignored.
    ``validation_window`` is scored beside the cost by the scorer of each route,
    on the series the cost was read from, and never reaches the cost.

    ``series_sink``, when given, is handed to the scorer that is built, which
    records every point/series output's scored series into it as a side
    effect of scoring. Network and spatial outputs are never recorded.
    """
    if outputs and objective_blocks:
        return _build_composite_metric_extractor(
            outputs,
            objective_blocks,
            ctx=ctx,
            window=window,
            validation_window=validation_window,
            min_samples=min_samples,
            series_sink=series_sink,
        )

    observed = load_observed(ctx, variable) if variable else []
    if not observed:
        logger.warning("No observations for variable=%r.", variable)
    # Built once, before the search: the records, the implicit blocks, the
    # burn-in and the window do not move between samples, and none of them
    # needs a context.
    route = str(variable) if variable else None
    scorer = (
        StationBlockScorer(
            route,
            objective,
            observed,
            gauge=gauge,
            window=window,
            validation_window=validation_window,
            min_samples=min_samples,
            series_sink=series_sink,
        )
        if observed
        else None
    )

    criterion = str(objective) if objective else None

    def metric_fn(trial_ctx: Any, *, objective: str = objective, variable: str = variable):
        # First, before anything is resolved or read: a call naming another route
        # is wrong whatever the state of the run it was made on.
        refuse_a_call_that_renames_the_route(
            route, criterion, called_variable=variable, called_objective=objective
        )
        resolved = resolve_flow_adapter(trial_ctx)
        if resolved is None:
            raise NotImplementedError("No flow solver adapter available for calibration")
        if scorer is None:
            raise ValueError(f"No observations available for calibration variable {route!r}")
        adapter, run_ctx = resolved
        try:
            produced = PRODUCERS[route](
                adapter,
                run_ctx,
                trial_ctx,
                scorer.stations,
                time_index=resolve_time_index(trial_ctx, n_timesteps=0),
            )
            return scorer.score(
                produced,
                source=f"Solver {run_ctx.run.solver!r}",
                boundaries=time_grid_boundaries(trial_ctx),
            )
        except Exception:
            logger.exception("Metric extractor failed")
            raise

    return metric_fn


def _build_composite_metric_extractor(
    outputs: Mapping[str, CalibOutputDecl],
    objective_blocks: list[CalibObjectiveBlockDecl],
    *,
    ctx: Any = None,
    window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    validation_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    min_samples: int = 1,
    series_sink: TrialSeriesSink | None = None,
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Build a metric_fn that routes through ``build_objective_from_config``."""
    observing = observing_outputs(outputs)
    refuse_window_without_dates(outputs, objective_blocks, window, observing)
    observed_records = observed_series_for_outputs(outputs, ctx) if observing else {}
    scorer = ObservableScorer(
        outputs,
        objective_blocks,
        observed_records=observed_records,
        window=window,
        validation_window=validation_window,
        min_samples=min_samples,
        series_sink=series_sink,
    )

    def metric_fn(trial_ctx: Any, *, objective: str | None = None, variable: str | None = None):
        # Dropped, not refused, unlike variable + objective: this one is not
        # parametrized by the pair. The criterion, the weights and the compared
        # quantities are the blocks, so there is nothing a call could rename.
        del objective, variable
        # extract_outputs already names the output whose declaration is at
        # fault, so there is nothing to add by re-wrapping here. Note that
        # NotImplementedError is a RuntimeError, which is why catching the
        # latter to "pass typed errors through" would swallow the former.
        try:
            extracted = extract_outputs(trial_ctx, outputs, window=window)
        except Exception:
            logger.exception("Output extraction failed")
            raise

        return scorer.score(
            extracted.observables,
            network_values={
                name: extracted.values[name]
                for name, output in outputs.items()
                if output.support == "network"
            },
            diagnostics=extracted.diagnostics,
            boundaries=time_grid_boundaries(trial_ctx),
        )

    return metric_fn


def build_paired_vector_capture(
    outputs: Mapping[str, CalibOutputDecl],
    *,
    ctx: Any,
    objective_blocks: list[CalibObjectiveBlockDecl] | None = None,
    window: tuple[Any, Any] | None = None,
    min_samples: int = 1,
) -> tuple[Callable[..., tuple[float, dict[str, float]]], dict[str, Any]]:
    """Return a metric function that keeps the paired vectors instead of a cost.

    A linearized covariance needs the simulated value AT EACH OBSERVATION, which
    the scoring path computes and then reduces to a cost. Rather than widen that
    return, this asks the very scorer the search used for the step before the
    reduction, :meth:`ObservableScorer.pair`, and stashes the vectors it aligned.
    One reader, so the records, the window and the minimum overlap cannot drift
    between the cost and the derivatives taken around it. It returns a cost of
    zero because nothing scores it: the caller is taking derivatives, not
    ranking trials.

    The order is fixed by sorting the output names, so the observations line up
    between the reference run and every perturbed one. A run that pairs a different
    number of samples is caught by the Jacobian, which refuses a ragged column.
    """
    blocks = list(objective_blocks or [])
    observed_records = observed_series_for_outputs(outputs, ctx)
    if not observed_records:
        raise ValueError(
            "a linearized covariance is built from residuals, and no calibration output "
            'names a station to be compared against. Declare observes = "<station>" on '
            "the outputs this calibration is fitted to."
        )
    scorer = ObservableScorer(
        outputs,
        blocks,
        observed_records=observed_records,
        window=window,
        min_samples=min_samples,
    )
    captured: dict[str, Any] = {}

    def metric_fn(trial_ctx: Any, *, objective: Any = None, variable: Any = None):
        del objective, variable
        paired = scorer.pair(
            extract_outputs(trial_ctx, outputs, window=window).observables,
            boundaries=time_grid_boundaries(trial_ctx),
        )
        order = sorted(paired.simulated)
        captured["simulated"] = np.concatenate(
            [np.asarray(paired.simulated[name], dtype=float).ravel() for name in order]
        )
        captured["observed"] = np.concatenate(
            [np.asarray(paired.observed[name], dtype=float).ravel() for name in order]
        )
        captured["order"] = tuple(order)
        return 0.0, {}

    return metric_fn, captured


__all__ = [
    "build_metric_extractor",
    "build_paired_vector_capture",
]
