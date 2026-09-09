"""Composite metric extractors.

The ``build_metric_extractor`` factory and its composite variant live here.
They wire ``CalibrationConfig.outputs`` and ``objective_blocks`` to the solver
extractors and produce the ``(primary, components)`` payload consumed by the
calibration engine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.metrics.scalar import score
from hydromodpy.calibration.metrics.series import (
    add_runoff_to_discharge,
    load_observed,
    resolve_time_index,
)
from hydromodpy.calibration.metrics.solver_extract import (
    extract_outputs,
    observable_series,
    resolve_flow_adapter,
    resolve_station_cells,
)
from hydromodpy.calibration.optim.objective import build_objective_from_config
from hydromodpy.core.contracts.observables import ObservableRequest
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


def _discharge_target(observed: list, declared_station_id: str | None):
    """Return the single observed station the outlet discharge is scored against.

    A gauge should be compared to the simulated discharge AT ITS OWN POSITION,
    the way ``head`` already is: ``resolve_station_cells`` gives each piezometer
    its own cell. Discharge cannot do that yet. No solver adapter serves it
    anywhere but ``support="domain"``, so the only simulated series a trial can
    read is the whole-catchment outlet.

    Until a per-cell discharge observable exists, one station is scored and the
    others are reported without scoring. Averaging them, which is what this did
    before, compared an upstream gauge draining a smaller area against the
    outlet series it cannot reproduce, and let that impossible fit move the
    parameters.
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


def _series_for(results: Mapping[str, Any], request_id: str, *, name: str) -> pd.Series:
    """Read one observable out of a batch, or say which one is missing."""
    result = results.get(request_id)
    if result is None:
        raise NotImplementedError(f"Solver returned no {name} observable for {request_id!r}")
    return observable_series(result, name=name)


def _simulated_discharge_by_station(
    adapter: Any,
    run_ctx: Any,
    trial_ctx: Any,
    observed: list,
    *,
    time_index: Any,
) -> dict[str, pd.Series]:
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

    catchment = _series_for(results, _CATCHMENT, name="discharge")
    if catchment.empty:
        raise NotImplementedError(
            f"Solver {run_ctx.run.solver!r} returned no discharge calibration series"
        )
    # A routed SFR network already carries the runoff: it was injected into the
    # reaches, so adding the forcing again would count it twice. Only a
    # drain-budget discharge is baseflow alone.
    if not results[_CATCHMENT].includes_runoff:
        catchment = add_runoff_to_discharge(catchment, trial_ctx)

    out: dict[str, pd.Series] = {}
    for obs_rec in observed:
        station_id = obs_rec.station_id
        if station_id not in station_cells:
            out[station_id] = catchment
            continue
        result = results[_cell_id(station_id)]
        series = observable_series(result, name="discharge")
        # Same guard as the catchment series, on the same reason: a reach the
        # network routed already carries the runoff it was fed with, and adding
        # the forcing again would count it twice.
        if not result.includes_runoff:
            area = float(np.asarray(results[_area_id(station_id)].values).reshape(-1)[0])
            series = add_runoff_to_discharge(series, trial_ctx, area_m2=area)
        out[station_id] = series
    return out


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
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Return a metric function closed over the loaded observations.

    The returned callable matches the ``TrialMetricFn`` signature:
    ``metric_fn(ctx, *, objective=..., variable=...) -> (primary, metrics)``.

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
            warmup_periods=warmup_periods,
            scoring_window=scoring_window,
        )

    observed = load_observed(ctx, variable) if variable else []
    if not observed:
        logger.warning("No observations for variable=%r.", variable)

    def metric_fn(trial_ctx: Any, *, objective: str = objective, variable: str = variable):
        resolved = resolve_flow_adapter(trial_ctx)
        if resolved is None:
            raise NotImplementedError("No flow solver adapter available for calibration")
        if not observed:
            raise ValueError(f"No observations available for calibration variable {variable!r}")
        adapter, run_ctx = resolved

        time_idx = resolve_time_index(trial_ctx, n_timesteps=0)
        try:
            if variable == "discharge":
                simulated_by_station = _simulated_discharge_by_station(
                    adapter,
                    run_ctx,
                    trial_ctx,
                    observed,
                    time_index=time_idx,
                )
                target = _discharge_target(observed, observed_station_id)
                components: dict[str, float] = {}
                for obs_rec in observed:
                    components[f"cost:{objective}@{obs_rec.station_id}"] = score(
                        obs_rec.series,
                        simulated_by_station[obs_rec.station_id],
                        objective,
                        warmup_periods=warmup_periods,
                        scoring_window=scoring_window,
                    )
                primary = components[f"cost:{objective}@{target.station_id}"]
                if not np.isfinite(primary):
                    raise ValueError(
                        f"Discharge cost at the calibration station {target.station_id!r} is "
                        f"{primary}. Check the observed record covers the scored window."
                    )
                return float(primary), components

            elif variable == "head":
                station_cells = resolve_station_cells(trial_ctx, observed)
                if not station_cells:
                    raise NotImplementedError(
                        "No station-to-cell mapping available for head calibration"
                    )
                components = {}
                costs = []
                # One call for every piezometer: the head file opens once.
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
                        for obs_rec in observed
                        if obs_rec.station_id in station_cells
                    ],
                    time_index=time_idx,
                )
                for obs_rec in observed:
                    if obs_rec.station_id not in station_cells:
                        continue
                    sim = _series_for(results, obs_rec.station_id, name="head")
                    if sim.empty:
                        raise NotImplementedError(
                            f"Solver {run_ctx.run.solver!r} returned no head calibration series"
                        )
                    cost = score(
                        obs_rec.series,
                        sim,
                        objective,
                        warmup_periods=warmup_periods,
                        scoring_window=scoring_window,
                    )
                    components[f"cost:{objective}@{obs_rec.station_id}"] = cost
                    if np.isfinite(cost):
                        costs.append(cost)
                if not costs:
                    raise ValueError("No finite head calibration costs were produced")
                return float(np.mean(costs)), components

            elif variable == "lake_level":
                components = {}
                costs = []
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
                    time_index=time_idx,
                )
                for obs_rec in observed:
                    sim = _series_for(results, obs_rec.station_id, name="stage")
                    if sim.empty:
                        raise NotImplementedError(
                            f"Solver {run_ctx.run.solver!r} returned no lake stage series"
                        )
                    cost = score(
                        obs_rec.series,
                        sim,
                        objective,
                        warmup_periods=warmup_periods,
                        scoring_window=scoring_window,
                    )
                    components[f"cost:{objective}@{obs_rec.station_id}"] = cost
                    if np.isfinite(cost):
                        costs.append(cost)
                if not costs:
                    raise ValueError("No finite lake-level calibration costs were produced")
                return float(np.mean(costs)), components

            else:
                raise NotImplementedError(f"Calibration variable {variable!r} is not supported")
        except Exception:
            logger.exception("Metric extractor failed")
            raise

    return metric_fn


def _build_composite_metric_extractor(
    outputs: Mapping[str, CalibOutputDecl],
    objective_blocks: list[CalibObjectiveBlockDecl],
    *,
    warmup_periods: int = 0,
    scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Build a metric_fn that routes through ``build_objective_from_config``."""
    if scoring_window is not None and any(bound is not None for bound in scoring_window):
        start, end = scoring_window
        # extract_outputs returns plain value vectors, with no date to compare the
        # bounds against. Honouring the window is impossible, and dropping it would
        # report a cost over the whole run under the name of a windowed one.
        raise ValueError(
            f"scoring_window {start} to {end} cannot be applied to the objective "
            f"block(s) {[str(block.name) for block in objective_blocks]}: a block "
            "scores extracted value vectors, which carry no time axis to cut on. "
            "Use warmup_periods, which counts samples, or score on a single variable."
        )
    cfg_subset = SimpleNamespace(
        outputs=dict(outputs),
        objective_blocks=list(objective_blocks),
        warmup_periods=int(warmup_periods),
    )
    composite = build_objective_from_config(cfg_subset)

    def metric_fn(trial_ctx: Any, *, objective: str | None = None, variable: str | None = None):
        del objective, variable
        # extract_outputs already names the output whose declaration is at
        # fault, so there is nothing to add by re-wrapping here. Note that
        # NotImplementedError is a RuntimeError, which is why catching the
        # latter to "pass typed errors through" would swallow the former.
        try:
            simulated_by_output, extraction_diagnostics = extract_outputs(trial_ctx, outputs)
        except Exception:
            logger.exception("Output extraction failed")
            raise

        try:
            value = composite.evaluate(simulated_by_output)
        except Exception as exc:
            logger.exception("Composite objective evaluation failed")
            raise RuntimeError(
                f"Composite objective evaluation failed: {type(exc).__name__}: {exc}"
            ) from exc

        components = {key: float(val) for key, val in value.components.items()}
        # The criterion emits its thirty diagnostics beside the cost, so a
        # session records them in trials.jsonl and in the iteration table
        # without promoting a single run.
        components.update({key: float(val) for key, val in extraction_diagnostics.items()})
        total = float(value.total)
        return total, components

    return metric_fn


__all__ = ["build_metric_extractor"]
