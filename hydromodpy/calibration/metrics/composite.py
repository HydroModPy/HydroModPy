"""Composite metric extractors.

The legacy ``build_metric_extractor`` factory and its composite variant live
here. They wire ``CalibrationConfig.outputs`` and ``objective_blocks`` to the
solver extractors and produce the ``(primary, components)`` payload consumed by
the calibration engine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.calibration.metrics.scalar import score
from hydromodpy.calibration.metrics.series import (
    add_runoff_to_discharge,
    load_observed,
    resolve_time_index,
)
from hydromodpy.calibration.metrics.solver_extract import (
    extract_boundary,
    extract_cell,
    extract_point,
    resolve_flow_adapter,
    resolve_station_cells,
)
from hydromodpy.calibration.objective import build_objective_from_config
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibOutputDecl

logger = get_logger(__name__)


def build_metric_extractor(
    variable: str | None,
    objective: str | None,
    ctx: Any,
    *,
    outputs: Mapping[str, CalibOutputDecl] | None = None,
    objective_blocks: list[CalibObjectiveBlockDecl] | None = None,
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Return a metric function closed over the loaded observations.

    The returned callable matches the ``TrialMetricFn`` signature:
    ``metric_fn(ctx, *, objective=..., variable=...) -> (primary, metrics)``.

    When ``outputs`` and ``objective_blocks`` are both provided, the extractor
    routes through :func:`build_objective_from_config`. Otherwise the legacy
    single-metric path runs against ``loaded_data`` (variable + objective).
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
                simulated = adapter.extract_calibration_series(
                    run_ctx,
                    None,
                    variable="discharge",
                    time_index=time_idx,
                )
                if simulated.empty:
                    raise NotImplementedError(
                        f"Solver {run_ctx.run.solver!r} returned no discharge calibration series"
                    )
                simulated = add_runoff_to_discharge(simulated, trial_ctx)
                components: dict[str, float] = {}
                costs: list[float] = []
                for obs_rec in observed:
                    cost = score(obs_rec.series, simulated, objective)
                    components[f"{objective}@{obs_rec.station_id}"] = cost
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
                for obs_rec in observed:
                    cell = station_cells.get(obs_rec.station_id)
                    if cell is None:
                        continue
                    sim = adapter.extract_calibration_series(
                        run_ctx,
                        None,
                        variable="head",
                        station_cells={obs_rec.station_id: cell},
                        time_index=time_idx,
                    )
                    if sim.empty:
                        raise NotImplementedError(
                            f"Solver {run_ctx.run.solver!r} returned no head calibration series"
                        )
                    cost = score(obs_rec.series, sim, objective)
                    components[f"{objective}@{obs_rec.station_id}"] = cost
                    if np.isfinite(cost):
                        costs.append(cost)
                if not costs:
                    raise ValueError("No finite head calibration costs were produced")
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
        simulated_by_output: dict[str, list[float]] = {}
        for name, decl in outputs.items():
            try:
                if decl.support == "point":
                    simulated_by_output[name] = extract_point(trial_ctx, decl)
                elif decl.support == "boundary":
                    simulated_by_output[name] = extract_boundary(trial_ctx, decl)
                else:
                    simulated_by_output[name] = extract_cell(trial_ctx, decl)
            except Exception as exc:
                logger.exception("Output %r extraction failed", name)
                raise RuntimeError(
                    f"Output {name!r} extraction failed: {type(exc).__name__}: {exc}"
                ) from exc

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
