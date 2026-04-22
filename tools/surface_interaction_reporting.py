"""Shared reporting helpers for transient surface-interaction comparisons."""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

StyleFn = Callable[[str], dict[str, Any]]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_head_snapshots(
    results: list[Any],
    output_png: Path,
    *,
    solver_order: tuple[str, ...],
    solver_labels: dict[str, str],
    snapshot_days: tuple[float, ...],
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: solver_order.index(item.solver))
    elapsed_days = np.asarray(ordered[0].elapsed_days, dtype=float)
    snapshot_idx = sorted(
        {int(np.argmin(np.abs(elapsed_days - float(day)))) for day in snapshot_days}
    )
    colors = plt.cm.cividis(np.linspace(0.12, 0.88, len(snapshot_idx)))
    fig, axes = plt.subplots(
        len(ordered), 1, figsize=(10.8, 8.8), sharex=True, constrained_layout=True
    )
    if len(ordered) == 1:
        axes = [axes]
    for ax, item in zip(axes, ordered, strict=False):
        ax.plot(
            item.x,
            item.topography_profile,
            color="#222222",
            linewidth=1.8,
            linestyle="--",
            label="Topography",
        )
        for color, idx in zip(colors, snapshot_idx, strict=False):
            ax.plot(
                item.x,
                item.head_profiles[idx],
                color=color,
                linewidth=1.9,
                label=f"t={item.elapsed_days[idx]:.0f} d",
            )
        ax.set_ylabel("Head [m]")
        ax.set_title(solver_labels[item.solver], fontsize=10.5)
        ax.grid(alpha=0.25, linewidth=0.6)
    axes[0].legend(loc="upper right", fontsize=8.8, frameon=False, ncols=3)
    axes[-1].set_xlabel("x [m]")
    fig.suptitle("Recharge ramp then dry recovery: head profiles at selected times", fontsize=11.0)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_flux_figure(
    results: list[Any],
    output_png: Path,
    *,
    solver_order: tuple[str, ...],
    solver_labels: dict[str, str],
    recharge_series_mm_day: tuple[float, ...],
    style_fn: StyleFn,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: solver_order.index(item.solver))
    fig, axes = plt.subplots(2, 1, figsize=(10.6, 7.8), sharex=True, constrained_layout=True)
    axes[0].step(
        ordered[0].elapsed_days,
        np.asarray(recharge_series_mm_day, dtype=float),
        where="mid",
        color="#444444",
        linewidth=2.0,
    )
    axes[0].set_ylabel("Recharge [mm/day]")
    axes[0].grid(alpha=0.25, linewidth=0.6)
    for item in ordered:
        axes[1].plot(
            item.elapsed_days,
            item.total_outflow_m3_day,
            label=f"{solver_labels[item.solver]} total outflow",
            **style_fn(item.solver),
        )
    axes[1].set_xlabel("Time [days]")
    axes[1].set_ylabel("Flux [m3/day]")
    axes[1].grid(alpha=0.25, linewidth=0.6)
    axes[1].legend(loc="upper left", fontsize=8.8, frameon=False)
    fig.suptitle("Recharge ramp then dry recovery: recharge and total outflow", fontsize=11.0)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_total_outflow_overlay_figure(
    results: list[Any],
    output_png: Path,
    *,
    solver_order: tuple[str, ...],
    solver_labels: dict[str, str],
    style_fn: StyleFn,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: solver_order.index(item.solver))
    fig, ax = plt.subplots(figsize=(10.4, 4.8), constrained_layout=True)
    for item in ordered:
        ax.plot(
            item.elapsed_days,
            item.total_outflow_m3_day,
            label=solver_labels[item.solver],
            **style_fn(item.solver),
        )
    ax.set_xlabel("Time [days]")
    ax.set_ylabel("Total Outflow [m3/day]")
    ax.set_title("Total Outflow Overlay", fontsize=10.8)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.legend(loc="upper left", fontsize=8.8, frameon=False, ncols=3)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_outflow_components_figure(
    results: list[Any],
    output_png: Path,
    *,
    solver_order: tuple[str, ...],
    solver_labels: dict[str, str],
    solver_colors: dict[str, str],
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: solver_order.index(item.solver))
    fig, axes = plt.subplots(
        len(ordered), 1, figsize=(11.0, 8.8), sharex=True, constrained_layout=True
    )
    if len(ordered) == 1:
        axes = [axes]
    for ax, item in zip(axes, ordered, strict=False):
        ax.plot(
            item.elapsed_days,
            item.total_outflow_m3_day,
            color="#111111",
            linewidth=2.2,
            label="Total outflow",
        )
        ax.plot(
            item.elapsed_days,
            item.east_boundary_outflow_m3_day,
            color="#7f7f7f",
            linewidth=1.8,
            linestyle="-.",
            label="East boundary",
        )
        ax.plot(
            item.elapsed_days,
            item.drainage_flux_m3_day,
            color=solver_colors[item.solver],
            linewidth=2.0,
            label="Drainage",
        )
        if item.bouss_surface_flux_m3_day is not None:
            ax.plot(
                item.elapsed_days,
                item.bouss_surface_flux_m3_day,
                color="#d62728",
                linewidth=1.8,
                linestyle="--",
                label="Surface excess",
            )
        ax.set_ylabel("Flux [m3/day]")
        ax.set_title(solver_labels[item.solver], fontsize=10.5)
        ax.grid(alpha=0.25, linewidth=0.6)
    axes[0].legend(loc="upper left", fontsize=8.8, frameon=False, ncols=4)
    axes[-1].set_xlabel("Time [days]")
    fig.suptitle("Outflow components by solver", fontsize=11.0)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_flux_budget_figure(
    results: list[Any],
    output_png: Path,
    *,
    solver_order: tuple[str, ...],
    solver_labels: dict[str, str],
    style_fn: StyleFn,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: solver_order.index(item.solver))
    elapsed_days = ordered[0].elapsed_days
    fig, axes = plt.subplots(4, 2, figsize=(12.8, 11.8), sharex=True, constrained_layout=True)
    flat_axes = list(np.asarray(axes).reshape(-1))
    flat_axes[0].step(
        elapsed_days, ordered[0].total_inflow_m3_day, where="mid", color="#222222", linewidth=2.0
    )
    flat_axes[0].step(
        elapsed_days,
        ordered[0].recharge_flux_m3_day,
        where="mid",
        color="#777777",
        linewidth=1.4,
        linestyle="--",
    )
    flat_axes[0].set_title("Total Inflow", fontsize=10.2)
    flat_axes[0].set_ylabel("Flux [m3/day]")
    flat_axes[0].grid(alpha=0.25, linewidth=0.6)
    panel_specs: list[tuple[Any, str]] = [
        (lambda item: item.net_inflow_m3_day, "Net Inflow"),
        (lambda item: item.storage_change_m3_day, "Storage Change"),
        (lambda item: item.residual_m3_day, "Residual"),
        (lambda item: item.east_boundary_inflow_m3_day, "East Boundary Inflow"),
        (lambda item: item.drainage_flux_m3_day, "Drainage Outflow"),
        (lambda item: item.east_boundary_outflow_m3_day, "East Boundary Outflow"),
        (
            lambda item: (
                np.zeros_like(item.elapsed_days, dtype=float)
                if item.bouss_surface_flux_m3_day is None
                else np.asarray(item.bouss_surface_flux_m3_day, dtype=float)
            ),
            "Surface Excess Outflow",
        ),
        (lambda item: item.total_outflow_m3_day, "Total Outflow"),
    ]
    for ax, (series_getter, title) in zip(flat_axes[1:], panel_specs, strict=False):
        for item in ordered:
            ax.plot(
                item.elapsed_days,
                np.asarray(series_getter(item), dtype=float),
                label=solver_labels[item.solver],
                **style_fn(item.solver),
            )
        if title in {"Net Inflow", "Residual"}:
            ax.axhline(0.0, color="#444444", linewidth=1.0, linestyle="--")
        ax.set_title(title, fontsize=10.2)
        ax.set_ylabel("Flux [m3/day]")
        ax.grid(alpha=0.25, linewidth=0.6)
    flat_axes[1].legend(loc="upper right", fontsize=8.4, frameon=False)
    flat_axes[-2].set_xlabel("Time [days]")
    flat_axes[-1].set_xlabel("Time [days]")
    fig.suptitle("Complete Flux Budget Comparison", fontsize=11.0)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_execution_times_figure(
    results: list[Any],
    output_png: Path,
    *,
    solver_order: tuple[str, ...],
    solver_labels: dict[str, str],
    solver_colors: dict[str, str],
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: solver_order.index(item.solver))
    labels = [solver_labels[item.solver] for item in ordered]
    values = [
        float(item.wall_time_seconds) if item.wall_time_seconds is not None else float("nan")
        for item in ordered
    ]
    colors = [solver_colors[item.solver] for item in ordered]
    ypos = np.arange(len(ordered), dtype=float)
    fig, ax = plt.subplots(figsize=(8.4, 3.8), constrained_layout=True)
    bars = ax.barh(ypos, values, color=colors, edgecolor="#222222", linewidth=0.6)
    ax.set_yticks(ypos, labels)
    ax.set_xlabel("Wall Time [s]")
    ax.set_title("Execution Time Comparison", fontsize=10.8)
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)
    finite_values = [value for value in values if np.isfinite(value)]
    offset = (max(finite_values) * 0.015) if finite_values else 0.0
    for bar, value in zip(bars, values, strict=False):
        if not np.isfinite(value):
            continue
        ax.text(
            float(bar.get_width()) + offset,
            float(bar.get_y()) + float(bar.get_height()) * 0.5,
            f"{value:.2f} s",
            va="center",
            ha="left",
            fontsize=8.8,
        )
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _select_informative_points(
    results: list[Any],
    *,
    solver_order: tuple[str, ...],
    point_bands: tuple[tuple[str, str, float, float], ...],
) -> list[tuple[str, str, float]]:
    ordered = sorted(results, key=lambda item: solver_order.index(item.solver))
    x = np.asarray(ordered[0].x, dtype=float)
    amplitude_by_solver = np.vstack(
        [np.ptp(np.asarray(item.head_profiles, dtype=float), axis=0) for item in ordered]
    )
    combined_amplitude = np.mean(amplitude_by_solver, axis=0)
    selected: list[tuple[str, str, float]] = []
    for point_id, point_label, left_frac, right_frac in point_bands:
        left_x = float(x[0]) + left_frac * float(x[-1] - x[0])
        right_x = float(x[0]) + right_frac * float(x[-1] - x[0])
        mask = (x >= left_x) & (x <= right_x)
        if not np.any(mask):
            idx = int(np.argmax(combined_amplitude))
        else:
            local_indices = np.flatnonzero(mask)
            idx = int(local_indices[int(np.argmax(combined_amplitude[mask]))])
        selected.append((point_id, point_label, float(x[idx])))
    return selected


def write_head_point_figure(
    results: list[Any],
    output_png: Path,
    *,
    solver_order: tuple[str, ...],
    solver_labels: dict[str, str],
    recharge_series_mm_day: tuple[float, ...],
    point_bands: tuple[tuple[str, str, float, float], ...],
    style_fn: StyleFn,
) -> list[dict[str, Any]]:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: solver_order.index(item.solver))
    point_specs = _select_informative_points(
        ordered, solver_order=solver_order, point_bands=point_bands
    )
    fig, axes = plt.subplots(4, 1, figsize=(11.0, 10.4), sharex=True, constrained_layout=True)
    axes[0].step(
        ordered[0].elapsed_days,
        np.asarray(recharge_series_mm_day, dtype=float),
        where="mid",
        color="#444444",
        linewidth=2.0,
    )
    axes[0].set_ylabel("Recharge\n[mm/day]")
    axes[0].grid(alpha=0.25, linewidth=0.6)
    rows: list[dict[str, Any]] = []
    for ax, (point_id, point_label, target_x_m) in zip(axes[1:], point_specs, strict=False):
        topo_value_m: float | None = None
        for item in ordered:
            idx = int(np.argmin(np.abs(item.x - float(target_x_m))))
            x_value = float(item.x[idx])
            head_series = np.asarray(item.head_profiles[:, idx], dtype=float)
            clearance_series = np.asarray(item.clearance_profiles[:, idx], dtype=float)
            ax.plot(
                item.elapsed_days,
                head_series,
                label=solver_labels[item.solver],
                **style_fn(item.solver),
            )
            for t_day, head_m, clearance_m in zip(
                item.elapsed_days, head_series, clearance_series, strict=False
            ):
                rows.append(
                    {
                        "point_id": point_id,
                        "point_label": point_label,
                        "x_m": x_value,
                        "solver": item.solver,
                        "solver_label": solver_labels[item.solver],
                        "elapsed_days": float(t_day),
                        "head_m": float(head_m),
                        "clearance_m": float(clearance_m),
                    }
                )
            if topo_value_m is None:
                topo_value_m = float(item.topography_profile[idx])
        if topo_value_m is not None:
            ax.axhline(
                topo_value_m,
                color="#222222",
                linewidth=1.2,
                linestyle="--",
                label="Topography" if point_id == point_specs[0][0] else None,
            )
        ax.set_ylabel("Head [m]")
        ax.set_title(f"{point_label} (x ~ {target_x_m:.0f} m)", fontsize=10.0)
        ax.grid(alpha=0.25, linewidth=0.6)
    axes[1].legend(loc="upper left", fontsize=8.8, frameon=False, ncols=4)
    axes[-1].set_xlabel("Time [days]")
    fig.suptitle(
        "Recharge ramp then dry recovery: head time series at selected hillslope points",
        fontsize=11.0,
    )
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return rows


def write_markdown_summary(
    results: list[Any],
    output_md: Path,
    figures_dir: Path,
    *,
    solver_order: tuple[str, ...],
    solver_labels: dict[str, str],
    recharge_series_mm_day: tuple[float, ...],
    hydraulic_conductivity_scale: float,
    topography_base_elevation_m: float,
    drainage_conductance_m2_s: float,
    dt_days: float,
) -> None:
    ordered = sorted(results, key=lambda item: solver_order.index(item.solver))
    lines = [
        "# Transient Hillslope Surface-Interaction Investigation",
        "",
        "West no-flow, east fixed head, annual recharge ramp followed by one dry year, and top drainage.",
        "",
        f"- hydraulic conductivity scale: `{hydraulic_conductivity_scale:.3f}x`",
        f"- topography base elevation at right boundary: `{topography_base_elevation_m:.3f} m`",
        f"- drainage conductance: `{drainage_conductance_m2_s:.3g} m2/s`",
        f"- time step: `{dt_days:.1f} day`",
        f"- recharge series [mm/day]: `{list(recharge_series_mm_day)}`",
        "- forcing shape: increase during first half-year, decrease during second half-year, then one additional year with zero recharge.",
        "",
        "| Solver | Onset day [d] | Peak drainage flux [m3/day] | Peak drainage day [d] | Max clearance [m] | Wall time [s] | Results dir |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in ordered:
        wall_time_text = (
            "n/a" if item.wall_time_seconds is None else f"{item.wall_time_seconds:.2f}"
        )
        lines.append(
            f"| {solver_labels[item.solver]} | {item.onset_day:.1f} | {item.peak_drainage_flux_m3_day:.4f} | {item.peak_drainage_day:.1f} | {item.max_clearance_m:.4f} | {wall_time_text} | `{item.out_path}` |"
        )
    lines.extend(
        [
            "",
            f"Head snapshots: `{figures_dir / 'head_snapshots.png'}`",
            f"Head point time series: `{figures_dir / 'head_point_timeseries.png'}`",
            f"Flux chronicle: `{figures_dir / 'flux_timeseries.png'}`",
            f"Total outflow overlay: `{figures_dir / 'total_outflow_overlay.png'}`",
            f"Outflow components: `{figures_dir / 'outflow_components.png'}`",
            f"Complete flux budget: `{figures_dir / 'flux_budget_comparison.png'}`",
            f"Execution times: `{figures_dir / 'execution_times.png'}`",
            "",
        ]
    )
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines), encoding="utf-8")
