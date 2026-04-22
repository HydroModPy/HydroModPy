"""Plotting helpers for calibration twin benchmarks.

This module has two responsibilities:

- suite-level benchmark summary figures;
- per-case objective figures derived from persisted calibration histories.
"""

from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path

import numpy as np

from hydromodpy.analysis.calibration.engine.objective_mapping import (
    ObjectiveMappingPoint,
    load_objective_mapping_points,
)
from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    TwinCalibrationCaseDefinition,
    TwinMethodBenchmarkResult,
)


SUITE_TITLE_FONTSIZE = 10.0
CASE_TITLE_FONTSIZE = 9.4
CASE_SUPTITLE_FONTSIZE = 11.8
SECTION_TITLE_FONTSIZE = 9.2
AXIS_LABEL_FONTSIZE = 8.4
TICK_LABEL_FONTSIZE = 7.4
LEGEND_FONTSIZE = 6.8
LEGEND_TITLE_FONTSIZE = 6.9
ANNOTATION_FONTSIZE = 6.4
CONFIG_TEXT_FONTSIZE = 7.9
CONFIG_SMALL_TEXT_FONTSIZE = 7.6


def _compact_case_title(
    case_id: str,
    detail: str,
) -> str:
    """Return one compact two-line title for case-level figures."""
    return f"{case_id}\n{detail}"


def _apply_tick_style(axis) -> None:
    """Apply one compact tick-label style."""
    axis.tick_params(labelsize=TICK_LABEL_FONTSIZE)


def _apply_compact_legend(axis, **kwargs):
    """Render one compact legend suited to dense calibration figures."""
    return axis.legend(
        fontsize=LEGEND_FONTSIZE,
        title_fontsize=LEGEND_TITLE_FONTSIZE,
        framealpha=0.94,
        borderpad=0.35,
        labelspacing=0.3,
        handlelength=1.35,
        handletextpad=0.45,
        borderaxespad=0.35,
        **kwargs,
    )


def _try_import_matplotlib():
    """Import matplotlib lazily and return pyplot, or None when unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    return plt


def _sanitize_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Drop rows lacking the minimal metrics used by suite figures."""
    return [
        row for row in rows if row.get("case_id") is not None and row.get("method_name") is not None
    ]


def write_suite_figures(
    method_rows: list[dict[str, object]],
    *,
    output_root: Path | None,
    figure_format: str = "png",
) -> tuple[Path, ...]:
    """Write suite-level figures and return the generated paths."""
    if output_root is None:
        return ()
    rows = _sanitize_rows(method_rows)
    if not rows:
        return ()
    plt = _try_import_matplotlib()
    if plt is None:
        return ()
    output_root.mkdir(parents=True, exist_ok=True)
    extension = str(figure_format).strip().lower() or "png"
    figure_paths = []

    row_labels = [f"{row['case_id']} | {row['method_name']}" for row in rows]
    target_success = [float(row.get("target_success_rate") or 0.0) for row in rows]
    best_fit = [float(row.get("best_fit_rate") or 0.0) for row in rows]
    mean_cost = [row.get("mean_cost_best") for row in rows]
    mean_eval = [row.get("mean_n_evaluations") for row in rows]
    mean_time_per_eval = [row.get("mean_time_per_evaluation_seconds") for row in rows]
    mean_calibration_time = [
        row.get("mean_calibration_time_seconds", row.get("calibration_time_seconds"))
        for row in rows
    ]
    mean_session_prepare = [
        row.get("mean_session_prepare_time_seconds", row.get("session_prepare_time_seconds"))
        for row in rows
    ]
    mean_estimated_candidate_runtime = [
        row.get(
            "mean_estimated_candidate_runtime_seconds",
            row.get("estimated_candidate_runtime_seconds"),
        )
        for row in rows
    ]
    mean_algorithm_overhead = [
        row.get(
            "mean_algorithm_overhead_time_seconds",
            row.get("algorithm_overhead_time_seconds"),
        )
        for row in rows
    ]
    mean_candidate_prepare = [row.get("mean_candidate_preparation_time_seconds") for row in rows]
    mean_candidate_actualize = [row.get("mean_candidate_actualize_time_seconds") for row in rows]
    mean_candidate_launcher_prepare = [
        row.get("mean_candidate_launcher_prepare_time_seconds") for row in rows
    ]
    mean_candidate_runtime_patch = [
        row.get("mean_candidate_runtime_patch_time_seconds") for row in rows
    ]
    mean_candidate_simulation = [row.get("mean_candidate_simulation_time_seconds") for row in rows]
    mean_candidate_output_selection = [
        row.get("mean_candidate_output_selection_time_seconds") for row in rows
    ]
    mean_candidate_objective_build = [
        row.get("mean_candidate_objective_build_time_seconds") for row in rows
    ]
    mean_candidate_objective_compute = [
        row.get("mean_candidate_objective_compute_time_seconds") for row in rows
    ]
    mean_candidate_objective = [row.get("mean_candidate_objective_time_seconds") for row in rows]

    fig, ax = plt.subplots(figsize=(12, max(4, 0.45 * len(rows) + 1)))
    y_positions = list(range(len(rows)))
    ax.barh(y_positions, best_fit, color="#9db5c9", label="best_fit_rate")
    ax.barh(y_positions, target_success, color="#284b63", alpha=0.85, label="target_success_rate")
    ax.set_yticks(y_positions)
    ax.set_yticklabels(row_labels)
    ax.set_xlim(0.0, 1.0)
    ax.set_xlabel("Success Rate", fontsize=AXIS_LABEL_FONTSIZE)
    ax.set_title("Calibration Benchmark Success Rates", fontsize=SUITE_TITLE_FONTSIZE)
    _apply_tick_style(ax)
    _apply_compact_legend(ax)
    fig.tight_layout()
    path = output_root / f"benchmark_target_success_rates.{extension}"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    figure_paths.append(path)

    scatter_points = [
        (
            float(eval_count),
            float(cost),
            f"{row['case_id']} | {row['method_name']}",
        )
        for row, eval_count, cost in zip(rows, mean_eval, mean_cost, strict=False)
        if eval_count is not None and cost is not None and float(cost) > 0.0
    ]
    if scatter_points:
        fig, ax = plt.subplots(figsize=(8, 6))
        xs = [item[0] for item in scatter_points]
        ys = [item[1] for item in scatter_points]
        ax.scatter(xs, ys, color="#284b63")
        for x_value, y_value, label in scatter_points:
            ax.annotate(label, (x_value, y_value), fontsize=ANNOTATION_FONTSIZE)
        ax.set_xlabel("Mean Evaluations", fontsize=AXIS_LABEL_FONTSIZE)
        ax.set_ylabel("Mean Best Cost", fontsize=AXIS_LABEL_FONTSIZE)
        ax.set_yscale("log")
        ax.set_title("Cost vs Evaluation Budget", fontsize=SUITE_TITLE_FONTSIZE)
        _apply_tick_style(ax)
        fig.tight_layout()
        path = output_root / f"benchmark_cost_vs_budget.{extension}"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figure_paths.append(path)

    time_points = [
        (
            float(time_value),
            float(cost),
            f"{row['case_id']} | {row['method_name']}",
        )
        for row, time_value, cost in zip(rows, mean_time_per_eval, mean_cost, strict=False)
        if time_value is not None
        and cost is not None
        and float(cost) > 0.0
        and float(time_value) > 0.0
    ]
    if time_points:
        fig, ax = plt.subplots(figsize=(8, 6))
        xs = [item[0] for item in time_points]
        ys = [item[1] for item in time_points]
        ax.scatter(xs, ys, color="#3c6e71")
        for x_value, y_value, label in time_points:
            ax.annotate(label, (x_value, y_value), fontsize=ANNOTATION_FONTSIZE)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Mean Time per Evaluation (s)", fontsize=AXIS_LABEL_FONTSIZE)
        ax.set_ylabel("Mean Best Cost", fontsize=AXIS_LABEL_FONTSIZE)
        ax.set_title("Cost vs Time per Evaluation", fontsize=SUITE_TITLE_FONTSIZE)
        _apply_tick_style(ax)
        fig.tight_layout()
        path = output_root / f"benchmark_time_vs_cost.{extension}"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figure_paths.append(path)

    normalized_error_points = []
    for row in rows:
        ratio_values = [
            float(value)
            for key, value in row.items()
            if str(key).startswith("mean_param_abs_error_over_tol__") and value is not None
        ]
        if ratio_values:
            normalized_error_points.append(
                (
                    float(sum(ratio_values) / len(ratio_values)),
                    f"{row['case_id']} | {row['method_name']}",
                )
            )
    if normalized_error_points:
        fig, ax = plt.subplots(figsize=(12, max(4, 0.4 * len(normalized_error_points) + 1)))
        y_positions = list(range(len(normalized_error_points)))
        values = [item[0] for item in normalized_error_points]
        labels = [item[1] for item in normalized_error_points]
        ax.barh(y_positions, values, color="#d9bf77")
        ax.axvline(1.0, color="#7a5c00", linestyle="--", linewidth=1.2)
        ax.set_yticks(y_positions)
        ax.set_yticklabels(labels)
        ax.set_xlabel("Mean Parameter Absolute Error / Tolerance", fontsize=AXIS_LABEL_FONTSIZE)
        ax.set_title("Normalized Parameter Error", fontsize=SUITE_TITLE_FONTSIZE)
        _apply_tick_style(ax)
        fig.tight_layout()
        path = output_root / f"benchmark_parameter_error_ratio.{extension}"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figure_paths.append(path)

    calibration_time_rows = [
        {
            "label": label,
            "session_prepare": float(session_prepare_value or 0.0),
            "candidate_runtime": float(candidate_runtime_value or 0.0),
            "algorithm_overhead": float(overhead_value or 0.0),
            "calibration_total": float(calibration_value or 0.0),
        }
        for (
            label,
            session_prepare_value,
            candidate_runtime_value,
            overhead_value,
            calibration_value,
        ) in zip(
            row_labels,
            mean_session_prepare,
            mean_estimated_candidate_runtime,
            mean_algorithm_overhead,
            mean_calibration_time,
            strict=False,
        )
        if any(
            value is not None and float(value) > 0.0
            for value in (
                session_prepare_value,
                candidate_runtime_value,
                overhead_value,
                calibration_value,
            )
        )
    ]
    if calibration_time_rows:
        fig, ax = plt.subplots(figsize=(12, max(4, 0.45 * len(calibration_time_rows) + 1)))
        y_positions = list(range(len(calibration_time_rows)))
        timing_labels = [item["label"] for item in calibration_time_rows]
        segment_specs = (
            ("session_prepare", "#d9bf77"),
            ("candidate_runtime", "#3c6e71"),
            ("algorithm_overhead", "#7a5c61"),
        )
        cumulative = [0.0 for _ in calibration_time_rows]
        for key, color in segment_specs:
            values = [item[key] for item in calibration_time_rows]
            ax.barh(
                y_positions,
                values,
                left=list(cumulative),
                color=color,
                label=key,
            )
            cumulative = [
                float(left + value) for left, value in zip(cumulative, values, strict=False)
            ]
        calibration_totals = [
            item["session_prepare"] + item["calibration_total"] for item in calibration_time_rows
        ]
        ax.scatter(
            calibration_totals,
            y_positions,
            marker="|",
            s=220,
            c="black",
            linewidths=1.2,
            label="end_to_end_total",
            zorder=5,
        )
        ax.set_yticks(y_positions)
        ax.set_yticklabels(timing_labels)
        ax.set_xlabel("Calibration Time (s)", fontsize=AXIS_LABEL_FONTSIZE)
        ax.set_title("Calibration Time Closure", fontsize=SUITE_TITLE_FONTSIZE)
        _apply_tick_style(ax)
        _apply_compact_legend(ax)
        fig.tight_layout()
        path = output_root / f"benchmark_calibration_time_closure.{extension}"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figure_paths.append(path)

    detailed_timing_breakdown_rows = [
        {
            "label": label,
            "actualize": float(actualize_value or 0.0),
            "launcher_prepare": float(launcher_prepare_value or 0.0),
            "runtime_patch": float(runtime_patch_value or 0.0),
            "simulate": float(simulation_value or 0.0),
            "output_select": float(output_select_value or 0.0),
            "objective_build": float(objective_build_value or 0.0),
            "objective_score": float(objective_compute_value or 0.0),
        }
        for (
            label,
            actualize_value,
            launcher_prepare_value,
            runtime_patch_value,
            simulation_value,
            output_select_value,
            objective_build_value,
            objective_compute_value,
        ) in zip(
            row_labels,
            mean_candidate_actualize,
            mean_candidate_launcher_prepare,
            mean_candidate_runtime_patch,
            mean_candidate_simulation,
            mean_candidate_output_selection,
            mean_candidate_objective_build,
            mean_candidate_objective_compute,
            strict=False,
        )
        if any(
            value is not None and float(value) > 0.0
            for value in (
                actualize_value,
                launcher_prepare_value,
                runtime_patch_value,
                simulation_value,
                output_select_value,
                objective_build_value,
                objective_compute_value,
            )
        )
    ]
    timing_breakdown_rows = [
        (
            label,
            float(prepare_value or 0.0),
            float(simulation_value or 0.0),
            float(objective_value or 0.0),
        )
        for label, prepare_value, simulation_value, objective_value in zip(
            row_labels,
            mean_candidate_prepare,
            mean_candidate_simulation,
            mean_candidate_objective,
            strict=False,
        )
        if any(
            value is not None and float(value) > 0.0
            for value in (prepare_value, simulation_value, objective_value)
        )
    ]
    if detailed_timing_breakdown_rows:
        fig, ax = plt.subplots(figsize=(12, max(4, 0.45 * len(detailed_timing_breakdown_rows) + 1)))
        y_positions = list(range(len(detailed_timing_breakdown_rows)))
        timing_labels = [item["label"] for item in detailed_timing_breakdown_rows]
        segment_specs = (
            ("actualize", "#d9bf77"),
            ("launcher_prepare", "#c17c74"),
            ("runtime_patch", "#9d4edd"),
            ("simulate", "#3c6e71"),
            ("output_select", "#2a9d8f"),
            ("objective_build", "#6d597a"),
            ("objective_score", "#284b63"),
        )
        cumulative = [0.0 for _ in detailed_timing_breakdown_rows]
        for key, color in segment_specs:
            values = [item[key] for item in detailed_timing_breakdown_rows]
            ax.barh(
                y_positions,
                values,
                left=list(cumulative),
                color=color,
                label=key,
            )
            cumulative = [
                float(left + value) for left, value in zip(cumulative, values, strict=False)
            ]
        ax.set_yticks(y_positions)
        ax.set_yticklabels(timing_labels)
        ax.set_xlabel("Mean Candidate Time (s)", fontsize=AXIS_LABEL_FONTSIZE)
        ax.set_title("Candidate Timing Breakdown", fontsize=SUITE_TITLE_FONTSIZE)
        _apply_tick_style(ax)
        _apply_compact_legend(ax)
        fig.tight_layout()
        path = output_root / f"benchmark_candidate_timing_breakdown.{extension}"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figure_paths.append(path)
    elif timing_breakdown_rows:
        fig, ax = plt.subplots(figsize=(12, max(4, 0.45 * len(timing_breakdown_rows) + 1)))
        y_positions = list(range(len(timing_breakdown_rows)))
        prep = [item[1] for item in timing_breakdown_rows]
        sim = [item[2] for item in timing_breakdown_rows]
        obj = [item[3] for item in timing_breakdown_rows]
        timing_labels = [item[0] for item in timing_breakdown_rows]
        ax.barh(y_positions, prep, color="#d9bf77", label="prepare")
        ax.barh(y_positions, sim, left=prep, color="#3c6e71", label="simulate")
        ax.barh(
            y_positions,
            obj,
            left=[p + s for p, s in zip(prep, sim, strict=False)],
            color="#284b63",
            label="objective",
        )
        ax.set_yticks(y_positions)
        ax.set_yticklabels(timing_labels)
        ax.set_xlabel("Mean Candidate Time (s)", fontsize=AXIS_LABEL_FONTSIZE)
        ax.set_title("Candidate Timing Breakdown", fontsize=SUITE_TITLE_FONTSIZE)
        _apply_tick_style(ax)
        _apply_compact_legend(ax)
        fig.tight_layout()
        path = output_root / f"benchmark_candidate_timing_breakdown.{extension}"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figure_paths.append(path)

    return tuple(figure_paths)


def _sanitize_method_slug(text: str) -> str:
    """Return one filesystem-safe method token."""
    token = "".join(
        char if char.isalnum() or char in {"_", "-"} else "_" for char in str(text).strip().lower()
    )
    return token or "method"


def _load_reference_objective_payload(
    *,
    benchmark_root: Path,
    definition: TwinCalibrationCaseDefinition,
) -> dict[str, object] | None:
    """Load one shared reference-objective payload when available."""
    parameter_names = tuple(str(name) for name in definition.truth_params.keys())
    candidate_paths = (
        benchmark_root / "objective_reference_samples.json",
        benchmark_root / "objective_regular_grid.json",
    )
    for path in candidate_paths:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if tuple(payload.get("parameter_names", ())) != parameter_names:
            continue
        return payload
    return None


def _reference_objective_points(
    payload: dict[str, object] | None,
) -> list[ObjectiveMappingPoint]:
    """Convert one persisted reference-objective payload to point objects."""
    if not isinstance(payload, dict):
        return []
    raw_points = payload.get("points")
    if isinstance(raw_points, list):
        points: list[ObjectiveMappingPoint] = []
        for index, raw_point in enumerate(raw_points, start=1):
            if not isinstance(raw_point, dict):
                continue
            params_named = raw_point.get("params_named", {})
            if not isinstance(params_named, dict):
                continue
            try:
                normalized_named = {str(name): float(value) for name, value in params_named.items()}
            except (TypeError, ValueError):
                continue
            objective_total = raw_point.get("objective_total")
            try:
                objective_total_value = None if objective_total is None else float(objective_total)
            except (TypeError, ValueError):
                objective_total_value = None
            block_costs_raw = raw_point.get("block_costs", {})
            if not isinstance(block_costs_raw, dict):
                block_costs_raw = {}
            points.append(
                ObjectiveMappingPoint(
                    iteration_id=str(raw_point.get("point_id", f"reference_{index:04d}")),
                    params_vector=tuple(float(normalized_named[name]) for name in normalized_named),
                    params_named=normalized_named,
                    objective_total=objective_total_value,
                    block_costs={
                        str(name): float(value)
                        for name, value in block_costs_raw.items()
                        if value is not None
                    },
                    status=str(raw_point.get("status", "objective_evaluated")),
                    failure_reason=raw_point.get("failure_reason"),
                )
            )
        return points

    if payload.get("role") == "calibration_regular_objective_grid":
        x_values = np.asarray(payload.get("x", ()), dtype=float)
        y_values = np.asarray(payload.get("y", ()), dtype=float)
        grid = np.asarray(payload.get("objective_total", ()), dtype=float)
        if x_values.ndim != 1 or y_values.ndim != 1 or grid.ndim != 2:
            return []
        points: list[ObjectiveMappingPoint] = []
        for row_index, y_value in enumerate(y_values):
            for col_index, x_value in enumerate(x_values):
                objective_value = grid[row_index, col_index]
                points.append(
                    ObjectiveMappingPoint(
                        iteration_id=f"reference_grid_{row_index:03d}_{col_index:03d}",
                        params_vector=(float(x_value), float(y_value)),
                        params_named={
                            str(payload["parameter_names"][0]): float(x_value),
                            str(payload["parameter_names"][1]): float(y_value),
                        },
                        objective_total=(
                            None
                            if not math.isfinite(float(objective_value))
                            else float(objective_value)
                        ),
                        status="objective_evaluated",
                        failure_reason=None,
                    )
                )
        return points
    return []


def _placeholder_observations(
    definition: TwinCalibrationCaseDefinition,
) -> dict[str, tuple[float, ...]]:
    """Return a minimal observed-value mapping accepted by case payload builders."""
    return {str(name): (0.0,) for name in definition.output_names}


def _case_payload(
    definition: TwinCalibrationCaseDefinition,
) -> dict[str, object]:
    """Build a representative calibration payload used to summarize the case."""
    if definition.build_calibration_payload is None:
        return {}
    if definition.method_profiles:
        method_profile = definition.method_profiles[0]
    else:
        method_profile = CalibrationMethodProfile(name="summary")
    try:
        return dict(
            definition.build_calibration_payload(
                "simulation.toml",
                "case_summary",
                _placeholder_observations(definition),
                method_profile,
            )
        )
    except Exception:
        return {}


def _support_label(payload: dict[str, object]) -> str:
    """Format one concise support description."""
    support = str(payload.get("support", "unknown"))
    if support == "point":
        x_value = payload.get("x")
        y_value = payload.get("y")
        parts = [support]
        if x_value is not None:
            parts.append(f"x={float(x_value):g}")
        if y_value is not None:
            parts.append(f"y={float(y_value):g}")
        return ", ".join(parts)
    if support == "boundary":
        boundary_id = payload.get("boundary_id")
        return f"boundary={boundary_id}" if boundary_id is not None else "boundary"
    return support


def _method_summary_lines(definition: TwinCalibrationCaseDefinition) -> list[str]:
    """Return human-readable method summary lines."""
    lines: list[str] = []
    for profile in definition.method_profiles:
        seeds = "" if not profile.repeat_seeds else f", seeds={list(profile.repeat_seeds)}"
        lines.append(
            f"- {profile.name} [{profile.success_metric}], "
            f"distribution={bool(profile.persist_model_distribution)}{seeds}"
        )
    return lines or ["- no method profile"]


def _noise_summary_lines(definition: TwinCalibrationCaseDefinition) -> list[str]:
    """Return concise lines describing synthetic observation perturbations."""
    noise = definition.observation_noise
    if noise is None:
        return ["- noise: none"]
    lines = [f"- noise seed={int(noise.seed)}"]
    if noise.absolute_sigma_by_output:
        lines.append(
            "- abs sigma: "
            + ", ".join(
                f"{name}={float(value):g}" for name, value in noise.absolute_sigma_by_output.items()
            )
        )
    if noise.relative_sigma_by_output:
        lines.append(
            "- rel sigma: "
            + ", ".join(
                f"{name}={float(value):g}" for name, value in noise.relative_sigma_by_output.items()
            )
        )
    return lines


def _parameter_zone_labels(payload: dict[str, object]) -> list[str]:
    """Extract zoned target labels from calibration parameter definitions."""
    labels: list[str] = []
    model_calibration = payload.get("model_calibration", {})
    if not isinstance(model_calibration, dict):
        return labels
    raw_parameters = model_calibration.get("parameter", [])
    if not isinstance(raw_parameters, list):
        return labels
    for parameter in raw_parameters:
        if not isinstance(parameter, dict):
            continue
        target = str(parameter.get("target", ""))
        if ".values_by_key." in target:
            labels.append(target.rsplit(".values_by_key.", maxsplit=1)[-1])
        lithology_key = parameter.get("lithology_key")
        if lithology_key is not None:
            labels.append(str(lithology_key))
    deduped: list[str] = []
    for label in labels:
        if label not in deduped:
            deduped.append(label)
    return deduped


def _draw_case_layout(
    *,
    axis,
    outputs: list[dict[str, object]],
    zone_labels: list[str],
) -> None:
    """Draw a simple schematic of observation supports for one case."""
    axis.set_title(
        "Observable Layout",
        loc="left",
        fontsize=SECTION_TITLE_FONTSIZE,
        fontweight="bold",
    )
    axis.set_xlim(0.0, 1.0)
    axis.set_ylim(0.0, 1.0)
    axis.set_aspect("auto")
    axis.axis("off")

    rectangle = axis.fill(
        [0.08, 0.92, 0.92, 0.08],
        [0.15, 0.15, 0.85, 0.85],
        facecolor="#f4f6f8",
        edgecolor="#7a8b99",
        linewidth=1.2,
        zorder=0,
    )
    del rectangle
    axis.text(
        0.5,
        0.88,
        "conceptual domain",
        ha="center",
        va="bottom",
        fontsize=CONFIG_TEXT_FONTSIZE,
    )

    point_outputs = [item for item in outputs if str(item.get("support")) == "point"]
    boundary_outputs = [item for item in outputs if str(item.get("support")) == "boundary"]

    x_values = [float(item["x"]) for item in point_outputs if item.get("x") is not None]
    y_values = [float(item["y"]) for item in point_outputs if item.get("y") is not None]
    x_min = min(x_values) if x_values else 0.0
    x_max = max(x_values) if x_values else 1.0
    y_min = min(y_values) if y_values else 0.0
    y_max = max(y_values) if y_values else 1.0
    x_span = max(x_max - x_min, 1.0)
    y_span = max(y_max - y_min, 1.0)

    for output in point_outputs:
        raw_x = float(output.get("x", x_min))
        raw_y = float(output.get("y")) if output.get("y") is not None else 0.5 * (y_min + y_max)
        x_pos = 0.12 + 0.76 * ((raw_x - x_min) / x_span)
        y_pos = 0.2 + 0.6 * ((raw_y - y_min) / y_span)
        axis.scatter(
            [x_pos],
            [y_pos],
            c="#2a9d8f",
            s=80,
            edgecolors="black",
            linewidths=0.6,
            zorder=3,
        )
        axis.text(
            x_pos,
            y_pos + 0.05,
            f"{output.get('name')}\n{output.get('variable')}",
            ha="center",
            va="bottom",
            fontsize=CONFIG_SMALL_TEXT_FONTSIZE,
        )

    boundary_positions = {
        "west": (0.08, 0.5),
        "east": (0.92, 0.5),
        "south": (0.5, 0.15),
        "north": (0.5, 0.85),
    }
    for index, output in enumerate(boundary_outputs, start=1):
        boundary_id = str(output.get("boundary_id", "")).lower()
        side = next(
            (name for name in boundary_positions if name in boundary_id),
            None,
        )
        if side is None:
            x_pos = 0.92
            y_pos = 0.2 + 0.12 * float(index)
        else:
            x_pos, y_pos = boundary_positions[side]
        axis.scatter(
            [x_pos],
            [y_pos],
            marker="s",
            c="#bc6c25",
            s=70,
            edgecolors="black",
            linewidths=0.6,
            zorder=3,
        )
        axis.text(
            x_pos,
            y_pos + 0.05,
            f"{output.get('name')}\n{output.get('boundary_id')}",
            ha="center",
            va="bottom",
            fontsize=CONFIG_SMALL_TEXT_FONTSIZE,
        )

    if zone_labels:
        axis.text(
            0.08,
            0.05,
            "zones: " + ", ".join(zone_labels),
            ha="left",
            va="center",
            fontsize=CONFIG_SMALL_TEXT_FONTSIZE,
        )


def write_case_configuration_figure(
    *,
    benchmark_root: Path,
    definition: TwinCalibrationCaseDefinition,
    simulation_config_path: Path,
    truth_simulation_config_path: Path,
    artifact_retention: str,
    figure_format: str = "png",
) -> Path | None:
    """Write one self-contained case-configuration figure."""
    plt = _try_import_matplotlib()
    if plt is None:
        return None

    payload = _case_payload(definition)
    model_calibration = payload.get("model_calibration", {})
    if not isinstance(model_calibration, dict):
        model_calibration = {}
    outputs = [item for item in model_calibration.get("output", []) if isinstance(item, dict)]
    parameters = [item for item in model_calibration.get("parameter", []) if isinstance(item, dict)]
    objective_blocks = [
        item for item in model_calibration.get("objective_block", []) if isinstance(item, dict)
    ]
    methods = _method_summary_lines(definition)
    noise_lines = _noise_summary_lines(definition)
    zone_labels = _parameter_zone_labels(payload)

    figure_root = benchmark_root / "figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    extension = str(figure_format).strip().lower() or "png"
    path = figure_root / f"case_configuration.{extension}"

    figure = plt.figure(figsize=(13.5, 9.0))
    grid = figure.add_gridspec(3, 2, height_ratios=[1.0, 1.1, 1.25], hspace=0.32, wspace=0.22)
    ax_meta = figure.add_subplot(grid[0, 0])
    ax_params = figure.add_subplot(grid[0, 1])
    ax_outputs = figure.add_subplot(grid[1, 0])
    ax_methods = figure.add_subplot(grid[1, 1])
    ax_layout = figure.add_subplot(grid[2, :])

    for axis in (ax_meta, ax_params, ax_outputs, ax_methods):
        axis.axis("off")

    figure.suptitle(
        _compact_case_title(definition.case_id, "configuration overview"),
        fontsize=CASE_SUPTITLE_FONTSIZE,
        fontweight="bold",
        y=0.985,
    )

    meta_lines = [
        f"solver={definition.solver_name}",
        f"regime={definition.regime}",
        f"retention={artifact_retention}",
        f"simulation={simulation_config_path.name}",
        (
            "truth simulation=same as calibration"
            if simulation_config_path == truth_simulation_config_path
            else f"truth simulation={truth_simulation_config_path.name}"
        ),
        f"fast={bool(definition.fast)}",
    ]
    if definition.perturbation_description:
        meta_lines.append(
            "perturbation="
            + textwrap.fill(
                str(definition.perturbation_description),
                width=42,
                subsequent_indent="  ",
            )
        )
    meta_lines.append(
        "description="
        + textwrap.fill(
            str(definition.description),
            width=44,
            subsequent_indent="  ",
        )
    )
    ax_meta.set_title(
        "Case Context",
        loc="left",
        fontsize=SECTION_TITLE_FONTSIZE,
        fontweight="bold",
    )
    ax_meta.text(
        0.0,
        1.0,
        "\n".join(meta_lines),
        ha="left",
        va="top",
        fontsize=CONFIG_TEXT_FONTSIZE,
        family="monospace",
        transform=ax_meta.transAxes,
    )

    parameter_lines: list[str] = []
    for parameter in parameters:
        name = str(parameter.get("name"))
        truth = definition.truth_params.get(name)
        lower, upper = definition.bounds.get(name, (None, None))
        tolerance = definition.parameter_abs_tolerances.get(name)
        parameter_lines.extend(
            [
                f"{name}",
                f"  truth={truth:g} bounds=[{lower:g}, {upper:g}] tol={tolerance:g}",
                f"  property={parameter.get('property')} mode={parameter.get('mode')}",
                f"  param={parameter.get('parameterization')}",
            ]
        )
    ax_params.set_title(
        "Parameters",
        loc="left",
        fontsize=SECTION_TITLE_FONTSIZE,
        fontweight="bold",
    )
    ax_params.text(
        0.0,
        1.0,
        "\n".join(parameter_lines or ["no parameter"]),
        ha="left",
        va="top",
        fontsize=CONFIG_TEXT_FONTSIZE,
        family="monospace",
        transform=ax_params.transAxes,
    )

    output_lines: list[str] = []
    for output in outputs:
        output_lines.append(
            f"{output.get('name')}: {output.get('variable')} | {_support_label(output)} | time={output.get('time')}"
        )
    if objective_blocks:
        output_lines.append("")
        output_lines.append("objective blocks:")
        for block in objective_blocks:
            output_lines.append(
                f"- {block.get('name')} metric={block.get('metric')} weight={float(block.get('weight', 0.0)):g} outputs={list(block.get('uses_outputs', []))}"
            )
    ax_outputs.set_title(
        "Observables And Objective",
        loc="left",
        fontsize=SECTION_TITLE_FONTSIZE,
        fontweight="bold",
    )
    ax_outputs.text(
        0.0,
        1.0,
        "\n".join(output_lines or ["no output"]),
        ha="left",
        va="top",
        fontsize=CONFIG_SMALL_TEXT_FONTSIZE,
        family="monospace",
        transform=ax_outputs.transAxes,
    )

    method_lines = [
        "methods:",
        *methods,
        "",
        *noise_lines,
    ]
    ax_methods.set_title(
        "Methods And Noise",
        loc="left",
        fontsize=SECTION_TITLE_FONTSIZE,
        fontweight="bold",
    )
    ax_methods.text(
        0.0,
        1.0,
        "\n".join(method_lines),
        ha="left",
        va="top",
        fontsize=CONFIG_TEXT_FONTSIZE,
        family="monospace",
        transform=ax_methods.transAxes,
    )

    _draw_case_layout(
        axis=ax_layout,
        outputs=outputs,
        zone_labels=zone_labels,
    )

    figure.tight_layout(rect=[0.0, 0.0, 1.0, 0.97])
    figure.savefig(path, dpi=180)
    plt.close(figure)
    return path


def _distribution_named_samples(
    distribution_path: Path | None,
) -> list[dict[str, float]]:
    """Load named parameter samples from one persisted model distribution."""
    if distribution_path is None or not distribution_path.is_file():
        return []
    try:
        payload = json.loads(distribution_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    samples = payload.get("samples")
    if not isinstance(samples, list):
        return []
    named_samples: list[dict[str, float]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        params_named = sample.get("params_named", {})
        if not isinstance(params_named, dict):
            continue
        try:
            named_samples.append({str(name): float(value) for name, value in params_named.items()})
        except (TypeError, ValueError):
            continue
    return named_samples


def _finite_points(points: list[ObjectiveMappingPoint]) -> list[ObjectiveMappingPoint]:
    """Keep only points carrying finite objective values."""
    return [point for point in points if point.finite_objective]


def _failed_points(points: list[ObjectiveMappingPoint]) -> list[ObjectiveMappingPoint]:
    """Keep points that failed objective evaluation."""
    return [point for point in points if not point.finite_objective]


def _plot_y_limits(
    finite_costs: list[float],
) -> tuple[float, float]:
    """Return robust Y limits for trace-style objective plots."""
    if not finite_costs:
        return 0.0, 1.0
    min_cost = float(min(finite_costs))
    max_cost = float(max(finite_costs))
    if math.isclose(min_cost, max_cost):
        delta = max(1.0e-6, 0.1 * max(abs(min_cost), 1.0))
        return min_cost - delta, max_cost + delta
    margin = 0.08 * (max_cost - min_cost)
    return min_cost - margin, max_cost + margin


def _idw_grid(
    *,
    xy: np.ndarray,
    values: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    power: float = 2.0,
) -> np.ndarray:
    """Interpolate values on a grid using inverse-distance weighting."""
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


def _normalize_axis_values(
    values: np.ndarray,
    *,
    lower: float,
    upper: float,
) -> np.ndarray:
    """Normalize one axis to ``[0, 1]`` while guarding degenerate bounds."""
    scale = float(upper) - float(lower)
    if not math.isfinite(scale) or abs(scale) <= 0.0:
        return np.zeros_like(values, dtype=float)
    return (np.asarray(values, dtype=float) - float(lower)) / scale


def _normalize_xy_for_interpolation(
    *,
    xy: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    bounds_x: tuple[float, float],
    bounds_y: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Scale interpolation coordinates to unit bounds so all axes contribute fairly."""
    normalized_xy = np.column_stack(
        [
            _normalize_axis_values(
                xy[:, 0],
                lower=float(bounds_x[0]),
                upper=float(bounds_x[1]),
            ),
            _normalize_axis_values(
                xy[:, 1],
                lower=float(bounds_y[0]),
                upper=float(bounds_y[1]),
            ),
        ]
    )
    normalized_grid_x = _normalize_axis_values(
        grid_x,
        lower=float(bounds_x[0]),
        upper=float(bounds_x[1]),
    )
    normalized_grid_y = _normalize_axis_values(
        grid_y,
        lower=float(bounds_y[0]),
        upper=float(bounds_y[1]),
    )
    return normalized_xy, normalized_grid_x, normalized_grid_y


def _write_objective_trace_figure(
    *,
    plt,
    path: Path,
    definition: TwinCalibrationCaseDefinition,
    result: TwinMethodBenchmarkResult,
    points: list[ObjectiveMappingPoint],
) -> bool:
    """Write the objective-vs-iteration trace for one method result."""
    if not points:
        return False
    finite_points = _finite_points(points)
    failed_points = _failed_points(points)
    finite_costs = [float(point.objective_total) for point in finite_points]
    y_min, y_max = _plot_y_limits(finite_costs)
    if failed_points:
        failed_level = y_max + 0.08 * max(y_max - y_min, 1.0)
        y_max = failed_level + 0.05 * max(y_max - y_min, 1.0)
    else:
        failed_level = None

    figure, axis = plt.subplots(figsize=(8.0, 4.8))
    if finite_points:
        xs = [index for index, point in enumerate(points, start=1) if point.finite_objective]
        ys = [float(point.objective_total) for point in finite_points]
        axis.plot(xs, ys, color="#284b63", linewidth=1.5, alpha=0.9)
        axis.scatter(xs, ys, color="#284b63", s=30, label="evaluated")
        best_index, best_point = min(
            (
                (index, point)
                for index, point in enumerate(points, start=1)
                if point.finite_objective
            ),
            key=lambda item: float(item[1].objective_total),
        )
        axis.scatter(
            [best_index],
            [float(best_point.objective_total)],
            marker="*",
            s=180,
            c="#f4a259",
            edgecolors="black",
            linewidths=0.8,
            label="best",
            zorder=5,
        )
    if failed_points and failed_level is not None:
        failed_xs = [
            index for index, point in enumerate(points, start=1) if not point.finite_objective
        ]
        axis.scatter(
            failed_xs,
            [failed_level for _ in failed_xs],
            marker="x",
            c="#c1121f",
            s=44,
            label="failed",
        )
    axis.set_xlabel("Iteration / evaluation index", fontsize=AXIS_LABEL_FONTSIZE)
    axis.set_ylabel("Objective total", fontsize=AXIS_LABEL_FONTSIZE)
    axis.set_title(
        _compact_case_title(
            definition.case_id,
            f"{result.method_instance_name} | objective trace",
        ),
        fontsize=CASE_TITLE_FONTSIZE,
    )
    axis.set_ylim(y_min, y_max)
    _apply_tick_style(axis)
    _apply_compact_legend(axis, loc="best")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180)
    plt.close(figure)
    return True


def _write_objective_landscape_1d(
    *,
    plt,
    path: Path,
    definition: TwinCalibrationCaseDefinition,
    result: TwinMethodBenchmarkResult,
    parameter_name: str,
    points: list[ObjectiveMappingPoint],
    distribution_samples: list[dict[str, float]],
    reference_points: list[ObjectiveMappingPoint] | None = None,
) -> bool:
    """Write one 1D objective plot with truth, best, and sampled solutions."""
    method_finite_points = sorted(
        [
            point
            for point in points
            if point.finite_objective and parameter_name in point.params_named
        ],
        key=lambda point: float(point.params_named[parameter_name]),
    )
    failed_points = [
        point
        for point in points
        if not point.finite_objective and parameter_name in point.params_named
    ]
    reference_finite_points = sorted(
        [
            point
            for point in (reference_points or [])
            if point.finite_objective and parameter_name in point.params_named
        ],
        key=lambda point: float(point.params_named[parameter_name]),
    )
    if not method_finite_points and not reference_finite_points and not failed_points:
        return False

    figure, axis = plt.subplots(figsize=(8.0, 4.8))
    finite_costs = [
        float(point.objective_total) for point in (reference_finite_points or method_finite_points)
    ]
    y_min, y_max = _plot_y_limits(finite_costs)
    if reference_finite_points:
        ref_x = [float(point.params_named[parameter_name]) for point in reference_finite_points]
        ref_y = [float(point.objective_total) for point in reference_finite_points]
        axis.plot(
            ref_x,
            ref_y,
            color="#5e6472",
            linewidth=1.1,
            alpha=0.9,
            label=f"reference ({len(reference_finite_points)})",
        )
        axis.scatter(
            ref_x,
            ref_y,
            color="#5e6472",
            s=18,
            alpha=0.75,
        )
    if method_finite_points:
        xs = [float(point.params_named[parameter_name]) for point in method_finite_points]
        ys = [float(point.objective_total) for point in method_finite_points]
        axis.scatter(
            xs,
            ys,
            color="#284b63",
            s=34,
            label="evaluated",
            zorder=4,
        )
    failed_level = None
    if failed_points:
        failed_level = y_max + 0.08 * max(y_max - y_min, 1.0)
        y_max = failed_level + 0.05 * max(y_max - y_min, 1.0)
        axis.scatter(
            [float(point.params_named[parameter_name]) for point in failed_points],
            [failed_level for _ in failed_points],
            marker="x",
            c="#c1121f",
            s=44,
            label="failed",
        )

    truth_value = float(definition.truth_params[parameter_name])
    axis.axvline(
        truth_value,
        color="#2a9d8f",
        linestyle="--",
        linewidth=1.4,
        label="truth",
    )
    if parameter_name in result.params_best and result.cost_best is not None:
        axis.scatter(
            [float(result.params_best[parameter_name])],
            [float(result.cost_best)],
            marker="*",
            s=180,
            c="#f4a259",
            edgecolors="black",
            linewidths=0.8,
            label="best",
            zorder=5,
        )

    if distribution_samples:
        distribution_x = [
            float(sample[parameter_name])
            for sample in distribution_samples
            if parameter_name in sample
        ]
        if distribution_x:
            rug_level = y_min - 0.04 * max(y_max - y_min, 1.0)
            y_min = rug_level - 0.05 * max(y_max - y_min, 1.0)
            axis.scatter(
                distribution_x,
                [rug_level for _ in distribution_x],
                marker="|",
                s=120,
                c="#8d99ae",
                linewidths=1.2,
                label="solutions",
            )

    lower, upper = definition.bounds[parameter_name]
    axis.set_xlim(float(lower), float(upper))
    axis.set_ylim(y_min, y_max)
    axis.set_xlabel(parameter_name, fontsize=AXIS_LABEL_FONTSIZE)
    axis.set_ylabel("Objective total", fontsize=AXIS_LABEL_FONTSIZE)
    axis.set_title(
        _compact_case_title(
            definition.case_id,
            f"{result.method_instance_name} | objective landscape",
        ),
        fontsize=CASE_TITLE_FONTSIZE,
    )
    _apply_tick_style(axis)
    _apply_compact_legend(axis, loc="best")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180)
    plt.close(figure)
    return True


def _write_objective_landscape_2d(
    *,
    plt,
    path: Path,
    definition: TwinCalibrationCaseDefinition,
    result: TwinMethodBenchmarkResult,
    parameter_names: tuple[str, str],
    points: list[ObjectiveMappingPoint],
    distribution_samples: list[dict[str, float]],
    reference_payload: dict[str, object] | None = None,
) -> bool:
    """Write one 2D interpolated objective map with solution overlays."""
    finite_points = [
        point
        for point in points
        if point.finite_objective
        and parameter_names[0] in point.params_named
        and parameter_names[1] in point.params_named
    ]
    failed_points = [
        point
        for point in points
        if not point.finite_objective
        and parameter_names[0] in point.params_named
        and parameter_names[1] in point.params_named
    ]
    reference_points = [
        point
        for point in _reference_objective_points(reference_payload)
        if point.finite_objective
        and parameter_names[0] in point.params_named
        and parameter_names[1] in point.params_named
    ]
    if not finite_points and not failed_points and not reference_points:
        return False

    figure, axis = plt.subplots(figsize=(7.4, 6.0))
    x_values = np.asarray(())
    y_values = np.asarray(())
    grid = np.asarray(())
    grid_source_label = None
    interpolation_xy_points = reference_points if len(reference_points) >= 3 else finite_points
    if len(interpolation_xy_points) >= 3:
        bounds_x = tuple(float(value) for value in definition.bounds[parameter_names[0]])
        bounds_y = tuple(float(value) for value in definition.bounds[parameter_names[1]])
        x_values = np.linspace(bounds_x[0], bounds_x[1], 60)
        y_values = np.linspace(bounds_y[0], bounds_y[1], 60)
        grid_x, grid_y = np.meshgrid(x_values, y_values)
        xy = np.asarray(
            [
                (
                    float(point.params_named[parameter_names[0]]),
                    float(point.params_named[parameter_names[1]]),
                )
                for point in interpolation_xy_points
            ],
            dtype=float,
        )
        costs = np.asarray(
            [float(point.objective_total) for point in interpolation_xy_points],
            dtype=float,
        )
        normalized_xy, normalized_grid_x, normalized_grid_y = _normalize_xy_for_interpolation(
            xy=xy,
            grid_x=grid_x,
            grid_y=grid_y,
            bounds_x=bounds_x,
            bounds_y=bounds_y,
        )
        grid = _idw_grid(
            xy=normalized_xy,
            values=costs,
            grid_x=normalized_grid_x,
            grid_y=normalized_grid_y,
        )
        if reference_points:
            grid_source_label = f"reference sample n={len(reference_points)}"
        else:
            grid_source_label = f"evaluated points n={len(finite_points)}"
    if isinstance(grid, np.ndarray) and grid.ndim == 2 and np.any(np.isfinite(grid)):
        contour = axis.contourf(
            x_values,
            y_values,
            grid,
            levels=24,
            cmap="viridis",
        )
        colorbar = figure.colorbar(contour, ax=axis, label="Objective total")
        colorbar.ax.tick_params(labelsize=TICK_LABEL_FONTSIZE)
        colorbar.set_label("Objective total", fontsize=AXIS_LABEL_FONTSIZE)
        axis.contour(
            x_values,
            y_values,
            grid,
            levels=10,
            colors="white",
            linewidths=0.35,
            alpha=0.35,
        )

    if reference_points:
        axis.scatter(
            [float(point.params_named[parameter_names[0]]) for point in reference_points],
            [float(point.params_named[parameter_names[1]]) for point in reference_points],
            c=[float(point.objective_total) for point in reference_points],
            cmap="viridis",
            s=10,
            alpha=0.32,
            linewidths=0.0,
            label="reference sample",
            zorder=2,
        )

    if finite_points:
        axis.scatter(
            [float(point.params_named[parameter_names[0]]) for point in finite_points],
            [float(point.params_named[parameter_names[1]]) for point in finite_points],
            c=[float(point.objective_total) for point in finite_points],
            cmap="viridis",
            edgecolors="black",
            linewidths=0.4,
            s=34,
            label="evaluated",
        )
    if failed_points:
        axis.scatter(
            [float(point.params_named[parameter_names[0]]) for point in failed_points],
            [float(point.params_named[parameter_names[1]]) for point in failed_points],
            marker="x",
            c="#c1121f",
            s=46,
            label="failed",
        )

    axis.scatter(
        [float(definition.truth_params[parameter_names[0]])],
        [float(definition.truth_params[parameter_names[1]])],
        marker="o",
        facecolors="white",
        edgecolors="black",
        linewidths=1.0,
        s=90,
        label="truth",
        zorder=5,
    )
    if all(name in result.params_best for name in parameter_names):
        axis.scatter(
            [float(result.params_best[parameter_names[0]])],
            [float(result.params_best[parameter_names[1]])],
            marker="*",
            c="#f4a259",
            edgecolors="black",
            linewidths=0.8,
            s=180,
            label="best",
            zorder=6,
        )

    if distribution_samples:
        distribution_xy = [
            (
                float(sample[parameter_names[0]]),
                float(sample[parameter_names[1]]),
            )
            for sample in distribution_samples
            if parameter_names[0] in sample and parameter_names[1] in sample
        ]
        if distribution_xy:
            axis.scatter(
                [item[0] for item in distribution_xy],
                [item[1] for item in distribution_xy],
                facecolors="none",
                edgecolors="#8d99ae",
                linewidths=0.9,
                s=44,
                alpha=0.9,
                label="solutions",
            )

    axis.set_xlim(*[float(value) for value in definition.bounds[parameter_names[0]]])
    axis.set_ylim(*[float(value) for value in definition.bounds[parameter_names[1]]])
    axis.set_xlabel(parameter_names[0], fontsize=AXIS_LABEL_FONTSIZE)
    axis.set_ylabel(parameter_names[1], fontsize=AXIS_LABEL_FONTSIZE)
    axis.set_title(
        _compact_case_title(
            definition.case_id,
            f"{result.method_instance_name} | objective landscape",
        ),
        fontsize=CASE_TITLE_FONTSIZE,
    )
    if grid_source_label is not None:
        axis.text(
            0.99,
            0.01,
            f"surface: {grid_source_label}",
            transform=axis.transAxes,
            ha="right",
            va="bottom",
            fontsize=ANNOTATION_FONTSIZE,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.75, "pad": 2.0},
        )
    _apply_tick_style(axis)
    _apply_compact_legend(axis, loc="best")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180)
    plt.close(figure)
    return True


def _write_objective_landscape_pairgrid(
    *,
    plt,
    path: Path,
    definition: TwinCalibrationCaseDefinition,
    result: TwinMethodBenchmarkResult,
    parameter_names: tuple[str, ...],
    points: list[ObjectiveMappingPoint],
    distribution_samples: list[dict[str, float]],
    reference_points: list[ObjectiveMappingPoint] | None = None,
) -> bool:
    """Write one pair-grid view when the benchmark has more than 2 parameters."""
    method_finite_points = [
        point
        for point in points
        if point.finite_objective and all(name in point.params_named for name in parameter_names)
    ]
    failed_points = [
        point
        for point in points
        if not point.finite_objective
        and all(name in point.params_named for name in parameter_names)
    ]
    finite_points = [
        point
        for point in (reference_points or method_finite_points)
        if point.finite_objective and all(name in point.params_named for name in parameter_names)
    ]
    if not finite_points and not failed_points:
        return False

    n_params = len(parameter_names)
    figure, axes = plt.subplots(
        n_params,
        n_params,
        figsize=(3.4 * n_params, 3.1 * n_params),
        squeeze=False,
    )
    finite_costs = [float(point.objective_total) for point in finite_points]
    cost_min = min(finite_costs) if finite_costs else 0.0
    cost_max = max(finite_costs) if finite_costs else 1.0

    for row_index, row_name in enumerate(parameter_names):
        for col_index, col_name in enumerate(parameter_names):
            axis = axes[row_index][col_index]
            if row_index == col_index:
                if finite_points:
                    axis.scatter(
                        [float(point.params_named[row_name]) for point in finite_points],
                        [float(point.objective_total) for point in finite_points],
                        c=[float(point.objective_total) for point in finite_points],
                        cmap="viridis",
                        vmin=cost_min,
                        vmax=cost_max,
                        s=16 if reference_points else 28,
                        alpha=0.7 if reference_points else 0.9,
                    )
                if reference_points and method_finite_points:
                    axis.scatter(
                        [float(point.params_named[row_name]) for point in method_finite_points],
                        [float(point.objective_total) for point in method_finite_points],
                        facecolors="none",
                        edgecolors="#284b63",
                        linewidths=0.7,
                        s=28,
                    )
                axis.axvline(
                    float(definition.truth_params[row_name]),
                    color="#2a9d8f",
                    linestyle="--",
                    linewidth=1.2,
                )
                if row_name in result.params_best and result.cost_best is not None:
                    axis.scatter(
                        [float(result.params_best[row_name])],
                        [float(result.cost_best)],
                        marker="*",
                        c="#f4a259",
                        edgecolors="black",
                        linewidths=0.8,
                        s=140,
                        zorder=5,
                    )
                if distribution_samples:
                    sample_x = [
                        float(sample[row_name])
                        for sample in distribution_samples
                        if row_name in sample
                    ]
                    if sample_x:
                        y_anchor = axis.get_ylim()[0]
                        axis.scatter(
                            sample_x,
                            [y_anchor for _ in sample_x],
                            marker="|",
                            c="#8d99ae",
                            s=90,
                            linewidths=1.0,
                        )
                axis.set_ylabel("Objective", fontsize=AXIS_LABEL_FONTSIZE)
            else:
                if finite_points:
                    axis.scatter(
                        [float(point.params_named[col_name]) for point in finite_points],
                        [float(point.params_named[row_name]) for point in finite_points],
                        c=[float(point.objective_total) for point in finite_points],
                        cmap="viridis",
                        vmin=cost_min,
                        vmax=cost_max,
                        s=14 if reference_points else 26,
                        alpha=0.55 if reference_points else 0.9,
                    )
                if reference_points and method_finite_points:
                    axis.scatter(
                        [float(point.params_named[col_name]) for point in method_finite_points],
                        [float(point.params_named[row_name]) for point in method_finite_points],
                        facecolors="none",
                        edgecolors="#284b63",
                        linewidths=0.6,
                        s=24,
                        alpha=0.9,
                    )
                if failed_points:
                    axis.scatter(
                        [float(point.params_named[col_name]) for point in failed_points],
                        [float(point.params_named[row_name]) for point in failed_points],
                        marker="x",
                        c="#c1121f",
                        s=28,
                    )
                axis.scatter(
                    [float(definition.truth_params[col_name])],
                    [float(definition.truth_params[row_name])],
                    marker="o",
                    facecolors="white",
                    edgecolors="black",
                    linewidths=0.9,
                    s=70,
                    zorder=5,
                )
                if col_name in result.params_best and row_name in result.params_best:
                    axis.scatter(
                        [float(result.params_best[col_name])],
                        [float(result.params_best[row_name])],
                        marker="*",
                        c="#f4a259",
                        edgecolors="black",
                        linewidths=0.8,
                        s=120,
                        zorder=6,
                    )
                if distribution_samples:
                    distribution_xy = [
                        (
                            float(sample[col_name]),
                            float(sample[row_name]),
                        )
                        for sample in distribution_samples
                        if col_name in sample and row_name in sample
                    ]
                    if distribution_xy:
                        axis.scatter(
                            [item[0] for item in distribution_xy],
                            [item[1] for item in distribution_xy],
                            facecolors="none",
                            edgecolors="#8d99ae",
                            linewidths=0.8,
                            s=34,
                            alpha=0.8,
                        )
                axis.set_xlim(*[float(value) for value in definition.bounds[col_name]])
                axis.set_ylim(*[float(value) for value in definition.bounds[row_name]])
            if row_index == n_params - 1:
                axis.set_xlabel(col_name, fontsize=AXIS_LABEL_FONTSIZE)
            if col_index == 0 and row_index != col_index:
                axis.set_ylabel(row_name, fontsize=AXIS_LABEL_FONTSIZE)
            _apply_tick_style(axis)
            axis.grid(alpha=0.15)

    figure.suptitle(
        _compact_case_title(
            definition.case_id,
            (
                f"{result.method_instance_name} | objective pair view"
                + (f" | reference n={len(reference_points)}" if reference_points else "")
            ),
        ),
        fontsize=CASE_SUPTITLE_FONTSIZE,
        y=0.995,
    )
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180)
    plt.close(figure)
    return True


def _write_posterior_distribution_1d(
    *,
    plt,
    path: Path,
    definition: TwinCalibrationCaseDefinition,
    result: TwinMethodBenchmarkResult,
    parameter_name: str,
    distribution_samples: list[dict[str, float]],
) -> bool:
    """Write a dedicated 1D posterior/ensemble figure."""
    sample_values = [
        float(sample[parameter_name]) for sample in distribution_samples if parameter_name in sample
    ]
    if not sample_values:
        return False

    figure, axis = plt.subplots(figsize=(8.0, 4.8))
    lower, upper = definition.bounds[parameter_name]
    if len(sample_values) >= 2:
        axis.hist(
            sample_values,
            bins=min(24, max(6, len(sample_values) // 2)),
            range=(float(lower), float(upper)),
            color="#8d99ae",
            edgecolor="black",
            alpha=0.85,
            label="distribution",
        )
    else:
        axis.scatter(
            sample_values,
            [1.0],
            marker="o",
            s=80,
            c="#8d99ae",
            edgecolors="black",
            linewidths=0.8,
            label="distribution",
            zorder=4,
        )
        axis.set_ylim(0.0, 1.5)

    axis.axvline(
        float(definition.truth_params[parameter_name]),
        color="#2a9d8f",
        linestyle="--",
        linewidth=1.4,
        label="truth",
    )
    if parameter_name in result.params_best:
        axis.axvline(
            float(result.params_best[parameter_name]),
            color="#f4a259",
            linestyle="-",
            linewidth=1.4,
            label="best",
        )
    axis.set_xlim(float(lower), float(upper))
    axis.set_xlabel(parameter_name, fontsize=AXIS_LABEL_FONTSIZE)
    axis.set_ylabel("Sample count", fontsize=AXIS_LABEL_FONTSIZE)
    axis.set_title(
        _compact_case_title(
            definition.case_id,
            f"{result.method_instance_name} | distribution (n={len(sample_values)})",
        ),
        fontsize=CASE_TITLE_FONTSIZE,
    )
    _apply_tick_style(axis)
    _apply_compact_legend(axis, loc="best")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180)
    plt.close(figure)
    return True


def _write_posterior_distribution_2d(
    *,
    plt,
    path: Path,
    definition: TwinCalibrationCaseDefinition,
    result: TwinMethodBenchmarkResult,
    parameter_names: tuple[str, str],
    distribution_samples: list[dict[str, float]],
) -> bool:
    """Write a dedicated 2D posterior/ensemble scatter figure."""
    sample_xy = [
        (
            float(sample[parameter_names[0]]),
            float(sample[parameter_names[1]]),
        )
        for sample in distribution_samples
        if parameter_names[0] in sample and parameter_names[1] in sample
    ]
    if not sample_xy:
        return False

    figure, axis = plt.subplots(figsize=(7.4, 6.0))
    if len(sample_xy) > 1:
        axis.scatter(
            [item[0] for item in sample_xy],
            [item[1] for item in sample_xy],
            c=np.linspace(0.0, 1.0, len(sample_xy)),
            cmap="Blues",
            s=42,
            alpha=0.85,
            edgecolors="black",
            linewidths=0.3,
            label="distribution",
        )
    else:
        axis.scatter(
            [sample_xy[0][0]],
            [sample_xy[0][1]],
            c="#8d99ae",
            s=64,
            edgecolors="black",
            linewidths=0.5,
            label="distribution",
        )
    axis.scatter(
        [float(definition.truth_params[parameter_names[0]])],
        [float(definition.truth_params[parameter_names[1]])],
        marker="o",
        facecolors="white",
        edgecolors="black",
        linewidths=1.0,
        s=90,
        label="truth",
        zorder=5,
    )
    if all(name in result.params_best for name in parameter_names):
        axis.scatter(
            [float(result.params_best[parameter_names[0]])],
            [float(result.params_best[parameter_names[1]])],
            marker="*",
            c="#f4a259",
            edgecolors="black",
            linewidths=0.8,
            s=180,
            label="best",
            zorder=6,
        )
    axis.set_xlim(*[float(value) for value in definition.bounds[parameter_names[0]]])
    axis.set_ylim(*[float(value) for value in definition.bounds[parameter_names[1]]])
    axis.set_xlabel(parameter_names[0], fontsize=AXIS_LABEL_FONTSIZE)
    axis.set_ylabel(parameter_names[1], fontsize=AXIS_LABEL_FONTSIZE)
    axis.set_title(
        _compact_case_title(
            definition.case_id,
            f"{result.method_instance_name} | distribution (n={len(sample_xy)})",
        ),
        fontsize=CASE_TITLE_FONTSIZE,
    )
    _apply_tick_style(axis)
    _apply_compact_legend(axis, loc="best")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180)
    plt.close(figure)
    return True


def _write_posterior_distribution_pairgrid(
    *,
    plt,
    path: Path,
    definition: TwinCalibrationCaseDefinition,
    result: TwinMethodBenchmarkResult,
    parameter_names: tuple[str, ...],
    distribution_samples: list[dict[str, float]],
) -> bool:
    """Write a pair-grid style distribution view for >2 parameters."""
    valid_samples = [
        sample for sample in distribution_samples if all(name in sample for name in parameter_names)
    ]
    if not valid_samples:
        return False

    n_params = len(parameter_names)
    figure, axes = plt.subplots(
        n_params,
        n_params,
        figsize=(3.2 * n_params, 3.0 * n_params),
        squeeze=False,
    )
    for row_index, row_name in enumerate(parameter_names):
        for col_index, col_name in enumerate(parameter_names):
            axis = axes[row_index][col_index]
            if row_index == col_index:
                values = [float(sample[row_name]) for sample in valid_samples]
                if len(values) >= 2:
                    axis.hist(
                        values,
                        bins=min(20, max(5, len(values) // 2)),
                        color="#8d99ae",
                        edgecolor="black",
                        alpha=0.85,
                    )
                else:
                    axis.scatter(values, [1.0], c="#8d99ae", s=48)
                axis.axvline(
                    float(definition.truth_params[row_name]),
                    color="#2a9d8f",
                    linestyle="--",
                    linewidth=1.2,
                )
                if row_name in result.params_best:
                    axis.axvline(
                        float(result.params_best[row_name]),
                        color="#f4a259",
                        linewidth=1.2,
                    )
                axis.set_xlim(*[float(value) for value in definition.bounds[row_name]])
                axis.set_ylabel("Count", fontsize=AXIS_LABEL_FONTSIZE)
            else:
                axis.scatter(
                    [float(sample[col_name]) for sample in valid_samples],
                    [float(sample[row_name]) for sample in valid_samples],
                    c="#8d99ae",
                    s=28,
                    alpha=0.75,
                    edgecolors="black",
                    linewidths=0.2,
                )
                axis.scatter(
                    [float(definition.truth_params[col_name])],
                    [float(definition.truth_params[row_name])],
                    marker="o",
                    facecolors="white",
                    edgecolors="black",
                    linewidths=0.9,
                    s=60,
                    zorder=5,
                )
                if col_name in result.params_best and row_name in result.params_best:
                    axis.scatter(
                        [float(result.params_best[col_name])],
                        [float(result.params_best[row_name])],
                        marker="*",
                        c="#f4a259",
                        edgecolors="black",
                        linewidths=0.7,
                        s=100,
                        zorder=6,
                    )
                axis.set_xlim(*[float(value) for value in definition.bounds[col_name]])
                axis.set_ylim(*[float(value) for value in definition.bounds[row_name]])
            if row_index == n_params - 1:
                axis.set_xlabel(col_name, fontsize=AXIS_LABEL_FONTSIZE)
            if col_index == 0 and row_index != col_index:
                axis.set_ylabel(row_name, fontsize=AXIS_LABEL_FONTSIZE)
            _apply_tick_style(axis)
            axis.grid(alpha=0.15)

    figure.suptitle(
        _compact_case_title(
            definition.case_id,
            f"{result.method_instance_name} | distribution (n={len(valid_samples)})",
        ),
        fontsize=CASE_SUPTITLE_FONTSIZE,
        y=0.995,
    )
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180)
    plt.close(figure)
    return True


def write_case_method_figures(
    *,
    benchmark_root: Path,
    definition: TwinCalibrationCaseDefinition,
    result: TwinMethodBenchmarkResult,
    figure_format: str = "png",
) -> dict[str, Path]:
    """Write per-method objective figures for one benchmark case."""
    if not definition.generate_case_figures:
        return {}
    if result.iteration_history_path is None or not result.iteration_history_path.is_file():
        return {}
    plt = _try_import_matplotlib()
    if plt is None:
        return {}

    points = load_objective_mapping_points(result.iteration_history_path)
    if not points:
        return {}

    distribution_samples = _distribution_named_samples(result.model_distribution_path)
    reference_payload = _load_reference_objective_payload(
        benchmark_root=benchmark_root,
        definition=definition,
    )
    reference_points = _reference_objective_points(reference_payload)
    parameter_names = tuple(definition.truth_params.keys())
    figure_root = benchmark_root / "figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    extension = str(figure_format).strip().lower() or "png"
    slug = _sanitize_method_slug(result.method_instance_name)

    trace_path = figure_root / f"objective_trace__{slug}.{extension}"
    landscape_path = figure_root / f"objective_landscape__{slug}.{extension}"
    posterior_path = figure_root / f"posterior_distribution__{slug}.{extension}"
    written: dict[str, Path] = {}

    if _write_objective_trace_figure(
        plt=plt,
        path=trace_path,
        definition=definition,
        result=result,
        points=points,
    ):
        written["objective_trace"] = trace_path

    if len(parameter_names) == 1:
        landscape_written = _write_objective_landscape_1d(
            plt=plt,
            path=landscape_path,
            definition=definition,
            result=result,
            parameter_name=parameter_names[0],
            points=points,
            distribution_samples=distribution_samples,
            reference_points=reference_points,
        )
    elif len(parameter_names) == 2:
        landscape_written = _write_objective_landscape_2d(
            plt=plt,
            path=landscape_path,
            definition=definition,
            result=result,
            parameter_names=(parameter_names[0], parameter_names[1]),
            points=points,
            distribution_samples=distribution_samples,
            reference_payload=reference_payload,
        )
    else:
        landscape_written = _write_objective_landscape_pairgrid(
            plt=plt,
            path=landscape_path,
            definition=definition,
            result=result,
            parameter_names=parameter_names,
            points=points,
            distribution_samples=distribution_samples,
            reference_points=reference_points,
        )
    if landscape_written:
        written["objective_landscape"] = landscape_path

    posterior_written = False
    if distribution_samples:
        if len(parameter_names) == 1:
            posterior_written = _write_posterior_distribution_1d(
                plt=plt,
                path=posterior_path,
                definition=definition,
                result=result,
                parameter_name=parameter_names[0],
                distribution_samples=distribution_samples,
            )
        elif len(parameter_names) == 2:
            posterior_written = _write_posterior_distribution_2d(
                plt=plt,
                path=posterior_path,
                definition=definition,
                result=result,
                parameter_names=(parameter_names[0], parameter_names[1]),
                distribution_samples=distribution_samples,
            )
        else:
            posterior_written = _write_posterior_distribution_pairgrid(
                plt=plt,
                path=posterior_path,
                definition=definition,
                result=result,
                parameter_names=parameter_names,
                distribution_samples=distribution_samples,
            )
    if posterior_written:
        written["posterior_distribution"] = posterior_path

    return written
