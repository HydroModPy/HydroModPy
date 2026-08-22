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


def _series_for(results: Mapping[str, Any], request_id: str, *, name: str) -> pd.Series:
    """Read one observable out of a batch, or say which one is missing."""
    result = results.get(request_id)
    if result is None:
        raise NotImplementedError(f"Solver returned no {name} observable for {request_id!r}")
    return observable_series(result, name=name)


def build_metric_extractor(
    variable: str | None,
    objective: str | None,
    ctx: Any,
    *,
    outputs: Mapping[str, CalibOutputDecl] | None = None,
    objective_blocks: list[CalibObjectiveBlockDecl] | None = None,
    warmup_periods: int = 0,
    scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Return a metric function closed over the loaded observations.

    The returned callable matches the ``TrialMetricFn`` signature:
    ``metric_fn(ctx, *, objective=..., variable=...) -> (primary, metrics)``.

    When ``outputs`` and ``objective_blocks`` are both provided, the extractor
    routes through :func:`build_objective_from_config`. Otherwise the
    single-metric path runs against ``loaded_data`` (variable + objective).
    Both branches are supported: the single-metric one is the standard TOML
    route taken whenever no ``objective_blocks`` are declared.

    ``scoring_window`` bounds the scored samples in dates. It reaches the
    single-metric branch only: the composite branch scores plain value vectors
    that carry no time axis to cut on.
    """
    if outputs and objective_blocks:
        return _build_composite_metric_extractor(outputs, objective_blocks)

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
                results = adapter.extract_observables(
                    run_ctx,
                    None,
                    [ObservableRequest(id=_CATCHMENT, name="discharge", support="domain")],
                    time_index=time_idx,
                )
                simulated = _series_for(results, _CATCHMENT, name="discharge")
                if simulated.empty:
                    raise NotImplementedError(
                        f"Solver {run_ctx.run.solver!r} returned no discharge calibration series"
                    )
                simulated = add_runoff_to_discharge(simulated, trial_ctx)
                components: dict[str, float] = {}
                costs: list[float] = []
                for obs_rec in observed:
                    cost = score(
                        obs_rec.series,
                        simulated,
                        objective,
                        warmup_periods=warmup_periods,
                        scoring_window=scoring_window,
                    )
                    components[f"cost:{objective}@{obs_rec.station_id}"] = cost
                    if np.isfinite(cost):
                        costs.append(cost)
                if not costs:
                    raise ValueError("No finite discharge calibration costs were produced")
                return float(np.mean(costs)), components

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
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Build a metric_fn that routes through ``build_objective_from_config``."""
    cfg_subset = SimpleNamespace(outputs=dict(outputs), objective_blocks=list(objective_blocks))
    composite = build_objective_from_config(cfg_subset)

    def metric_fn(trial_ctx: Any, *, objective: str | None = None, variable: str | None = None):
        del objective, variable
        try:
            simulated_by_output = extract_outputs(trial_ctx, outputs)
        except RuntimeError:
            logger.exception("Output extraction failed")
            raise
        except Exception as exc:
            logger.exception("Output extraction failed")
            raise RuntimeError(f"Output extraction failed: {type(exc).__name__}: {exc}") from exc

        try:
            value = composite.evaluate(simulated_by_output)
        except Exception as exc:
            logger.exception("Composite objective evaluation failed")
            raise RuntimeError(
                f"Composite objective evaluation failed: {type(exc).__name__}: {exc}"
            ) from exc

        components = {key: float(val) for key, val in value.components.items()}
        total = float(value.total)
        return total, components

    return metric_fn


__all__ = ["build_metric_extractor"]
