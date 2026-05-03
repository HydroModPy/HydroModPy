"""Timeseries renderers for comparison visuals."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
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
    _display_variant_label,
    _legend_ncols,
    _pretty_label,
    _safe_float,
    _series_style,
    _solver_color,
)

_SECONDS_PER_DAY = 86_400.0

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _surface_reference_lines(
    rows: Iterable[Mapping[str, Any]],
) -> list[tuple[str, str, float]]:
    """Return stable surface-elevation reference lines for point plots."""
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        top = _safe_float(row.get("surface_top_m"))
        if top is None:
            continue
        key = (
            str(row.get("variant_id", "")),
            str(row.get("variant_label", row.get("variant_id", ""))),
        )
        grouped.setdefault(key, []).append(top)

    lines: list[tuple[str, str, float]] = []
    for (variant_id, variant_label), values in sorted(grouped.items()):
        finite = [value for value in values if math.isfinite(value)]
        if finite:
            lines.append((variant_id, variant_label, float(np.nanmedian(finite))))
    if len(lines) <= 1:
        return lines

    top_values = np.asarray([line[2] for line in lines], dtype=float)
    if np.nanmax(top_values) - np.nanmin(top_values) <= 0.05:
        return [("surface", "Surface", float(np.nanmean(top_values)))]
    return lines


def _plot_surface_reference_lines(ax: Any, rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    for variant_id, variant_label, top in _surface_reference_lines(rows):
        if variant_id == "surface":
            color = "#111827"
            label = "Surface"
        else:
            color = _solver_color(variant_id)
            label = "Surface " + _display_variant_label(
                variant_id=variant_id, variant_label=variant_label
            )
        ax.axhline(
            top,
            color=color,
            linestyle=(0, (5, 3)),
            linewidth=1.15,
            alpha=0.72,
            label=label,
            zorder=1,
        )
        count += 1
    return count


def _write_timeseries_figure(
    *,
    path: Path,
    observable_name: str,
    unit: str,
    grouped_rows: list[dict[str, Any]],
) -> bool:
    use_elapsed_seconds = all(
        _safe_float(row.get("elapsed_seconds")) is not None for row in grouped_rows
    )
    x_label = "Elapsed time [d]" if use_elapsed_seconds else "Time index"

    series_payloads: dict[tuple[str, str, int], list[tuple[float, float]]] = {}
    for row in grouped_rows:
        value = _safe_float(row.get("value"))
        if value is None:
            continue
        x_value = (
            _safe_float(row.get("elapsed_seconds"))
            if use_elapsed_seconds
            else _safe_float(row.get("time_index"))
        )
        if x_value is None:
            continue
        if use_elapsed_seconds:
            x_value = x_value / _SECONDS_PER_DAY
        key = (
            str(row.get("variant_id", "")),
            str(row.get("variant_label", row.get("variant_id", ""))),
            int(row.get("value_index", 0)),
        )
        series_payloads.setdefault(key, []).append((x_value, value))

    if not any(len(points) >= 2 for points in series_payloads.values()):
        return False

    figure, ax = plt.subplots(1, 1, figsize=(7.0, 4.1))
    tick_positions: list[float] = []
    for (variant_id, variant_label, value_index), points in sorted(series_payloads.items()):
        ordered = sorted(points, key=lambda item: item[0])
        if len(ordered) < 2:
            continue
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        label = _display_variant_label(
            variant_id=variant_id,
            variant_label=variant_label or variant_id,
        )
        if any(
            other_value_index != value_index and other_variant_id == variant_id
            for (other_variant_id, _, other_value_index) in series_payloads
        ):
            label = f"{label} [{value_index}]"
        style = _series_style(observable_name)
        ax.plot(x_values, y_values, label=label, **style)

    if not ax.lines:
        plt.close(figure)
        return False
    _plot_surface_reference_lines(ax, grouped_rows)
    ax.set_xlabel(x_label, fontsize=_LABEL_FONT_SIZE)
    ax.set_ylabel(unit or "value", fontsize=_LABEL_FONT_SIZE)
    ax.set_title(_pretty_label(observable_name), fontsize=_TITLE_FONT_SIZE, pad=8)
    ax.tick_params(labelsize=_TICK_FONT_SIZE)
    ax.grid(True, alpha=0.18, linewidth=0.6)
    ax.margins(x=0.03, y=0.08)
    if not use_elapsed_seconds:
        _apply_time_ticks(ax, tick_positions=tick_positions)
    legend = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.21),
        ncol=_legend_ncols(len(ax.lines)),
        frameon=False,
        fontsize=_LEGEND_FONT_SIZE,
        handlelength=1.8,
        columnspacing=1.1,
        borderaxespad=0.0,
    )
    for line in legend.get_lines():
        line.set_linewidth(1.8)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.86, bottom=0.29)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_runtime_bar_figure(
    *,
    path: Path,
    execution_rows: list[Mapping[str, Any]],
    reference_variant: str | None,
) -> bool:
    rows = [row for row in execution_rows if _safe_float(row.get("runtime_seconds")) is not None]
    if len(rows) < 2:
        return False
    ordered = sorted(rows, key=lambda item: float(item["runtime_seconds"]), reverse=True)
    labels = [
        _display_variant_label(
            variant_id=str(row.get("variant_id", "")),
            variant_label=str(row.get("variant_label", row.get("variant_id", ""))),
        )
        for row in ordered
    ]
    runtimes = [float(row["runtime_seconds"]) for row in ordered]
    colors = [_solver_color(str(row.get("solver", ""))) for row in ordered]

    figure_height = max(2.8, 0.72 * len(ordered) + 1.1)
    figure, ax = plt.subplots(1, 1, figsize=(7.4, figure_height))
    positions = np.arange(len(ordered))
    bars = ax.barh(positions, runtimes, color=colors, edgecolor="none", height=0.58)
    ax.set_yticks(positions, labels=labels, fontsize=_LABEL_FONT_SIZE)
    ax.set_xlabel("Runtime [s]", fontsize=_LABEL_FONT_SIZE)
    ax.tick_params(axis="x", labelsize=_TICK_FONT_SIZE)
    ax.grid(axis="x", alpha=0.22, linewidth=0.6)
    ax.set_title("Execution time comparison", fontsize=_TITLE_FONT_SIZE, pad=8)

    reference_runtime = None
    if reference_variant is not None:
        for row in ordered:
            if str(row.get("variant_id", "")) == reference_variant:
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


def _write_point_dashboard(
    *,
    path: Path,
    rows: list[dict[str, Any]],
) -> bool:
    point_rows = [row for row in rows if str(row.get("support", "")) == "point"]
    observables = sorted(
        {str(row.get("observable", "")) for row in point_rows if row.get("observable")}
    )
    if len(observables) < 2:
        return False

    grouped: dict[str, dict[tuple[str, str], list[tuple[float, float]]]] = {}
    for row in point_rows:
        observable_name = str(row.get("observable", ""))
        value = _safe_float(row.get("value"))
        x_value = _safe_float(row.get("time_index"))
        if not observable_name or value is None or x_value is None:
            continue
        key = (
            str(row.get("variant_id", "")),
            str(row.get("variant_label", row.get("variant_id", ""))),
        )
        grouped.setdefault(observable_name, {}).setdefault(key, []).append((x_value, value))

    plotted_observables = [
        name
        for name in observables
        if any(len(points) >= 2 for points in grouped.get(name, {}).values())
    ]
    if len(plotted_observables) < 2:
        return False

    figure, axes = plt.subplots(
        len(plotted_observables),
        1,
        figsize=(7.6, max(5.0, 2.25 * len(plotted_observables) + 0.7)),
        sharex=True,
        squeeze=False,
    )
    axes_flat = np.asarray(axes, dtype=object).ravel()
    tick_positions: list[float] = []
    for index, observable_name in enumerate(plotted_observables):
        ax = axes_flat[index]
        observable_rows = [
            row for row in point_rows if str(row.get("observable", "")) == observable_name
        ]
        for (variant_id, variant_label), points in sorted(grouped.get(observable_name, {}).items()):
            ordered = sorted(points, key=lambda item: item[0])
            if len(ordered) < 2:
                continue
            x_values = [item[0] for item in ordered]
            y_values = [item[1] for item in ordered]
            tick_positions.extend(x_values)
            style = _series_style(observable_name)
            ax.plot(
                x_values,
                y_values,
                color=_solver_color(variant_id),
                label=_display_variant_label(variant_id=variant_id, variant_label=variant_label),
                **style,
            )
        _plot_surface_reference_lines(ax, observable_rows)
        ax.set_title(
            _pretty_label(observable_name), fontsize=_PANEL_TITLE_FONT_SIZE, pad=5, loc="left"
        )
        unit = next(
            (
                str(row.get("unit", ""))
                for row in point_rows
                if str(row.get("observable", "")) == observable_name
                and str(row.get("unit", "")) != ""
            ),
            "m",
        )
        ax.set_ylabel(unit, fontsize=_LABEL_FONT_SIZE)
        ax.tick_params(labelsize=_TICK_FONT_SIZE)
        ax.grid(True, alpha=0.18, linewidth=0.6)
        ax.margins(x=0.02, y=0.08)
        if index == 0 and ax.lines:
            legend = ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, 1.34),
                ncol=_legend_ncols(len(ax.lines)),
                frameon=False,
                fontsize=_LEGEND_FONT_SIZE,
                handlelength=2.0,
                columnspacing=1.2,
            )
            for line in legend.get_lines():
                line.set_linewidth(1.8)

    axes_flat[-1].set_xlabel("Time step", fontsize=_LABEL_FONT_SIZE)
    _apply_time_ticks(axes_flat[-1], tick_positions=tick_positions)
    figure.suptitle("Head chronicle comparison", fontsize=_TITLE_FONT_SIZE, y=0.985)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.86, bottom=0.13, hspace=0.34)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_native_flux_panel(
    *,
    path: Path,
    variable: str,
    long_rows: list[Mapping[str, Any]],
    delta_rows: list[Mapping[str, Any]],
) -> bool:
    flux_rows = [row for row in long_rows if str(row.get("variable", "")) == variable]
    variant_keys = {
        str(row.get("variant_id", "")) for row in flux_rows if str(row.get("variant_id", "")) != ""
    }
    if len(variant_keys) < 2:
        return False

    series_payloads: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for row in flux_rows:
        value = _safe_float(row.get("value"))
        x_value = _safe_float(row.get("time_index"))
        if value is None or x_value is None:
            continue
        key = (
            str(row.get("variant_id", "")),
            str(row.get("variant_label", row.get("variant_id", ""))),
        )
        series_payloads.setdefault(key, []).append((int(x_value), value))
    if not any(len(points) >= 2 for points in series_payloads.values()):
        return False

    relevant_delta = [
        row
        for row in delta_rows
        if str(row.get("variable", "")) == variable
        and _safe_float(row.get("signed_error")) is not None
        and _safe_float(row.get("time_index")) is not None
    ]

    figure, axes = plt.subplots(2, 1, figsize=(7.5, 6.2), sharex=True)
    main_ax, delta_ax = axes
    tick_positions: list[float] = []
    tick_labels: list[str] = []
    for (variant_id, variant_label), points in sorted(series_payloads.items()):
        ordered = sorted(points, key=lambda item: item[0])
        label = _display_variant_label(
            variant_id=variant_id,
            variant_label=variant_label,
        )
        color = _solver_color(variant_id)
        tick_positions.extend(float(item[0]) for item in ordered)
        main_ax.step(
            [item[0] for item in ordered],
            [item[1] for item in ordered],
            where="post",
            linewidth=1.8,
            label=label,
            color=color,
        )
    main_ax.set_ylabel(_pretty_label(variable), fontsize=_LABEL_FONT_SIZE)
    main_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    main_ax.grid(True, alpha=0.22, linewidth=0.6)
    legend = main_ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=_legend_ncols(len(series_payloads)),
        frameon=False,
        fontsize=_LEGEND_FONT_SIZE,
    )
    for line in legend.get_lines():
        line.set_linewidth(1.8)

    if relevant_delta:
        delta_groups: dict[str, list[tuple[int, float]]] = {}
        time_label_lookup: dict[int, str] = {}
        for row in relevant_delta:
            key = str(row.get("variant_id", ""))
            time_index = int(float(row["time_index"]))
            delta_groups.setdefault(key, []).append((time_index, float(row["signed_error"])))
            label = str(row.get("time_label", "")).strip()
            if label:
                time_label_lookup[time_index] = label
        for variant_id, points in sorted(delta_groups.items()):
            ordered = sorted(points, key=lambda item: item[0])
            delta_ax.step(
                [item[0] for item in ordered],
                [item[1] for item in ordered],
                where="post",
                linewidth=1.6,
                color=_solver_color(variant_id),
                label=_display_variant_label(variant_id=variant_id, variant_label=variant_id),
            )
        tick_labels = [
            time_label_lookup.get(int(value), str(int(value)))
            for value in sorted(time_label_lookup)
        ]
        delta_ax.axhline(0.0, color="#111827", linewidth=0.8, alpha=0.65)
    delta_ax.set_xlabel("Time step", fontsize=_LABEL_FONT_SIZE)
    delta_ax.set_ylabel("Delta vs ref", fontsize=_LABEL_FONT_SIZE)
    delta_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    delta_ax.grid(True, alpha=0.22, linewidth=0.6)
    _apply_time_ticks(
        delta_ax,
        tick_positions=tick_positions,
        tick_labels=(tick_labels if tick_labels else None),
    )

    figure.suptitle(f"{_pretty_label(variable)} hydrograph", fontsize=_TITLE_FONT_SIZE, y=0.97)
    figure.subplots_adjust(left=0.12, right=0.98, top=0.9, bottom=0.18, hspace=0.25)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_flux_dashboard(
    *,
    path: Path,
    rows: list[dict[str, Any]],
    native_long_rows: list[Mapping[str, Any]],
) -> bool:
    panels: list[
        tuple[str, dict[tuple[str, str], list[tuple[float, float]]], list[str] | None]
    ] = []

    outlet_rows = [row for row in rows if str(row.get("observable", "")) == "outlet_flux_series"]
    if outlet_rows:
        grouped: dict[tuple[str, str], list[tuple[float, float]]] = {}
        for row in outlet_rows:
            value = _safe_float(row.get("value"))
            x_value = _safe_float(row.get("time_index"))
            if value is None or x_value is None:
                continue
            key = (
                str(row.get("variant_id", "")),
                str(row.get("variant_label", row.get("variant_id", ""))),
            )
            grouped.setdefault(key, []).append((x_value, value))
        if any(len(points) >= 2 for points in grouped.values()):
            panels.append(("Outlet flux [m3/s]", grouped, None))

    for variable in ("accumulation_flux", "outflow_drain"):
        grouped_native: dict[tuple[str, str], list[tuple[float, float]]] = {}
        time_labels: dict[int, str] = {}
        for row in native_long_rows:
            if str(row.get("variable", "")) != variable:
                continue
            value = _safe_float(row.get("value"))
            x_value = _safe_float(row.get("time_index"))
            if value is None or x_value is None:
                continue
            key = (
                str(row.get("variant_id", "")),
                str(row.get("variant_label", row.get("variant_id", ""))),
            )
            grouped_native.setdefault(key, []).append((x_value, value))
            label = str(row.get("time_label", "")).strip()
            if label:
                time_labels[int(x_value)] = label
        if any(len(points) >= 2 for points in grouped_native.values()):
            labels = [time_labels[index] for index in sorted(time_labels)] if time_labels else None
            panels.append((_pretty_label(variable), grouped_native, labels))

    if len(panels) < 2:
        return False

    figure, axes = plt.subplots(
        len(panels),
        1,
        figsize=(7.6, max(5.6, 2.15 * len(panels) + 0.7)),
        sharex=True,
        squeeze=False,
    )
    axes_flat = np.asarray(axes, dtype=object).ravel()
    tick_positions: list[float] = []
    tick_labels: list[str] | None = None
    for index, (panel_title, grouped, labels) in enumerate(panels):
        ax = axes_flat[index]
        for (variant_id, variant_label), points in sorted(grouped.items()):
            ordered = sorted(points, key=lambda item: item[0])
            if len(ordered) < 2:
                continue
            x_values = [item[0] for item in ordered]
            y_values = [item[1] for item in ordered]
            tick_positions.extend(x_values)
            if labels:
                tick_labels = labels
            ax.step(
                x_values,
                y_values,
                where="post",
                linewidth=1.8,
                color=_solver_color(variant_id),
                label=_display_variant_label(variant_id=variant_id, variant_label=variant_label),
            )
        ax.set_title(panel_title, fontsize=_PANEL_TITLE_FONT_SIZE, pad=5, loc="left")
        ax.tick_params(labelsize=_TICK_FONT_SIZE)
        ax.grid(True, alpha=0.18, linewidth=0.6)
        ax.margins(x=0.02, y=0.08)
        if index == 0 and ax.lines:
            legend = ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, 1.34),
                ncol=_legend_ncols(len(ax.lines)),
                frameon=False,
                fontsize=_LEGEND_FONT_SIZE,
                handlelength=2.0,
                columnspacing=1.2,
            )
            for line in legend.get_lines():
                line.set_linewidth(1.8)

    axes_flat[-1].set_xlabel("Time step", fontsize=_LABEL_FONT_SIZE)
    _apply_time_ticks(axes_flat[-1], tick_positions=tick_positions, tick_labels=tick_labels)
    figure.suptitle("Flux overview", fontsize=_TITLE_FONT_SIZE, y=0.985)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.86, bottom=0.13, hspace=0.34)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_budget_diagnostic_figure(
    *,
    path: Path,
    variant_id: str,
    variant_label: str,
    budget_rows: list[Mapping[str, Any]],
    rows: list[dict[str, Any]],
) -> bool:
    variant_budget_rows = [
        row for row in budget_rows if str(row.get("variant_id", "")) == variant_id
    ]
    if not variant_budget_rows:
        return False

    use_elapsed_seconds = all(
        _safe_float(row.get("elapsed_seconds")) is not None for row in variant_budget_rows
    )
    x_field = "elapsed_seconds" if use_elapsed_seconds else "time_index"
    x_label = "Elapsed time [d]" if use_elapsed_seconds else "Time step"

    component_groups: dict[str, list[tuple[float, float]]] = {}
    time_labels: dict[int, str] = {}
    for row in variant_budget_rows:
        component = str(row.get("component", "")).strip()
        x_value = _safe_float(row.get(x_field))
        if x_value is not None and use_elapsed_seconds:
            x_value = x_value / _SECONDS_PER_DAY
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
        if str(row.get("variant_id", "")) != variant_id:
            continue
        if str(row.get("observable", "")) != "outlet_flux_series":
            continue
        if str(row.get("unit", "")) != "m3/s":
            continue
        x_value = _safe_float(row.get(x_field))
        if x_value is not None and use_elapsed_seconds:
            x_value = x_value / _SECONDS_PER_DAY
        value = _safe_float(row.get("value"))
        if x_value is None or value is None:
            continue
        outlet_points.append((x_value, value))

    release_components = [
        component
        for component in (
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
        f"Budget diagnostics: {_display_variant_label(variant_id=variant_id, variant_label=variant_label)}",
        fontsize=_TITLE_FONT_SIZE,
        y=0.98,
    )
    figure.subplots_adjust(left=0.11, right=0.98, top=0.85, bottom=0.18, hspace=0.36)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True
