"""Timeseries and dashboard renderers."""

from __future__ import annotations

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
    _budget_component_label,
    _display_simulation_label,
    _legend_ncols,
    _pretty_label,
    _safe_float,
    _series_style,
    _solver_color,
)
from hydromodpy.core.units.time import SECONDS_PER_DAY

from .aggregation import (
    _plot_surface_reference_lines,
    _row_time_value,
    _rows_have_elapsed_seconds,
    _time_axis_label,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _write_timeseries_figure(
    *,
    path: Path,
    observable_name: str,
    unit: str,
    grouped_rows: list[dict[str, Any]],
    point_label: str = "",
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
            x_value = x_value / SECONDS_PER_DAY
        key = (
            str(row.get("simulation_id", "")),
            str(row.get("simulation_label", row.get("simulation_id", ""))),
            int(row.get("value_index", 0)),
        )
        series_payloads.setdefault(key, []).append((x_value, value))

    if not any(len(points) >= 2 for points in series_payloads.values()):
        return False

    figure, ax = plt.subplots(1, 1, figsize=(7.0, 4.1))
    tick_positions: list[float] = []
    for (simulation_id, simulation_label, value_index), points in sorted(series_payloads.items()):
        ordered = sorted(points, key=lambda item: item[0])
        if len(ordered) < 2:
            continue
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        label = _display_simulation_label(
            simulation_id=simulation_id,
            simulation_label=simulation_label or simulation_id,
        )
        if any(
            other_value_index != value_index and other_simulation_id == simulation_id
            for (other_simulation_id, _, other_value_index) in series_payloads
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
    title = _pretty_label(observable_name)
    if point_label:
        title = f"Point {point_label} - {title}"
    ax.set_title(title, fontsize=_TITLE_FONT_SIZE, pad=8)
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

    use_elapsed_seconds = _rows_have_elapsed_seconds(point_rows)
    grouped: dict[str, dict[tuple[str, str], list[tuple[float, float]]]] = {}
    for row in point_rows:
        observable_name = str(row.get("observable", ""))
        value = _safe_float(row.get("value"))
        x_value = _row_time_value(row, use_elapsed_seconds=use_elapsed_seconds)
        if not observable_name or value is None or x_value is None:
            continue
        key = (
            str(row.get("simulation_id", "")),
            str(row.get("simulation_label", row.get("simulation_id", ""))),
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
        for (simulation_id, simulation_label), points in sorted(
            grouped.get(observable_name, {}).items()
        ):
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
                color=_solver_color(simulation_id),
                label=_display_simulation_label(
                    simulation_id=simulation_id, simulation_label=simulation_label
                ),
                **style,
            )
        _plot_surface_reference_lines(ax, observable_rows)
        ax.set_title(
            _pretty_label(observable_name),
            fontsize=_PANEL_TITLE_FONT_SIZE,
            pad=5,
            loc="left",
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

    axes_flat[-1].set_xlabel(
        _time_axis_label(use_elapsed_seconds=use_elapsed_seconds),
        fontsize=_LABEL_FONT_SIZE,
    )
    if not use_elapsed_seconds:
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
    simulation_keys = {
        str(row.get("simulation_id", ""))
        for row in flux_rows
        if str(row.get("simulation_id", "")) != ""
    }
    if len(simulation_keys) < 2:
        return False

    use_elapsed_seconds = _rows_have_elapsed_seconds(flux_rows)
    series_payloads: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for row in flux_rows:
        value = _safe_float(row.get("value"))
        x_value = _row_time_value(row, use_elapsed_seconds=use_elapsed_seconds)
        if value is None or x_value is None:
            continue
        key = (
            str(row.get("simulation_id", "")),
            str(row.get("simulation_label", row.get("simulation_id", ""))),
        )
        series_payloads.setdefault(key, []).append((int(x_value), value))
    if not any(len(points) >= 2 for points in series_payloads.values()):
        return False

    relevant_delta = [
        row
        for row in delta_rows
        if str(row.get("variable", "")) == variable
        and _safe_float(row.get("signed_error")) is not None
        and _row_time_value(row, use_elapsed_seconds=use_elapsed_seconds) is not None
    ]

    figure, axes = plt.subplots(2, 1, figsize=(7.5, 6.2), sharex=True)
    main_ax, delta_ax = axes
    tick_positions: list[float] = []
    tick_labels: list[str] = []
    for (simulation_id, simulation_label), points in sorted(series_payloads.items()):
        ordered = sorted(points, key=lambda item: item[0])
        label = _display_simulation_label(
            simulation_id=simulation_id,
            simulation_label=simulation_label,
        )
        color = _solver_color(simulation_id)
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
        delta_groups: dict[str, list[tuple[float, float]]] = {}
        time_label_lookup: dict[int, str] = {}
        for row in relevant_delta:
            key = str(row.get("simulation_id", ""))
            time_value = _row_time_value(row, use_elapsed_seconds=use_elapsed_seconds)
            if time_value is None:
                continue
            delta_groups.setdefault(key, []).append((time_value, float(row["signed_error"])))
            label = str(row.get("time_label", "")).strip()
            if label and not use_elapsed_seconds:
                time_label_lookup[int(time_value)] = label
        for simulation_id, points in sorted(delta_groups.items()):
            ordered = sorted(points, key=lambda item: item[0])
            delta_ax.step(
                [item[0] for item in ordered],
                [item[1] for item in ordered],
                where="post",
                linewidth=1.6,
                color=_solver_color(simulation_id),
                label=_display_simulation_label(
                    simulation_id=simulation_id, simulation_label=simulation_id
                ),
            )
        tick_labels = [
            time_label_lookup.get(int(value), str(int(value)))
            for value in sorted(time_label_lookup)
        ]
        delta_ax.axhline(0.0, color="#111827", linewidth=0.8, alpha=0.65)
    delta_ax.set_xlabel(
        _time_axis_label(use_elapsed_seconds=use_elapsed_seconds),
        fontsize=_LABEL_FONT_SIZE,
    )
    delta_ax.set_ylabel("Delta vs ref", fontsize=_LABEL_FONT_SIZE)
    delta_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    delta_ax.grid(True, alpha=0.22, linewidth=0.6)
    if not use_elapsed_seconds:
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
    native_flux_rows = [
        row
        for row in native_long_rows
        if str(row.get("variable", "")) in {"accumulation_flux", "outflow_drain"}
    ]
    use_elapsed_seconds = _rows_have_elapsed_seconds(outlet_rows + native_flux_rows)
    if outlet_rows:
        grouped: dict[tuple[str, str], list[tuple[float, float]]] = {}
        for row in outlet_rows:
            value = _safe_float(row.get("value"))
            x_value = _row_time_value(row, use_elapsed_seconds=use_elapsed_seconds)
            if value is None or x_value is None:
                continue
            key = (
                str(row.get("simulation_id", "")),
                str(row.get("simulation_label", row.get("simulation_id", ""))),
            )
            grouped.setdefault(key, []).append((x_value, value))
        if any(len(points) >= 2 for points in grouped.values()):
            panels.append(("Outlet flux [m3/s]", grouped, None))

    for variable in ("accumulation_flux", "outflow_drain"):
        grouped_native: dict[tuple[str, str], list[tuple[float, float]]] = {}
        time_labels: dict[int, str] = {}
        for row in native_flux_rows:
            if str(row.get("variable", "")) != variable:
                continue
            value = _safe_float(row.get("value"))
            x_value = _row_time_value(row, use_elapsed_seconds=use_elapsed_seconds)
            if value is None or x_value is None:
                continue
            key = (
                str(row.get("simulation_id", "")),
                str(row.get("simulation_label", row.get("simulation_id", ""))),
            )
            grouped_native.setdefault(key, []).append((x_value, value))
            label = str(row.get("time_label", "")).strip()
            if label and not use_elapsed_seconds:
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
        for (simulation_id, simulation_label), points in sorted(grouped.items()):
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
                color=_solver_color(simulation_id),
                label=_display_simulation_label(
                    simulation_id=simulation_id, simulation_label=simulation_label
                ),
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

    axes_flat[-1].set_xlabel(
        _time_axis_label(use_elapsed_seconds=use_elapsed_seconds),
        fontsize=_LABEL_FONT_SIZE,
    )
    if not use_elapsed_seconds:
        _apply_time_ticks(axes_flat[-1], tick_positions=tick_positions, tick_labels=tick_labels)
    figure.suptitle("Flux overview", fontsize=_TITLE_FONT_SIZE, y=0.985)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.86, bottom=0.13, hspace=0.34)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_comparable_outflow_dashboard(
    *,
    path: Path,
    budget_rows: list[Mapping[str, Any]],
    rows: list[dict[str, Any]],
) -> bool:
    """Write the solver-comparable release comparison dashboard."""
    comparable_rows = [
        row
        for row in budget_rows
        if str(row.get("component", "")) == "comparable_outflow_total_m3_s"
    ]
    if not comparable_rows:
        return False

    use_elapsed_seconds = all(
        _safe_float(row.get("elapsed_seconds")) is not None for row in comparable_rows
    )
    x_field = "elapsed_seconds" if use_elapsed_seconds else "time_index"
    x_label = _time_axis_label(use_elapsed_seconds=use_elapsed_seconds)

    grouped_total: dict[tuple[str, str], list[tuple[float, float]]] = {}
    grouped_components: dict[tuple[str, str, str], list[tuple[float, float]]] = {}
    time_labels: dict[int, str] = {}

    for row in budget_rows:
        component = str(row.get("component", ""))
        if component not in {
            "comparable_outflow_total_m3_s",
            "drainage_total_m3_s",
            "surface_excess_total_m3_s",
        }:
            continue
        x_value = _safe_float(row.get(x_field))
        if x_value is not None and use_elapsed_seconds:
            x_value = x_value / SECONDS_PER_DAY
        value = _safe_float(row.get("value"))
        if x_value is None or value is None:
            continue
        simulation_id = str(row.get("simulation_id", ""))
        simulation_label = str(row.get("simulation_label", simulation_id))
        if component == "comparable_outflow_total_m3_s":
            grouped_total.setdefault((simulation_id, simulation_label), []).append((x_value, value))
        else:
            grouped_components.setdefault((simulation_id, simulation_label, component), []).append(
                (x_value, value)
            )
        time_index = _safe_float(row.get("time_index"))
        label = str(row.get("time_label", "")).strip()
        if time_index is not None and label:
            time_labels[int(time_index)] = label

    if not any(len(points) >= 2 for points in grouped_total.values()):
        return False

    outlet_points_by_sim: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for row in rows:
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
        simulation_id = str(row.get("simulation_id", ""))
        simulation_label = str(row.get("simulation_label", simulation_id))
        outlet_points_by_sim.setdefault((simulation_id, simulation_label), []).append(
            (x_value, value)
        )

    figure, axes = plt.subplots(2, 1, figsize=(8.1, 6.6), sharex=True, squeeze=False)
    total_ax, component_ax = np.asarray(axes, dtype=object).ravel()
    tick_positions: list[float] = []

    for (simulation_id, simulation_label), points in sorted(grouped_total.items()):
        ordered = sorted(points, key=lambda item: item[0])
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        tick_positions.extend(x_values)
        total_ax.step(
            x_values,
            y_values,
            where="post",
            linewidth=2.0,
            color=_solver_color(simulation_id),
            label=_display_simulation_label(
                simulation_id=simulation_id,
                simulation_label=simulation_label,
            ),
        )
    for (simulation_id, simulation_label), points in sorted(outlet_points_by_sim.items()):
        ordered = sorted(points, key=lambda item: item[0])
        if len(ordered) < 2:
            continue
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        total_ax.step(
            x_values,
            y_values,
            where="post",
            linewidth=1.2,
            linestyle=":",
            color=_solver_color(simulation_id),
            alpha=0.85,
            label=(
                "Outlet "
                + _display_simulation_label(
                    simulation_id=simulation_id,
                    simulation_label=simulation_label,
                )
            ),
        )
    total_ax.set_title(
        "Comparable outflow = drainage + surface excess",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=5,
        loc="left",
    )
    total_ax.set_ylabel("m3/s", fontsize=_LABEL_FONT_SIZE)
    total_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    total_ax.grid(True, alpha=0.18, linewidth=0.6)
    total_ax.axhline(0.0, color="#9ca3af", linewidth=0.8, alpha=0.8)
    handles, labels = total_ax.get_legend_handles_labels()
    if labels:
        legend = total_ax.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 1.34),
            ncol=_legend_ncols(len(labels)),
            frameon=False,
            fontsize=_LEGEND_FONT_SIZE,
        )
        for line in legend.get_lines():
            line.set_linewidth(1.8)

    for (simulation_id, simulation_label, component), points in sorted(grouped_components.items()):
        ordered = sorted(points, key=lambda item: item[0])
        if len(ordered) < 2:
            continue
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        linestyle = "-" if component == "drainage_total_m3_s" else "--"
        component_ax.step(
            x_values,
            y_values,
            where="post",
            linewidth=1.55,
            linestyle=linestyle,
            color=_solver_color(simulation_id),
            alpha=0.88,
            label=(
                _display_simulation_label(
                    simulation_id=simulation_id,
                    simulation_label=simulation_label,
                )
                + " - "
                + _budget_component_label(component)
            ),
        )
    component_ax.set_title(
        "Native components kept visible",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=5,
        loc="left",
    )
    component_ax.set_ylabel("m3/s", fontsize=_LABEL_FONT_SIZE)
    component_ax.set_xlabel(x_label, fontsize=_LABEL_FONT_SIZE)
    component_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    component_ax.grid(True, alpha=0.18, linewidth=0.6)
    component_ax.axhline(0.0, color="#9ca3af", linewidth=0.8, alpha=0.8)
    handles, labels = component_ax.get_legend_handles_labels()
    if labels:
        legend = component_ax.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.2),
            ncol=_legend_ncols(len(labels)),
            frameon=False,
            fontsize=_LEGEND_FONT_SIZE,
        )
        for line in legend.get_lines():
            line.set_linewidth(1.55)

    tick_labels = [time_labels[index] for index in sorted(time_labels)] if time_labels else None
    if not use_elapsed_seconds:
        _apply_time_ticks(component_ax, tick_positions=tick_positions, tick_labels=tick_labels)
    figure.suptitle("Comparable outflow diagnostics", fontsize=_TITLE_FONT_SIZE, y=0.98)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.84, bottom=0.2, hspace=0.38)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True
