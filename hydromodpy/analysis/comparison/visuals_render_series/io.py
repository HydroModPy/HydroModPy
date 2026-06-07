"""Runtime and budget dashboards (matplotlib outputs)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

from hydromodpy.analysis.comparison.visuals_format import _apply_time_ticks
from hydromodpy.analysis.comparison.visuals_style import (
    _LABEL_FONT_SIZE,
    _LEGEND_FONT_SIZE,
    _PANEL_TITLE_FONT_SIZE,
    _TICK_FONT_SIZE,
    _TITLE_FONT_SIZE,
    _budget_component_color,
    _budget_component_label,
    _display_simulation_label,
    _legend_ncols,
    _safe_float,
    _solver_color,
)
from hydromodpy.core.units.time import SECONDS_PER_DAY

from .aggregation import (
    _budget_component_points,
    _budget_time_field,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _write_runtime_bar_figure(
    *,
    path: Path,
    execution_rows: list[Mapping[str, Any]],
    reference_simulation: str | None,
) -> bool:
    rows = [row for row in execution_rows if _safe_float(row.get("runtime_seconds")) is not None]
    if len(rows) < 2:
        return False
    ordered = sorted(rows, key=lambda item: float(item["runtime_seconds"]), reverse=True)
    labels = [
        _display_simulation_label(
            simulation_id=str(row.get("simulation_id", "")),
            simulation_label=str(row.get("simulation_label", row.get("simulation_id", ""))),
        )
        for row in ordered
    ]
    runtimes = [float(row["runtime_seconds"]) for row in ordered]
    colors = [_solver_color(str(row.get("solver", ""))) for row in ordered]
    time_scopes = {
        str(row.get("time_scope", "") or "").strip().lower()
        for row in ordered
        if str(row.get("time_scope", "") or "").strip()
    }
    is_flow_solve_time = time_scopes == {"flow_solve"}

    figure_height = max(2.8, 0.72 * len(ordered) + 1.1)
    figure, ax = plt.subplots(1, 1, figsize=(7.4, figure_height))
    positions = np.arange(len(ordered))
    bars = ax.barh(positions, runtimes, color=colors, edgecolor="none", height=0.58)
    ax.set_yticks(positions, labels=labels, fontsize=_LABEL_FONT_SIZE)
    ax.set_xlabel(
        "Flow solve time [s]" if is_flow_solve_time else "Runtime [s]",
        fontsize=_LABEL_FONT_SIZE,
    )
    ax.tick_params(axis="x", labelsize=_TICK_FONT_SIZE)
    ax.grid(axis="x", alpha=0.22, linewidth=0.6)
    ax.set_title(
        "Flow solve time comparison" if is_flow_solve_time else "Execution time comparison",
        fontsize=_TITLE_FONT_SIZE,
        pad=8,
    )

    reference_runtime = None
    if reference_simulation is not None:
        for row in ordered:
            if str(row.get("simulation_id", "")) == reference_simulation:
                reference_runtime = float(row["runtime_seconds"])
                break
    max_runtime = max(runtimes)
    for bar, row in zip(bars, ordered, strict=False):
        runtime = float(row["runtime_seconds"])
        speedup = (
            reference_runtime / runtime
            if reference_runtime is not None and runtime > 0.0
            else math.nan
        )
        annotation = f"{runtime:.2f} s"
        if math.isfinite(speedup):
            annotation += f"  ({speedup:.2f}x ref)"
        ax.text(
            runtime + max_runtime * 0.02,
            bar.get_y() + bar.get_height() / 2.0,
            annotation,
            va="center",
            ha="left",
            fontsize=_LEGEND_FONT_SIZE,
        )
    ax.set_xlim(0.0, max_runtime * 1.34)
    figure.subplots_adjust(left=0.28, right=0.97, top=0.87, bottom=0.16)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_storage_comparison_dashboard(
    *,
    path: Path,
    budget_rows: list[Mapping[str, Any]],
) -> bool:
    """Write a global storage-rate comparison figure across simulations."""
    storage_rows = [
        row for row in budget_rows if str(row.get("component", "")) == "storage_change_total_m3_s"
    ]
    if not storage_rows:
        return False
    use_elapsed_seconds, x_field, x_label = _budget_time_field(storage_rows)
    grouped = _budget_component_points(
        storage_rows,
        component="storage_change_total_m3_s",
        x_field=x_field,
        use_elapsed_seconds=use_elapsed_seconds,
    )
    if not any(len(points) >= 2 for points in grouped.values()):
        return False

    figure, ax = plt.subplots(figsize=(8.1, 4.5))
    tick_positions: list[float] = []

    for (simulation_id, simulation_label), points in sorted(grouped.items()):
        ordered = sorted(points, key=lambda item: item[0])
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        label = _display_simulation_label(
            simulation_id=simulation_id,
            simulation_label=simulation_label,
        )
        ax.step(
            x_values,
            y_values,
            where="post",
            linewidth=2.0,
            color=_solver_color(simulation_id),
            label=label,
        )

    ax.set_title("Global storage change rate", fontsize=_PANEL_TITLE_FONT_SIZE, pad=5, loc="left")
    ax.set_ylabel("m3/s", fontsize=_LABEL_FONT_SIZE)
    ax.set_xlabel(x_label, fontsize=_LABEL_FONT_SIZE)
    ax.grid(True, alpha=0.18, linewidth=0.6)
    ax.axhline(0.0, color="#9ca3af", linewidth=0.8, alpha=0.8)
    ax.tick_params(labelsize=_TICK_FONT_SIZE)
    handles, labels = ax.get_legend_handles_labels()
    if labels:
        ax.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.18),
            ncol=_legend_ncols(len(labels)),
            frameon=False,
            fontsize=_LEGEND_FONT_SIZE,
        )

    if not use_elapsed_seconds:
        _apply_time_ticks(ax, tick_positions=tick_positions, tick_labels=None)
    figure.suptitle("Storage comparison", fontsize=_TITLE_FONT_SIZE, y=0.98)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.82, bottom=0.28)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_total_input_output_dashboard(
    *,
    path: Path,
    budget_rows: list[Mapping[str, Any]],
) -> bool:
    """Write total external inflow and outflow curves for each simulation."""
    if not budget_rows:
        return False
    use_elapsed_seconds, x_field, x_label = _budget_time_field(budget_rows)
    by_sim_time: dict[tuple[str, str, float], dict[str, float]] = {}
    tick_positions: list[float] = []
    for row in budget_rows:
        component = str(row.get("component", ""))
        if component in {"storage_change_total_m3_s", "closure_residual_m3_s"}:
            continue
        x_value = _safe_float(row.get(x_field))
        if x_value is not None and use_elapsed_seconds:
            x_value = x_value / SECONDS_PER_DAY
        value = _safe_float(row.get("value"))
        if x_value is None or value is None:
            continue
        simulation_id = str(row.get("simulation_id", ""))
        simulation_label = str(row.get("simulation_label", simulation_id))
        item = by_sim_time.setdefault(
            (simulation_id, simulation_label, x_value),
            {"input": 0.0, "output": 0.0},
        )
        if component in {"recharge_total_m3_s", "dry_deficit_total_m3_s"}:
            item["input"] += max(value, 0.0)
        elif component == "well_total_m3_s":
            if value >= 0.0:
                item["input"] += value
            else:
                item["output"] += abs(value)
        elif component in {
            "prescribed_head_out_total_m3_s",
            "drainage_total_m3_s",
            "surface_excess_total_m3_s",
            "balance_implied_outflow_total_m3_s",
            "comparable_outflow_total_m3_s",
        }:
            if component != "comparable_outflow_total_m3_s":
                item["output"] += max(value, 0.0)
        tick_positions.append(x_value)

    grouped: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
    for (simulation_id, simulation_label, x_value), values in by_sim_time.items():
        grouped.setdefault((simulation_id, simulation_label), []).append(
            (x_value, values["input"], values["output"])
        )
    if not any(len(points) >= 2 for points in grouped.values()):
        return False

    figure, ax = plt.subplots(figsize=(8.1, 4.5))
    for (simulation_id, simulation_label), points in sorted(grouped.items()):
        ordered = sorted(points, key=lambda item: item[0])
        x_values = [item[0] for item in ordered]
        inputs = [item[1] for item in ordered]
        outputs = [item[2] for item in ordered]
        label = _display_simulation_label(
            simulation_id=simulation_id,
            simulation_label=simulation_label,
        )
        color = _solver_color(simulation_id)
        ax.step(
            x_values,
            inputs,
            where="post",
            linewidth=2.0,
            color=color,
            label=f"{label} - total inputs",
        )
        ax.step(
            x_values,
            outputs,
            where="post",
            linewidth=2.0,
            linestyle="--",
            color=color,
            label=f"{label} - total outputs",
        )
    ax.set_title(
        "External water balance: inputs vs outputs",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=5,
        loc="left",
    )
    ax.set_ylabel("m3/s", fontsize=_LABEL_FONT_SIZE)
    ax.set_xlabel(x_label, fontsize=_LABEL_FONT_SIZE)
    ax.grid(True, alpha=0.18, linewidth=0.6)
    ax.axhline(0.0, color="#9ca3af", linewidth=0.8, alpha=0.8)
    ax.tick_params(labelsize=_TICK_FONT_SIZE)
    handles, labels = ax.get_legend_handles_labels()
    if labels:
        ax.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.18),
            ncol=_legend_ncols(len(labels)),
            frameon=False,
            fontsize=_LEGEND_FONT_SIZE,
        )
    if not use_elapsed_seconds:
        _apply_time_ticks(ax, tick_positions=tick_positions, tick_labels=None)
    figure.suptitle("Total inputs and outputs", fontsize=_TITLE_FONT_SIZE, y=0.98)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.82, bottom=0.28)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_budget_diagnostic_figure(
    *,
    path: Path,
    simulation_id: str,
    simulation_label: str,
    budget_rows: list[Mapping[str, Any]],
    rows: list[dict[str, Any]],
) -> bool:
    simulation_budget_rows = [
        row for row in budget_rows if str(row.get("simulation_id", "")) == simulation_id
    ]
    if not simulation_budget_rows:
        return False

    use_elapsed_seconds = all(
        _safe_float(row.get("elapsed_seconds")) is not None for row in simulation_budget_rows
    )
    x_field = "elapsed_seconds" if use_elapsed_seconds else "time_index"
    x_label = "Elapsed time [d]" if use_elapsed_seconds else "Time step"

    component_groups: dict[str, list[tuple[float, float]]] = {}
    time_labels: dict[int, str] = {}
    for row in simulation_budget_rows:
        component = str(row.get("component", "")).strip()
        x_value = _safe_float(row.get(x_field))
        if x_value is not None and use_elapsed_seconds:
            x_value = x_value / SECONDS_PER_DAY
        value = _safe_float(row.get("value"))
        if not component or x_value is None or value is None:
            continue
        component_groups.setdefault(component, []).append((x_value, value))
        time_index = _safe_float(row.get("time_index"))
        label = str(row.get("time_label", "")).strip()
        if time_index is not None and label:
            time_labels[int(time_index)] = label

    if not component_groups:
        return False

    outlet_points: list[tuple[float, float]] = []
    for row in rows:
        if str(row.get("simulation_id", "")) != simulation_id:
            continue
        if str(row.get("observable", "")) != "outlet_flux_series":
            continue
        if str(row.get("unit", "")) != "m3/s":
            continue
        x_value = _safe_float(row.get(x_field))
        if x_value is not None and use_elapsed_seconds:
            x_value = x_value / SECONDS_PER_DAY
        value = _safe_float(row.get("value"))
        if x_value is None or value is None:
            continue
        outlet_points.append((x_value, value))

    release_components = [
        component
        for component in (
            "comparable_outflow_total_m3_s",
            "drainage_total_m3_s",
            "surface_excess_total_m3_s",
        )
        if component in component_groups
    ]
    balance_components = [
        component
        for component in (
            "recharge_total_m3_s",
            "well_total_m3_s",
            "storage_change_total_m3_s",
            "closure_residual_m3_s",
        )
        if component in component_groups
    ]
    if not release_components and not balance_components and not outlet_points:
        return False

    figure, axes = plt.subplots(2, 1, figsize=(7.8, 6.8), sharex=True, squeeze=False)
    release_ax, balance_ax = np.asarray(axes, dtype=object).ravel()
    tick_positions: list[float] = []

    for component in release_components:
        ordered = sorted(component_groups[component], key=lambda item: item[0])
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        release_ax.step(
            x_values,
            y_values,
            where="post",
            linewidth=1.9,
            color=_budget_component_color(component),
            label=_budget_component_label(component),
        )
    if outlet_points:
        ordered = sorted(outlet_points, key=lambda item: item[0])
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        release_ax.step(
            x_values,
            y_values,
            where="post",
            linewidth=1.7,
            linestyle="--",
            color=_budget_component_color("outlet_flux_series"),
            label="Compared outlet flux",
        )
    release_ax.set_title("Release terms", fontsize=_PANEL_TITLE_FONT_SIZE, pad=5, loc="left")
    release_ax.set_ylabel("m3/s", fontsize=_LABEL_FONT_SIZE)
    release_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    release_ax.grid(True, alpha=0.18, linewidth=0.6)
    release_ax.axhline(0.0, color="#9ca3af", linewidth=0.8, alpha=0.8)
    release_handles, release_labels = release_ax.get_legend_handles_labels()
    if release_labels:
        legend = release_ax.legend(
            release_handles,
            release_labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 1.32),
            ncol=_legend_ncols(len(release_labels)),
            frameon=False,
            fontsize=_LEGEND_FONT_SIZE,
        )
        for line in legend.get_lines():
            line.set_linewidth(1.9)

    for component in balance_components:
        ordered = sorted(component_groups[component], key=lambda item: item[0])
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        linestyle = "--" if component == "closure_residual_m3_s" else "-"
        balance_ax.step(
            x_values,
            y_values,
            where="post",
            linewidth=1.8,
            linestyle=linestyle,
            color=_budget_component_color(component),
            label=_budget_component_label(component),
        )
    balance_ax.set_title("Inputs and storage", fontsize=_PANEL_TITLE_FONT_SIZE, pad=5, loc="left")
    balance_ax.set_ylabel("m3/s", fontsize=_LABEL_FONT_SIZE)
    balance_ax.set_xlabel(x_label, fontsize=_LABEL_FONT_SIZE)
    balance_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    balance_ax.grid(True, alpha=0.18, linewidth=0.6)
    balance_ax.axhline(0.0, color="#9ca3af", linewidth=0.8, alpha=0.8)
    balance_handles, balance_labels = balance_ax.get_legend_handles_labels()
    if balance_labels:
        legend = balance_ax.legend(
            balance_handles,
            balance_labels,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.2),
            ncol=_legend_ncols(len(balance_labels)),
            frameon=False,
            fontsize=_LEGEND_FONT_SIZE,
        )
        for line in legend.get_lines():
            line.set_linewidth(1.8)
    tick_labels = [time_labels[index] for index in sorted(time_labels)] if time_labels else None
    _apply_time_ticks(balance_ax, tick_positions=tick_positions, tick_labels=tick_labels)
    figure.suptitle(
        f"Budget diagnostics: {_display_simulation_label(simulation_id=simulation_id, simulation_label=simulation_label)}",
        fontsize=_TITLE_FONT_SIZE,
        y=0.98,
    )
    figure.subplots_adjust(left=0.11, right=0.98, top=0.85, bottom=0.18, hspace=0.36)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True
