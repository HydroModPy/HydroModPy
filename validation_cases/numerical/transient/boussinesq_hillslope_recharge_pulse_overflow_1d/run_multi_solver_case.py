"""CLI entrypoint for a multi-method Boussinesq overflow comparison."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from validation_cases.shared.cli import apply_output_root_override

from .diagnostics import SolverOverflowDiagnostics, build_hillslope_overflow_diagnostics
from .runtime_boussinesq import (
    DEFAULT_SOLVER,
    WINDOWS_SURFACE_CONTEXT_PRESET,
    run_boussinesq_hillslope_overflow_case,
)


DEFAULT_SOLVERS = ("boussinesq", "petsc_partition", "petsc")
SOLVER_COLORS = {
    "boussinesq": "#2ca02c",
    "scipy_sparse": "#9467bd",
    "petsc_partition": "#1f77b4",
    "petsc": "#d62728",
}
SNAPSHOT_DAYS = (0.0, 8.0, 20.0, 28.0, 40.0)
POINT_BANDS = (
    ("upper_slope", "Upper slope", 0.00, 1.0 / 3.0),
    ("mid_slope", "Mid slope", 1.0 / 3.0, 2.0 / 3.0),
    ("near_toe", "Near toe", 2.0 / 3.0, 1.0),
)


@dataclass(frozen=True, slots=True)
class TimedSolverDiagnostics:
    diagnostics: SolverOverflowDiagnostics
    wall_time_seconds: float


def _normalize_solver_names(raw_solvers: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not raw_solvers:
        return DEFAULT_SOLVERS
    normalized: list[str] = []
    for raw in raw_solvers:
        solver = str(raw).strip().lower()
        if not solver:
            continue
        if solver not in normalized:
            normalized.append(solver)
    if not normalized:
        return DEFAULT_SOLVERS
    if len(normalized) < 2:
        raise ValueError("At least two distinct solvers are required for a comparison.")
    return tuple(normalized)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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


def _align_recharge_series_to_elapsed(
    recharge_mm_day: np.ndarray,
    elapsed_days: np.ndarray,
) -> np.ndarray:
    recharge = np.asarray(recharge_mm_day, dtype=float).reshape(-1)
    elapsed = np.asarray(elapsed_days, dtype=float).reshape(-1)
    if recharge.size == elapsed.size:
        return recharge
    if recharge.size == max(0, elapsed.size - 1):
        if recharge.size == 0:
            return np.zeros_like(elapsed, dtype=float)
        return np.concatenate(([float(recharge[0])], recharge))
    raise ValueError(
        "Recharge chronology length does not match elapsed days "
        f"({recharge.size} vs {elapsed.size})."
    )


def _build_timeseries_rows(results: list[TimedSolverDiagnostics]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in results:
        diagnostics = item.diagnostics
        recharge_mm_day = _align_recharge_series_to_elapsed(
            diagnostics.recharge_mm_day,
            diagnostics.elapsed_days,
        )
        total_outflow = np.asarray(diagnostics.total_outflow_m3_day, dtype=float)
        recharge_flux = np.asarray(diagnostics.recharge_flux_m3_day, dtype=float)
        net_inflow = np.asarray(
            getattr(diagnostics, "net_inflow_m3_day", recharge_flux - total_outflow),
            dtype=float,
        )
        storage_change = np.asarray(
            getattr(
                diagnostics,
                "storage_change_m3_day",
                getattr(diagnostics, "storage_balance_m3_day", net_inflow),
            ),
            dtype=float,
        )
        residual = np.asarray(
            getattr(diagnostics, "residual_m3_day", net_inflow - storage_change),
            dtype=float,
        )
        for idx, day in enumerate(diagnostics.elapsed_days.tolist()):
            rows.append(
                {
                    "solver": diagnostics.solver_name,
                    "solver_label": diagnostics.solver_label,
                    "runtime_backend": diagnostics.runtime_backend,
                    "surface_interaction_model": diagnostics.surface_interaction_model,
                    "elapsed_days": float(day),
                    "recharge_mm_day": float(recharge_mm_day[idx]),
                    "recharge_flux_m3_day": float(recharge_flux[idx]),
                    "surface_excess_flux_m3_day": float(
                        diagnostics.surface_excess_flux_m3_day[idx]
                    ),
                    "east_boundary_outflow_m3_day": float(
                        diagnostics.east_boundary_outflow_m3_day[idx]
                    ),
                    "total_outflow_m3_day": float(total_outflow[idx]),
                    "net_inflow_m3_day": float(net_inflow[idx]),
                    "storage_change_m3_day": float(storage_change[idx]),
                    "residual_m3_day": float(residual[idx]),
                    "total_overflow_m3_day": float(diagnostics.total_overflow_m3_day[idx]),
                    "active_overflow_length_m": float(diagnostics.active_overflow_length_m[idx]),
                    "overflow_front_x_m": float(diagnostics.overflow_front_x_m[idx]),
                    "overflow_centroid_x_m": float(diagnostics.overflow_centroid_x_m[idx]),
                    "max_head_clearance_m": float(np.max(diagnostics.mean_head_clearance_m[idx])),
                }
            )
    return rows


def _build_execution_rows(results: list[TimedSolverDiagnostics]) -> list[dict[str, Any]]:
    return [
        {
            "solver": item.diagnostics.solver_name,
            "solver_label": item.diagnostics.solver_label,
            "runtime_backend": item.diagnostics.runtime_backend,
            "surface_interaction_model": item.diagnostics.surface_interaction_model,
            "wall_time_seconds": item.wall_time_seconds,
            "results_dir": str(item.diagnostics.result.out_path),
        }
        for item in results
    ]


def _write_total_overflow_overlay_figure(
    results: list[TimedSolverDiagnostics],
    output_png: Path,
    *,
    dpi: int,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    fig, ax = plt.subplots(figsize=(10.2, 4.8), constrained_layout=True)

    for item in results:
        diagnostics = item.diagnostics
        ax.plot(
            diagnostics.elapsed_days,
            diagnostics.total_overflow_m3_day,
            color=SOLVER_COLORS.get(diagnostics.solver_name, "#444444"),
            linewidth=2.2,
            label=diagnostics.solver_label,
        )
    ax.set_xlabel("Time [day]")
    ax.set_ylabel("Total Overflow [m3/day]")
    ax.set_title("Total Surface-Overflow Overlay", fontsize=10.8)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.legend(loc="upper left", fontsize=8.8, frameon=False)
    fig.savefig(output_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _write_total_outflow_overlay_figure(
    results: list[TimedSolverDiagnostics],
    output_png: Path,
    *,
    dpi: int,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    fig, ax = plt.subplots(figsize=(10.2, 4.8), constrained_layout=True)

    for item in results:
        diagnostics = item.diagnostics
        ax.plot(
            diagnostics.elapsed_days,
            diagnostics.total_outflow_m3_day,
            color=SOLVER_COLORS.get(diagnostics.solver_name, "#444444"),
            linewidth=2.2,
            label=diagnostics.solver_label,
        )
    ax.set_xlabel("Time [day]")
    ax.set_ylabel("Total Outflow [m3/day]")
    ax.set_title("Total Outflow Overlay", fontsize=10.8)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.legend(loc="upper left", fontsize=8.8, frameon=False)
    fig.savefig(output_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _solver_plot_style(solver_name: str) -> dict[str, Any]:
    return {
        "color": SOLVER_COLORS.get(solver_name, "#444444"),
        "linewidth": 2.2,
        "zorder": 3,
    }


def _select_snapshot_indices(
    elapsed_days: np.ndarray, snapshot_days: tuple[float, ...]
) -> list[int]:
    times = np.asarray(elapsed_days, dtype=float).reshape(-1)
    selected: list[int] = []
    for day in snapshot_days:
        idx = int(np.argmin(np.abs(times - float(day))))
        if idx not in selected:
            selected.append(idx)
    return sorted(selected)


def _select_informative_points(
    results: list[TimedSolverDiagnostics],
) -> list[tuple[str, str, float]]:
    x = np.asarray(results[0].diagnostics.x_m, dtype=float)
    amplitude_by_solver = np.vstack(
        [
            np.ptp(np.asarray(item.diagnostics.mean_head_profiles_m, dtype=float), axis=0)
            for item in results
        ]
    )
    combined_amplitude = np.mean(amplitude_by_solver, axis=0)
    selected: list[tuple[str, str, float]] = []
    for point_id, point_label, left_frac, right_frac in POINT_BANDS:
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


def _write_head_snapshots_figure(
    results: list[TimedSolverDiagnostics],
    output_png: Path,
    *,
    dpi: int,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = list(results)
    snapshot_idx = _select_snapshot_indices(ordered[0].diagnostics.elapsed_days, SNAPSHOT_DAYS)
    colors = plt.cm.cividis(np.linspace(0.12, 0.88, len(snapshot_idx)))

    fig, axes = plt.subplots(
        len(ordered), 1, figsize=(10.8, 8.8), sharex=True, constrained_layout=True
    )
    if len(ordered) == 1:
        axes = [axes]
    for ax, item in zip(axes, ordered, strict=False):
        diagnostics = item.diagnostics
        ax.plot(
            diagnostics.x_m,
            diagnostics.topography_profile_m,
            color="#222222",
            linewidth=1.8,
            linestyle="--",
            label="Topography",
        )
        for color, idx in zip(colors, snapshot_idx, strict=False):
            ax.plot(
                diagnostics.x_m,
                diagnostics.mean_head_profiles_m[idx],
                color=color,
                linewidth=1.9,
                label=f"t={diagnostics.elapsed_days[idx]:.0f} d",
            )
        ax.set_ylabel("Head [m]")
        ax.set_title(diagnostics.solver_label, fontsize=10.5)
        ax.grid(alpha=0.25, linewidth=0.6)
    axes[0].legend(loc="upper right", fontsize=8.8, frameon=False, ncols=3)
    axes[-1].set_xlabel("x [m]")
    fig.suptitle("Boussinesq methods: head profiles at selected times", fontsize=11.0)
    fig.savefig(output_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _write_flux_figure(
    results: list[TimedSolverDiagnostics],
    output_png: Path,
    *,
    dpi: int,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = list(results)
    fig, axes = plt.subplots(2, 1, figsize=(10.6, 7.8), sharex=True, constrained_layout=True)

    elapsed_days = ordered[0].diagnostics.elapsed_days
    recharge = np.asarray(ordered[0].diagnostics.recharge_mm_day, dtype=float)
    axes[0].step(
        elapsed_days,
        recharge,
        where="mid",
        color="#444444",
        linewidth=2.0,
    )
    axes[0].set_ylabel("Recharge [mm/day]")
    axes[0].grid(alpha=0.25, linewidth=0.6)

    for item in ordered:
        diagnostics = item.diagnostics
        axes[1].plot(
            diagnostics.elapsed_days,
            diagnostics.total_outflow_m3_day,
            label=f"{diagnostics.solver_label} total outflow",
            **_solver_plot_style(diagnostics.solver_name),
        )
    axes[1].set_xlabel("Time [days]")
    axes[1].set_ylabel("Flux [m3/day]")
    axes[1].grid(alpha=0.25, linewidth=0.6)
    axes[1].legend(loc="upper left", fontsize=8.8, frameon=False)

    fig.suptitle("Recharge and total outflow", fontsize=11.0)
    fig.savefig(output_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _write_outflow_components_figure(
    results: list[TimedSolverDiagnostics],
    output_png: Path,
    *,
    dpi: int,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = list(results)
    fig, axes = plt.subplots(
        len(ordered), 1, figsize=(11.0, 8.8), sharex=True, constrained_layout=True
    )
    if len(ordered) == 1:
        axes = [axes]
    for ax, item in zip(axes, ordered, strict=False):
        diagnostics = item.diagnostics
        ax.plot(
            diagnostics.elapsed_days,
            diagnostics.total_outflow_m3_day,
            color="#111111",
            linewidth=2.2,
            label="Total outflow",
        )
        ax.plot(
            diagnostics.elapsed_days,
            diagnostics.east_boundary_outflow_m3_day,
            color="#7f7f7f",
            linewidth=1.8,
            linestyle="-.",
            label="East boundary",
        )
        ax.plot(
            diagnostics.elapsed_days,
            diagnostics.surface_excess_flux_m3_day,
            color=SOLVER_COLORS.get(diagnostics.solver_name, "#444444"),
            linewidth=2.0,
            label="Surface excess",
        )
        ax.set_ylabel("Flux [m3/day]")
        ax.set_title(diagnostics.solver_label, fontsize=10.5)
        ax.grid(alpha=0.25, linewidth=0.6)
    axes[0].legend(loc="upper left", fontsize=8.8, frameon=False, ncols=3)
    axes[-1].set_xlabel("Time [days]")
    fig.suptitle("Outflow components by Boussinesq method", fontsize=11.0)
    fig.savefig(output_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _write_flux_budget_figure(
    results: list[TimedSolverDiagnostics],
    output_png: Path,
    *,
    dpi: int,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = list(results)

    fig, axes = plt.subplots(4, 2, figsize=(12.8, 11.8), sharex=True, constrained_layout=True)
    flat_axes = list(np.asarray(axes).reshape(-1))

    recharge_ax = flat_axes[0]
    recharge_ax.step(
        ordered[0].diagnostics.elapsed_days,
        ordered[0].diagnostics.recharge_flux_m3_day,
        where="mid",
        color="#222222",
        linewidth=2.0,
    )
    recharge_ax.set_title("Recharge Input", fontsize=10.2)
    recharge_ax.set_ylabel("Flux [m3/day]")
    recharge_ax.grid(alpha=0.25, linewidth=0.6)

    panel_specs: list[tuple[Any, str]] = [
        (lambda item: item.diagnostics.net_inflow_m3_day, "Net Inflow"),
        (lambda item: item.diagnostics.storage_change_m3_day, "Storage Change"),
        (lambda item: item.diagnostics.residual_m3_day, "Residual"),
        (lambda item: item.diagnostics.east_boundary_outflow_m3_day, "East Boundary Outflow"),
        (lambda item: item.diagnostics.surface_excess_flux_m3_day, "Surface Excess Outflow"),
        (lambda item: item.diagnostics.total_outflow_m3_day, "Total Outflow"),
        (lambda item: item.diagnostics.total_overflow_m3_day, "Total Overflow"),
    ]

    for ax, (series_getter, title) in zip(flat_axes[1:], panel_specs, strict=False):
        for item in ordered:
            diagnostics = item.diagnostics
            ax.plot(
                diagnostics.elapsed_days,
                np.asarray(series_getter(item), dtype=float),
                label=diagnostics.solver_label,
                **_solver_plot_style(diagnostics.solver_name),
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
    fig.savefig(output_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _write_head_point_figure(
    results: list[TimedSolverDiagnostics],
    output_png: Path,
    *,
    dpi: int,
) -> list[dict[str, Any]]:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = list(results)
    point_specs = _select_informative_points(ordered)
    fig, axes = plt.subplots(4, 1, figsize=(11.0, 10.4), sharex=True, constrained_layout=True)

    recharge = np.asarray(ordered[0].diagnostics.recharge_mm_day, dtype=float)
    elapsed_days = ordered[0].diagnostics.elapsed_days
    axes[0].step(
        elapsed_days,
        recharge,
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
            diagnostics = item.diagnostics
            idx = int(np.argmin(np.abs(diagnostics.x_m - float(target_x_m))))
            x_value = float(diagnostics.x_m[idx])
            head_series = np.asarray(diagnostics.mean_head_profiles_m[:, idx], dtype=float)
            clearance_series = np.asarray(diagnostics.mean_head_clearance_m[:, idx], dtype=float)
            ax.plot(
                diagnostics.elapsed_days,
                head_series,
                label=diagnostics.solver_label,
                **_solver_plot_style(diagnostics.solver_name),
            )
            for t_day, head_m, clearance_m in zip(
                diagnostics.elapsed_days,
                head_series,
                clearance_series,
                strict=False,
            ):
                rows.append(
                    {
                        "point_id": point_id,
                        "point_label": point_label,
                        "x_m": x_value,
                        "solver": diagnostics.solver_name,
                        "solver_label": diagnostics.solver_label,
                        "elapsed_days": float(t_day),
                        "head_m": float(head_m),
                        "clearance_m": float(clearance_m),
                    }
                )
            if topo_value_m is None:
                topo_value_m = float(diagnostics.topography_profile_m[idx])
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
    fig.suptitle("Head time series at selected hillslope points", fontsize=11.0)
    fig.savefig(output_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return rows


def _build_summary_rows(results: list[TimedSolverDiagnostics]) -> list[dict[str, Any]]:
    return [
        {
            "solver": item.diagnostics.solver_name,
            "solver_label": item.diagnostics.solver_label,
            "runtime_backend": item.diagnostics.runtime_backend,
            "surface_interaction_model": item.diagnostics.surface_interaction_model,
            "onset_day": item.diagnostics.onset_day,
            "peak_total_overflow_m3_day": item.diagnostics.peak_total_overflow_m3_day,
            "peak_overflow_day": item.diagnostics.peak_overflow_day,
            "peak_active_length_m": item.diagnostics.peak_active_length_m,
            "max_head_clearance_m": item.diagnostics.max_head_clearance_m,
            "wall_time_seconds": item.wall_time_seconds,
            "results_dir": str(item.diagnostics.result.out_path),
            "postprocess_dir": str(item.diagnostics.result.postprocess_dir),
        }
        for item in results
    ]


def _write_execution_times_figure(
    results: list[TimedSolverDiagnostics],
    output_png: Path,
    *,
    dpi: int,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    labels = [item.diagnostics.solver_label for item in results]
    values = [float(item.wall_time_seconds) for item in results]
    colors = [SOLVER_COLORS.get(item.diagnostics.solver_name, "#444444") for item in results]
    ypos = np.arange(len(results), dtype=float)

    fig, ax = plt.subplots(figsize=(8.6, 3.8), constrained_layout=True)
    bars = ax.barh(ypos, values, color=colors, edgecolor="#222222", linewidth=0.6)
    ax.set_yticks(ypos, labels)
    ax.set_xlabel("Wall Time [s]")
    ax.set_title("Execution Time Comparison", fontsize=10.8)
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)

    max_value = max(values) if values else 0.0
    for bar, value in zip(bars, values, strict=False):
        ax.text(
            float(bar.get_width()) + max(0.05, max_value * 0.015),
            float(bar.get_y()) + float(bar.get_height()) * 0.5,
            f"{value:.2f} s",
            va="center",
            ha="left",
            fontsize=8.8,
        )

    fig.savefig(output_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _write_summary(
    output_md: Path,
    *,
    results: list[TimedSolverDiagnostics],
    figures_dir: Path,
    args: argparse.Namespace,
) -> None:
    lines = [
        "# Multi-Solver Boussinesq Overflow Comparison",
        "",
        "This report compares multiple Boussinesq surface-interaction formulations on the same transient hillslope overflow case.",
        "",
        f"- solvers: `{[item.diagnostics.solver_name for item in results]}`",
        f"- forcing preset: `{args.forcing_preset}`",
        f"- forcing scale: `{float(args.forcing_scale):.3f}`",
        f"- dt_days override: `{args.dt_days}`",
        f"- east_head override: `{args.east_head}`",
        f"- initial_head override: `{args.initial_head}`",
        "",
        "| Solver | Backend | Surface law | Onset day [d] | Peak total overflow [m3/day] | Peak day [d] | Max h-z [m] | Wall time [s] | Results dir |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in results:
        diagnostics = item.diagnostics
        lines.append(
            f"| {diagnostics.solver_label} | {diagnostics.runtime_backend} | {diagnostics.surface_interaction_model} | "
            f"{diagnostics.onset_day:.2f} | {diagnostics.peak_total_overflow_m3_day:.3f} | {diagnostics.peak_overflow_day:.2f} | "
            f"{diagnostics.max_head_clearance_m:.4f} | {item.wall_time_seconds:.2f} | `{diagnostics.result.out_path}` |"
        )
        lines.extend(
            [
                "",
                f"Head snapshots: `{figures_dir / 'head_snapshots.png'}`",
                f"Head point time series: `{figures_dir / 'head_point_timeseries.png'}`",
                f"Flux chronicle: `{figures_dir / 'flux_timeseries.png'}`",
                f"Total outflow overlay: `{figures_dir / 'total_outflow_overlay.png'}`",
                f"Total overflow overlay: `{figures_dir / 'total_overflow_overlay.png'}`",
                f"Outflow components: `{figures_dir / 'outflow_components.png'}`",
                f"Complete flux budget: `{figures_dir / 'flux_budget_comparison.png'}`",
                f"Execution times: `{figures_dir / 'execution_times.png'}`",
                "",
            ]
        )
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines), encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the transient hillslope overflow case for several Boussinesq "
            "solver variants and generate a total-overflow overlay."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("out") / "boussinesq_hillslope_overflow_multi_20260413",
        help=(
            "Root directory used for validation outputs and the multi-solver "
            "report. On Linux/WSL, use /mnt/c/... if the output must remain "
            "visible from Windows."
        ),
    )
    parser.add_argument(
        "--solvers",
        nargs="+",
        default=list(DEFAULT_SOLVERS),
        help=("Solver variants to compare. Defaults to: " + ", ".join(DEFAULT_SOLVERS)),
    )
    parser.add_argument(
        "--context-preset",
        type=str,
        default=None,
        help=(
            "Optional shared geometry/forcing preset. Supported values: "
            f"{WINDOWS_SURFACE_CONTEXT_PRESET}."
        ),
    )
    parser.add_argument("--forcing-preset", type=str, default="strong")
    parser.add_argument("--forcing-scale", type=float, default=1.0)
    parser.add_argument("--east-head", type=float, default=None)
    parser.add_argument("--initial-head", type=float, default=None)
    parser.add_argument("--dt-days", type=float, default=None)
    parser.add_argument("--runtime-max-iterations", type=int, default=None)
    parser.add_argument("--runtime-tol-residual-inf", type=float, default=None)
    parser.add_argument("--overflow-threshold-mm-day", type=float, default=None)
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--timeout", type=int, default=2400)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    solver_names = _normalize_solver_names(args.solvers)

    output_root = Path(args.output_root).expanduser().resolve()
    apply_output_root_override(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    os.environ["HYDROMODPY_OUT_PATH"] = str(output_root)

    results: list[TimedSolverDiagnostics] = []
    for solver_name in solver_names:
        t0 = time.perf_counter()
        run_result = run_boussinesq_hillslope_overflow_case(
            caller_file=Path(__file__),
            timeout=int(args.timeout),
            solver=solver_name,
            context_preset=args.context_preset,
            forcing_preset=args.forcing_preset,
            forcing_scale=float(args.forcing_scale),
            east_head_m=args.east_head,
            initial_head_m=args.initial_head,
            dt_days=args.dt_days,
            runtime_max_iterations=args.runtime_max_iterations,
            runtime_tol_residual_inf=args.runtime_tol_residual_inf,
        )
        wall_time_seconds = time.perf_counter() - t0
        diagnostics = build_hillslope_overflow_diagnostics(
            result=run_result,
            overflow_threshold_mm_day=args.overflow_threshold_mm_day,
        )
        results.append(
            TimedSolverDiagnostics(
                diagnostics=diagnostics,
                wall_time_seconds=wall_time_seconds,
            )
        )

    figures_dir = output_root / "figures"
    _write_total_overflow_overlay_figure(
        results,
        figures_dir / "total_overflow_overlay.png",
        dpi=int(args.dpi),
    )
    _write_total_outflow_overlay_figure(
        results,
        figures_dir / "total_outflow_overlay.png",
        dpi=int(args.dpi),
    )
    _write_head_snapshots_figure(
        results,
        figures_dir / "head_snapshots.png",
        dpi=int(args.dpi),
    )
    head_point_rows = _write_head_point_figure(
        results,
        figures_dir / "head_point_timeseries.png",
        dpi=int(args.dpi),
    )
    _write_flux_figure(
        results,
        figures_dir / "flux_timeseries.png",
        dpi=int(args.dpi),
    )
    _write_outflow_components_figure(
        results,
        figures_dir / "outflow_components.png",
        dpi=int(args.dpi),
    )
    _write_flux_budget_figure(
        results,
        figures_dir / "flux_budget_comparison.png",
        dpi=int(args.dpi),
    )
    _write_execution_times_figure(
        results,
        figures_dir / "execution_times.png",
        dpi=int(args.dpi),
    )
    _write_csv(output_root / "timeseries.csv", _build_timeseries_rows(results))
    _write_csv(output_root / "execution_times.csv", _build_execution_rows(results))
    _write_csv(output_root / "summary_metrics.csv", _build_summary_rows(results))
    _write_csv(output_root / "head_point_timeseries.csv", head_point_rows)
    _write_summary(
        output_root / "summary.md",
        results=results,
        figures_dir=figures_dir,
        args=args,
    )
    (output_root / "summary.json").write_text(
        json.dumps(
            {
                "output_root": str(output_root),
                "timeseries_csv": str(output_root / "timeseries.csv"),
                "head_point_timeseries_csv": str(output_root / "head_point_timeseries.csv"),
                "summary_metrics_csv": str(output_root / "summary_metrics.csv"),
                "execution_times_csv": str(output_root / "execution_times.csv"),
                "head_snapshots_png": str(figures_dir / "head_snapshots.png"),
                "head_point_timeseries_png": str(figures_dir / "head_point_timeseries.png"),
                "flux_timeseries_png": str(figures_dir / "flux_timeseries.png"),
                "total_outflow_overlay_png": str(figures_dir / "total_outflow_overlay.png"),
                "total_overflow_overlay_png": str(figures_dir / "total_overflow_overlay.png"),
                "outflow_components_png": str(figures_dir / "outflow_components.png"),
                "flux_budget_comparison_png": str(figures_dir / "flux_budget_comparison.png"),
                "execution_times_png": str(figures_dir / "execution_times.png"),
                "solver_names": list(solver_names),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Output root: {output_root}")
    print(f"Saved figure: {figures_dir / 'total_overflow_overlay.png'}")
    print(f"Saved execution times: {figures_dir / 'execution_times.png'}")
    for item in results:
        diagnostics = item.diagnostics
        print(
            f"{diagnostics.solver_label}: onset={diagnostics.onset_day:.2f} d, "
            f"peak_qs={diagnostics.peak_total_overflow_m3_day:.3f} m3/day, "
            f"max_h_minus_top={diagnostics.max_head_clearance_m:.4f} m, "
            f"wall_time={item.wall_time_seconds:.2f} s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
