"""What a trial context can answer with, for both scoring routes.

The ``build_metric_extractor`` factory lives here and so does every producer
behind it: resolving the flow adapter, placing a gauge on the mesh, reading the
discharge routed to its cell, adding the runoff forcing to a drain budget and
scaling it by the area that cell drains. All of it is measured in the
pipeline's own terms and none of it can be asked of a model that is not it.

Scoring is the other half and it is not here. Both routes hand their
observables to a scorer of
:mod:`hydromodpy.calibration.metrics.observable_scoring`, which holds no
context: ``[calibration.outputs]`` and ``[[calibration.objective_blocks]]`` go
to :class:`~hydromodpy.calibration.metrics.observable_scoring.ObservableScorer`,
``variable`` and ``objective`` to
:class:`~hydromodpy.calibration.metrics.observable_scoring.StationScorer`.
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
    StationScorer,
    observable_series,
    refuse_window_without_dates,
)
from hydromodpy.calibration.metrics.observed_pairing import (
    observed_series_for_outputs,
    observing_outputs,
)
from hydromodpy.calibration.metrics.series import (
    add_runoff_to_discharge,
    load_observed,
    resolve_time_index,
)
from hydromodpy.calibration.metrics.solver_extract import (
    extract_outputs,
    report_the_area_a_gauge_drains,
    resolve_flow_adapter,
    resolve_station_cells,
)
from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.exceptions import UncertaintyNotAvailableError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibOutputDecl

logger = get_logger(__name__)

# Station id the discharge target uses when a run has a single catchment outlet.
_CATCHMENT = "_catchment"


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
    requests = [ObservableRequest(id=_CATCHMENT, name="discharge", support="domain")]
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
        results = adapter.extract_observables(run_ctx, None, requests, time_index=time_index)
    except Exception as exc:
        if len(requests) == 1:
            raise
        logger.warning(
            "Per-cell discharge is unavailable on solver %r (%s); every gauge is scored "
            "against the catchment outlet series, which is only right for the outlet one.",
            run_ctx.run.solver,
            exc,
        )
        results = adapter.extract_observables(run_ctx, None, requests[:1], time_index=time_index)
        station_cells = {}

    whole = _result_for(results, _CATCHMENT, name="discharge")
    catchment = observable_series(whole, name="discharge")
    if catchment.empty:
        raise NotImplementedError(
            f"Solver {run_ctx.run.solver!r} returned no discharge calibration series"
        )
    # A routed SFR network already carries the runoff: it was injected into the
    # reaches, so adding the forcing again would count it twice. Only a
    # drain-budget discharge is baseflow alone.
    if not whole.includes_runoff:
        catchment = add_runoff_to_discharge(catchment, trial_ctx)

    out: dict[str, ObservableResult] = {}
    for obs_rec in observed:
        station_id = obs_rec.station_id
        if station_id not in station_cells:
            out[station_id] = _corrected(whole, catchment, request_id=station_id)
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
    results = adapter.extract_observables(
        run_ctx,
        None,
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
    results = adapter.extract_observables(
        run_ctx,
        None,
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

Keyed on the vocabulary :attr:`StationScorer.SUPPORTED` declares, so the route
a document names is either produced and scored or refused by the scorer before
a search starts. A test holds the two in step."""


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
    extractor is built. Honouring a different pair at call time would score a
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
    warmup_periods: int = 0,
    scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    observed_station_id: str | None = None,
    min_samples: int = 1,
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Return a metric function closed over the loaded observations.

    The returned callable matches the ``TrialMetricFn`` signature:
    ``metric_fn(ctx, *, objective=..., variable=...) -> (primary, metrics)``.
    Both arguments have to repeat what the extractor was built on, and a call
    that renames either is refused: the producer, the loaded records and the
    gauge the search follows are all chosen here, so a criterion swapped at
    call time would report a cost the document cannot account for.

    When ``outputs`` and ``objective_blocks`` are both provided, the extractor
    routes through :func:`build_objective_from_config`. Otherwise the
    single-metric path runs against ``loaded_data`` (variable + objective).
    Both branches are supported: the single-metric one is the standard TOML
    route taken whenever no ``objective_blocks`` are declared.

    ``warmup_periods`` reaches both branches. ``scoring_window`` bounds the
    scored samples in dates, which only the single-metric branch can do: the
    composite branch scores plain value vectors that carry no time axis to cut
    on, so a window declared with objective blocks is refused rather than
    ignored.
    """
    if outputs and objective_blocks:
        return _build_composite_metric_extractor(
            outputs,
            objective_blocks,
            ctx=ctx,
            warmup_periods=warmup_periods,
            scoring_window=scoring_window,
            min_samples=min_samples,
        )

    observed = load_observed(ctx, variable) if variable else []
    if not observed:
        logger.warning("No observations for variable=%r.", variable)
    # Built once, before the search: the records, the criterion, the burn-in and
    # the window do not move between samples, and none of them needs a context.
    route = str(variable) if variable else None
    scorer = (
        StationScorer(
            route,
            objective,
            observed,
            observed_station_id=observed_station_id,
            warmup_periods=warmup_periods,
            scoring_window=scoring_window,
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
                observed,
                time_index=resolve_time_index(trial_ctx, n_timesteps=0),
            )
            return scorer.score(produced, source=f"Solver {run_ctx.run.solver!r}")
        except Exception:
            logger.exception("Metric extractor failed")
            raise

    return metric_fn


def _build_composite_metric_extractor(
    outputs: Mapping[str, CalibOutputDecl],
    objective_blocks: list[CalibObjectiveBlockDecl],
    *,
    ctx: Any = None,
    warmup_periods: int = 0,
    scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    min_samples: int = 1,
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Build a metric_fn that routes through ``build_objective_from_config``."""
    observing = observing_outputs(outputs)
    refuse_window_without_dates(outputs, objective_blocks, scoring_window, observing)
    observed_records = observed_series_for_outputs(outputs, ctx) if observing else {}
    scorer = ObservableScorer(
        outputs,
        objective_blocks,
        observed_records=observed_records,
        warmup_periods=warmup_periods,
        scoring_window=scoring_window,
        min_samples=min_samples,
    )

    def metric_fn(trial_ctx: Any, *, objective: str | None = None, variable: str | None = None):
        # Dropped, not refused, unlike the single-metric route: this one is not
        # parametrised by the pair. The criterion, the weights and the compared
        # quantities are the blocks, so there is nothing a call could rename.
        del objective, variable
        # extract_outputs already names the output whose declaration is at
        # fault, so there is nothing to add by re-wrapping here. Note that
        # NotImplementedError is a RuntimeError, which is why catching the
        # latter to "pass typed errors through" would swallow the former.
        try:
            extracted = extract_outputs(trial_ctx, outputs)
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
        )

    return metric_fn


def refuse_a_burn_in_the_residuals_cannot_honour(
    outputs: Mapping[str, CalibOutputDecl],
    objective_blocks: list[CalibObjectiveBlockDecl],
    warmup_periods: int,
) -> None:
    """Refuse a linearized width on a calibration whose cost drops leading samples.

    A first-order width is read off the residual AT EACH OBSERVATION. A cost is
    not: leading samples are dropped before it is computed, by a block's own
    ``warmup`` on the composite route and by ``[calibration].warmup_periods``
    reaching the criterion on the single-metric one. Two blocks may even drop
    different counts, so there is no single vector that is both aligned once
    and scored by everything. A covariance built on the untruncated pairing
    describes the slope of a surface the search never climbed, over a window it
    was told to ignore.

    What is inspected is the burn-in applied to the outputs a residual is
    actually taken from, which is exactly the ones that name a station. A block
    that names none of them truncates nothing this reads, and a document that
    declares no block at all truncates through the criterion instead, which is
    the route the calibration-wide setting reaches.
    """
    observing = observing_outputs(outputs)
    if not observing:
        return
    default = int(warmup_periods or 0)
    if not objective_blocks:
        if default <= 0:
            return
        raise UncertaintyNotAvailableError(
            f"a linearized width is taken from the residual at each observation, and "
            f"[calibration].warmup_periods drops the first {default} sample(s) before the "
            "cost is computed. The residuals would then cover a window the search was told "
            "to ignore. Score the burn-in out with scoring_window, which cuts the record "
            "itself, or read the width with uncertainty.method = 'cost_profile'."
        )
    burnt: dict[str, int] = {}
    for block in objective_blocks:
        if not any(str(name) in observing for name in block.uses_outputs):
            continue
        declared = getattr(block, "warmup", None)
        effective = default if declared is None else int(declared)
        if effective > 0:
            burnt[str(block.name)] = effective
    if not burnt:
        return
    listed = ", ".join(f"{name} drops {count}" for name, count in sorted(burnt.items()))
    raise UncertaintyNotAvailableError(
        f"a linearized width is taken from the residual at each observation, and block(s) "
        f"{listed} leading sample(s) before scoring. The residuals would then cover a window "
        "the search was told to ignore. Score the burn-in out with scoring_window, which "
        "cuts the record itself, or read the width with uncertainty.method = 'cost_profile'."
    )


def build_paired_vector_capture(
    outputs: Mapping[str, CalibOutputDecl],
    *,
    ctx: Any,
    objective_blocks: list[CalibObjectiveBlockDecl] | None = None,
    warmup_periods: int = 0,
    scoring_window: tuple[Any, Any] | None = None,
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
    refuse_a_burn_in_the_residuals_cannot_honour(outputs, blocks, warmup_periods)
    scorer = ObservableScorer(
        outputs,
        blocks,
        observed_records=observed_records,
        warmup_periods=warmup_periods,
        scoring_window=scoring_window,
        min_samples=min_samples,
    )
    captured: dict[str, Any] = {}

    def metric_fn(trial_ctx: Any, *, objective: Any = None, variable: Any = None):
        del objective, variable
        paired = scorer.pair(extract_outputs(trial_ctx, outputs).observables)
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
    "refuse_a_burn_in_the_residuals_cannot_honour",
]
