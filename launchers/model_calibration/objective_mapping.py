"""Objective-function mapping diagnostics for model-calibration runs.

This module is intentionally launcher-local: it only consumes calibration
iteration artifacts and the model-calibration evaluator. It does not introduce
new dependencies in the HydroModPy calibration core.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from launchers.model_calibration.config import ModelCalibrationConfig
from launchers.model_calibration.runtime import (
    ModelCalibrationObjectiveEvaluator,
    PreparedCalibrationSession,
)
from launchers.model_calibration._utils import jsonable as _jsonable


@dataclass(frozen=True, slots=True)
class ObjectiveMappingPoint:
    """One evaluated simulation used to map the objective function."""

    iteration_id: str
    params_vector: tuple[float, ...]
    params_named: dict[str, float]
    objective_total: float | None
    block_costs: dict[str, float] = field(default_factory=dict)
    status: str = "unknown"
    failure_reason: str | None = None

    @property
    def finite_objective(self) -> bool:
        """Return True when the point has a finite objective value."""
        return (
            self.objective_total is not None
            and math.isfinite(float(self.objective_total))
        )


def resolve_objective_mapping_axes(
    *,
    cfg: ModelCalibrationConfig,
) -> tuple[str, str]:
    """Resolve the two mapped parameters."""
    configured_axes = cfg.model_calibration.objective_mapping.axes
    if configured_axes is not None:
        unknown = [
            name for name in configured_axes if name not in cfg.parameter_names
        ]
        if unknown:
            raise ValueError(
                "objective_mapping.axes references unknown parameters: "
                f"{unknown}"
            )
        return configured_axes

    parameter_names = cfg.parameter_names
    if len(parameter_names) < 2:
        raise ValueError("objective mapping requires at least two parameters")
    return parameter_names[:2]


def _objective_from_payload(payload: dict[str, Any]) -> float | None:
    """Return the objective value stored in one history payload."""
    value = payload.get("objective_total")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_objective_mapping_points(history_path: Path) -> list[ObjectiveMappingPoint]:
    """Load evaluated objective points from the calibration JSONL history."""
    if not history_path.is_file():
        return []
    points: list[ObjectiveMappingPoint] = []
    for raw_line in history_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        params_named = {
            str(name): float(value)
            for name, value in dict(payload.get("params_named", {})).items()
        }
        params_vector = tuple(
            float(value) for value in payload.get("params_vector", ())
        )
        points.append(
            ObjectiveMappingPoint(
                iteration_id=str(payload.get("iteration_id", "")),
                params_vector=params_vector,
                params_named=params_named,
                objective_total=_objective_from_payload(payload),
                block_costs={
                    str(name): float(value)
                    for name, value in dict(payload.get("block_costs", {})).items()
                },
                status=str(payload.get("status", "unknown")),
                failure_reason=payload.get("failure_reason"),
            )
        )
    return points


def _best_params(
    *,
    cfg: ModelCalibrationConfig,
    result: Any,
) -> dict[str, float]:
    """Return the best parameter mapping from a calibration result."""
    params = getattr(result, "params_best", None)
    if params is not None:
        return {str(name): float(value) for name, value in dict(params).items()}
    vector = tuple(float(value) for value in np.asarray(result.x_best).ravel())
    return {
        str(name): float(value)
        for name, value in zip(cfg.parameter_names, vector, strict=True)
    }


def _finite_xy_costs(
    *,
    points: list[ObjectiveMappingPoint],
    axes: tuple[str, str],
) -> tuple[np.ndarray, np.ndarray]:
    """Return finite `(xy, cost)` arrays for interpolation."""
    xy_values: list[tuple[float, float]] = []
    costs: list[float] = []
    for point in points:
        if not point.finite_objective:
            continue
        if axes[0] not in point.params_named or axes[1] not in point.params_named:
            continue
        xy_values.append(
            (
                float(point.params_named[axes[0]]),
                float(point.params_named[axes[1]]),
            )
        )
        costs.append(float(point.objective_total))
    if not xy_values:
        return np.empty((0, 2), dtype=float), np.empty((0,), dtype=float)
    return np.asarray(xy_values, dtype=float), np.asarray(costs, dtype=float)


def _finite_xy_block_costs(
    *,
    points: list[ObjectiveMappingPoint],
    axes: tuple[str, str],
    block_name: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Return finite `(xy, block_cost)` arrays for one objective block."""
    xy_values: list[tuple[float, float]] = []
    costs: list[float] = []
    for point in points:
        if axes[0] not in point.params_named or axes[1] not in point.params_named:
            continue
        if block_name not in point.block_costs:
            continue
        block_cost = float(point.block_costs[block_name])
        if not math.isfinite(block_cost):
            continue
        xy_values.append(
            (
                float(point.params_named[axes[0]]),
                float(point.params_named[axes[1]]),
            )
        )
        costs.append(block_cost)
    if not xy_values:
        return np.empty((0, 2), dtype=float), np.empty((0,), dtype=float)
    return np.asarray(xy_values, dtype=float), np.asarray(costs, dtype=float)


def _axis_bounds(
    *,
    cfg: ModelCalibrationConfig,
    axes: tuple[str, str],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return configured bounds for the two mapped axes."""
    return (
        tuple(float(value) for value in cfg.bounds[axes[0]]),
        tuple(float(value) for value in cfg.bounds[axes[1]]),
    )


def _latin_hypercube_2d(
    *,
    rng: np.random.Generator,
    n_points: int,
    bounds_x: tuple[float, float],
    bounds_y: tuple[float, float],
) -> np.ndarray:
    """Generate one deterministic 2D Latin-hypercube sample."""
    if n_points <= 0:
        return np.empty((0, 2), dtype=float)
    base = (np.arange(n_points, dtype=float) + rng.random(n_points)) / n_points
    xs = base.copy()
    ys = base.copy()
    rng.shuffle(xs)
    rng.shuffle(ys)
    return np.column_stack(
        [
            bounds_x[0] + xs * (bounds_x[1] - bounds_x[0]),
            bounds_y[0] + ys * (bounds_y[1] - bounds_y[0]),
        ]
    )


def _adaptive_scores(
    *,
    pool_xy: np.ndarray,
    existing_xy: np.ndarray,
    existing_costs: np.ndarray,
) -> np.ndarray:
    """Score candidate points by local objective variation and sparse coverage."""
    if pool_xy.size == 0:
        return np.empty((0,), dtype=float)
    if existing_xy.shape[0] == 0:
        return np.ones(pool_xy.shape[0], dtype=float)

    scale = np.ptp(existing_xy, axis=0)
    scale = np.where(scale > 0.0, scale, 1.0)
    normalized_existing = existing_xy / scale
    normalized_pool = pool_xy / scale
    distances = np.linalg.norm(
        normalized_pool[:, None, :] - normalized_existing[None, :, :],
        axis=2,
    )
    nearest_distance = np.min(distances, axis=1)

    if existing_costs.size < 2:
        local_variation = np.zeros(pool_xy.shape[0], dtype=float)
    else:
        k = min(4, existing_costs.size)
        nearest_indices = np.argpartition(distances, kth=k - 1, axis=1)[:, :k]
        local_variation = np.asarray(
            [
                float(np.nanstd(existing_costs[row_indices]))
                for row_indices in nearest_indices
            ],
            dtype=float,
        )

    distance_scale = np.nanmax(nearest_distance)
    variation_scale = np.nanmax(local_variation)
    distance_score = (
        nearest_distance / distance_scale
        if distance_scale > 0.0
        else nearest_distance
    )
    variation_score = (
        local_variation / variation_scale
        if variation_scale > 0.0
        else local_variation
    )
    return variation_score + 0.25 * distance_score


def propose_additional_objective_mapping_params(
    *,
    cfg: ModelCalibrationConfig,
    points: list[ObjectiveMappingPoint],
    result: Any,
) -> list[dict[str, float]]:
    """Propose additional simulations on a slice through the best parameters."""
    mapping_cfg = cfg.model_calibration.objective_mapping
    n_runs = int(mapping_cfg.additional_runs)
    if n_runs <= 0:
        return []

    axes = resolve_objective_mapping_axes(cfg=cfg)
    best = _best_params(cfg=cfg, result=result)
    bounds_x, bounds_y = _axis_bounds(cfg=cfg, axes=axes)
    rng = np.random.default_rng(int(mapping_cfg.random_seed))
    pool_size = max(int(mapping_cfg.candidate_pool_size), n_runs)
    pool_xy = _latin_hypercube_2d(
        rng=rng,
        n_points=pool_size,
        bounds_x=bounds_x,
        bounds_y=bounds_y,
    )

    if mapping_cfg.sampling == "latin_hypercube":
        selected_xy = pool_xy[:n_runs]
    else:
        existing_xy, existing_costs = _finite_xy_costs(points=points, axes=axes)
        selected_rows: list[int] = []
        current_xy = existing_xy.copy()
        current_costs = existing_costs.copy()
        available = np.ones(pool_xy.shape[0], dtype=bool)
        for _ in range(n_runs):
            candidate_xy = pool_xy[available]
            scores = _adaptive_scores(
                pool_xy=candidate_xy,
                existing_xy=current_xy,
                existing_costs=current_costs,
            )
            local_index = int(np.nanargmax(scores))
            absolute_indices = np.flatnonzero(available)
            selected_index = int(absolute_indices[local_index])
            selected_rows.append(selected_index)
            available[selected_index] = False
            current_xy = np.vstack([current_xy, pool_xy[selected_index]])
            current_costs = np.append(
                current_costs,
                np.nanmean(current_costs) if current_costs.size else 0.0,
            )
        selected_xy = pool_xy[selected_rows]

    proposals: list[dict[str, float]] = []
    for xy in selected_xy:
        params = dict(best)
        params[axes[0]] = float(xy[0])
        params[axes[1]] = float(xy[1])
        proposals.append(params)
    return proposals


def _idw_grid(
    *,
    xy: np.ndarray,
    values: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    power: float,
) -> np.ndarray:
    """Interpolate values on a grid using inverse-distance weights."""
    if xy.shape[0] == 0:
        return np.full_like(grid_x, np.nan, dtype=float)
    grid_points = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    distances = np.linalg.norm(grid_points[:, None, :] - xy[None, :, :], axis=2)
    exact = distances == 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        weights = 1.0 / np.power(distances, float(power))
    weights[~np.isfinite(weights)] = 0.0
    weighted_sum = weights @ values
    weight_total = np.sum(weights, axis=1)
    interpolated = np.divide(
        weighted_sum,
        weight_total,
        out=np.full(grid_points.shape[0], np.nan, dtype=float),
        where=weight_total > 0.0,
    )
    if np.any(exact):
        exact_rows = np.any(exact, axis=1)
        exact_indices = np.argmax(exact[exact_rows], axis=1)
        interpolated[exact_rows] = values[exact_indices]
    return interpolated.reshape(grid_x.shape)


def _nearest_grid(
    *,
    xy: np.ndarray,
    values: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
) -> np.ndarray:
    """Interpolate values on a grid with nearest-neighbor assignment."""
    if xy.shape[0] == 0:
        return np.full_like(grid_x, np.nan, dtype=float)
    grid_points = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    distances = np.linalg.norm(grid_points[:, None, :] - xy[None, :, :], axis=2)
    nearest = np.argmin(distances, axis=1)
    return values[nearest].reshape(grid_x.shape)


def interpolate_objective_grid(
    *,
    cfg: ModelCalibrationConfig,
    points: list[ObjectiveMappingPoint],
    axes: tuple[str, str],
) -> dict[str, Any]:
    """Build one interpolated objective grid from evaluated points."""
    mapping_cfg = cfg.model_calibration.objective_mapping
    bounds_x, bounds_y = _axis_bounds(cfg=cfg, axes=axes)
    x_values = np.linspace(bounds_x[0], bounds_x[1], int(mapping_cfg.grid_size))
    y_values = np.linspace(bounds_y[0], bounds_y[1], int(mapping_cfg.grid_size))
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    xy, costs = _finite_xy_costs(points=points, axes=axes)

    interpolator = mapping_cfg.interpolation
    interpolation_used = interpolator
    if xy.shape[0] == 0:
        objective_grid = np.full_like(grid_x, np.nan, dtype=float)
    elif interpolator == "nearest":
        objective_grid = _nearest_grid(
            xy=xy,
            values=costs,
            grid_x=grid_x,
            grid_y=grid_y,
        )
    elif interpolator == "linear":
        try:
            from scipy.interpolate import griddata

            objective_grid = griddata(
                xy,
                costs,
                (grid_x, grid_y),
                method="linear",
            )
            missing = ~np.isfinite(objective_grid)
            if np.any(missing):
                objective_grid[missing] = _idw_grid(
                    xy=xy,
                    values=costs,
                    grid_x=grid_x,
                    grid_y=grid_y,
                    power=mapping_cfg.idw_power,
                )[missing]
        except Exception:
            interpolation_used = "idw_fallback"
            objective_grid = _idw_grid(
                xy=xy,
                values=costs,
                grid_x=grid_x,
                grid_y=grid_y,
                power=mapping_cfg.idw_power,
            )
    else:
        objective_grid = _idw_grid(
            xy=xy,
            values=costs,
            grid_x=grid_x,
            grid_y=grid_y,
            power=mapping_cfg.idw_power,
        )

    block_grids: dict[str, Any] = {}
    if mapping_cfg.include_block_contributions:
        block_names = sorted(
            {
                block_name
                for point in points
                for block_name in point.block_costs.keys()
            }
        )
        for block_name in block_names:
            block_xy, block_costs = _finite_xy_block_costs(
                points=points,
                axes=axes,
                block_name=block_name,
            )
            block_grids[block_name] = _jsonable(
                _idw_grid(
                    xy=block_xy,
                    values=block_costs,
                    grid_x=grid_x,
                    grid_y=grid_y,
                    power=mapping_cfg.idw_power,
                )
            )

    return {
        "axes": list(axes),
        "x": x_values.tolist(),
        "y": y_values.tolist(),
        "objective_total": _jsonable(objective_grid),
        "block_costs": block_grids,
        "interpolation_requested": interpolator,
        "interpolation_used": interpolation_used,
        "finite_point_count": int(xy.shape[0]),
    }


def write_objective_mapping_points_csv(
    *,
    path: Path,
    cfg: ModelCalibrationConfig,
    points: list[ObjectiveMappingPoint],
) -> None:
    """Write evaluated objective points as a flat CSV table."""
    block_names = sorted(
        {
            block_name
            for point in points
            for block_name in point.block_costs.keys()
        }
    )
    fieldnames = [
        "iteration_id",
        "status",
        "objective_total",
        *cfg.parameter_names,
        *[f"block_{name}" for name in block_names],
        "failure_reason",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for point in points:
            row: dict[str, Any] = {
                "iteration_id": point.iteration_id,
                "status": point.status,
                "objective_total": point.objective_total,
                "failure_reason": point.failure_reason,
            }
            for name in cfg.parameter_names:
                row[name] = point.params_named.get(name)
            for block_name in block_names:
                row[f"block_{block_name}"] = point.block_costs.get(block_name)
            writer.writerow(row)


def write_objective_mapping_grid_json(
    *,
    path: Path,
    grid_payload: dict[str, Any],
    cfg: ModelCalibrationConfig,
    points: list[ObjectiveMappingPoint],
    additional_runs_executed: int,
) -> None:
    """Write one objective mapping grid JSON artifact."""
    payload = {
        "role": "objective_function_mapping",
        "parameter_names": list(cfg.parameter_names),
        "point_count": len(points),
        "finite_point_count": sum(point.finite_objective for point in points),
        "additional_runs_executed": int(additional_runs_executed),
        "grid": grid_payload,
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def write_objective_mapping_figure(
    *,
    path: Path,
    cfg: ModelCalibrationConfig,
    points: list[ObjectiveMappingPoint],
    axes: tuple[str, str],
    grid_payload: dict[str, Any],
    result: Any,
) -> bool:
    """Write a simple 2D objective-map figure when matplotlib is available."""
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception:
        return False

    grid = np.asarray(grid_payload["objective_total"], dtype=float)
    x_values = np.asarray(grid_payload["x"], dtype=float)
    y_values = np.asarray(grid_payload["y"], dtype=float)
    finite_points = [point for point in points if point.finite_objective]
    failed_points = [point for point in points if not point.finite_objective]

    figure, axis = plt.subplots(figsize=(8.0, 6.0))
    if np.any(np.isfinite(grid)):
        contour = axis.contourf(
            x_values,
            y_values,
            grid,
            levels=20,
            cmap="viridis",
        )
        figure.colorbar(contour, ax=axis, label="Objective total")

    if finite_points:
        axis.scatter(
            [point.params_named[axes[0]] for point in finite_points],
            [point.params_named[axes[1]] for point in finite_points],
            c=[float(point.objective_total) for point in finite_points],
            cmap="viridis",
            edgecolors="black",
            linewidths=0.5,
            s=35,
            label="Evaluated finite",
        )
    if failed_points:
        axis.scatter(
            [
                point.params_named[axes[0]]
                for point in failed_points
                if axes[0] in point.params_named and axes[1] in point.params_named
            ],
            [
                point.params_named[axes[1]]
                for point in failed_points
                if axes[0] in point.params_named and axes[1] in point.params_named
            ],
            marker="x",
            c="red",
            s=45,
            label="Failed / infinite",
        )

    best = _best_params(cfg=cfg, result=result)
    axis.scatter(
        [best[axes[0]]],
        [best[axes[1]]],
        marker="*",
        c="white",
        edgecolors="black",
        s=180,
        label="Best",
        zorder=5,
    )
    axis.set_xlabel(axes[0])
    axis.set_ylabel(axes[1])
    axis.set_title("Calibration objective mapping")
    axis.legend(loc="best")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return True


def execute_objective_mapping_additional_runs(
    *,
    cfg: ModelCalibrationConfig,
    session: PreparedCalibrationSession,
    evaluator: ModelCalibrationObjectiveEvaluator,
    result: Any,
) -> int:
    """Evaluate additional points requested for objective mapping diagnostics."""
    initial_points = load_objective_mapping_points(session.iteration_history_path)
    proposals = propose_additional_objective_mapping_params(
        cfg=cfg,
        points=initial_points,
        result=result,
    )
    executed = 0
    for params in proposals:
        _ = evaluator.evaluate(params)
        executed += 1
    return executed


def build_objective_mapping_artifacts(
    *,
    cfg: ModelCalibrationConfig,
    session: PreparedCalibrationSession,
    result: Any,
    additional_runs_executed: int,
) -> dict[str, Any]:
    """Build objective-mapping CSV/JSON/figure artifacts from iteration history."""
    mapping_cfg = cfg.model_calibration.objective_mapping
    axes = resolve_objective_mapping_axes(cfg=cfg)
    points = load_objective_mapping_points(session.iteration_history_path)
    points_path = session.calibration_root / mapping_cfg.output_points_csv
    grid_path = session.calibration_root / mapping_cfg.output_grid_json
    figure_path = (
        None
        if mapping_cfg.output_figure is None
        else session.calibration_root / mapping_cfg.output_figure
    )

    write_objective_mapping_points_csv(
        path=points_path,
        cfg=cfg,
        points=points,
    )
    grid_payload = interpolate_objective_grid(
        cfg=cfg,
        points=points,
        axes=axes,
    )
    write_objective_mapping_grid_json(
        path=grid_path,
        grid_payload=grid_payload,
        cfg=cfg,
        points=points,
        additional_runs_executed=additional_runs_executed,
    )
    figure_written = False
    if figure_path is not None:
        figure_written = write_objective_mapping_figure(
            path=figure_path,
            cfg=cfg,
            points=points,
            axes=axes,
            grid_payload=grid_payload,
            result=result,
        )

    return {
        "enabled": True,
        "status": "completed",
        "axes": list(axes),
        "interpolation_requested": mapping_cfg.interpolation,
        "interpolation_used": grid_payload["interpolation_used"],
        "sampling": mapping_cfg.sampling,
        "additional_runs_requested": int(mapping_cfg.additional_runs),
        "additional_runs_executed": int(additional_runs_executed),
        "point_count": len(points),
        "finite_point_count": sum(point.finite_objective for point in points),
        "points_csv": str(points_path),
        "grid_json": str(grid_path),
        "figure": None if figure_path is None else str(figure_path),
        "figure_written": figure_written,
    }


def run_objective_mapping(
    *,
    cfg: ModelCalibrationConfig,
    session: PreparedCalibrationSession,
    evaluator: ModelCalibrationObjectiveEvaluator,
    result: Any,
) -> dict[str, Any] | None:
    """Run optional objective-function mapping diagnostics."""
    mapping_cfg = cfg.model_calibration.objective_mapping
    if not mapping_cfg.enabled:
        return None

    if not cfg.model_calibration.persist_iteration_history:
        return {
            "enabled": True,
            "status": "skipped",
            "reason": "persist_iteration_history_is_disabled",
        }

    additional_runs_executed = execute_objective_mapping_additional_runs(
        cfg=cfg,
        session=session,
        evaluator=evaluator,
        result=result,
    )
    return build_objective_mapping_artifacts(
        cfg=cfg,
        session=session,
        result=result,
        additional_runs_executed=additional_runs_executed,
    )


__all__ = (
    "ObjectiveMappingPoint",
    "build_objective_mapping_artifacts",
    "execute_objective_mapping_additional_runs",
    "interpolate_objective_grid",
    "load_objective_mapping_points",
    "propose_additional_objective_mapping_params",
    "resolve_objective_mapping_axes",
    "run_objective_mapping",
)
