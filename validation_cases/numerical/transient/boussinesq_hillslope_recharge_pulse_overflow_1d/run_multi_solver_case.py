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
from .runtime_boussinesq import DEFAULT_SOLVER, run_boussinesq_hillslope_overflow_case


DEFAULT_SOLVERS = ("boussinesq", "petsc_partition", "petsc")
SOLVER_COLORS = {
    "boussinesq": "#2ca02c",
    "scipy_sparse": "#9467bd",
    "petsc_partition": "#1f77b4",
    "petsc": "#d62728",
}


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
        for idx, day in enumerate(diagnostics.elapsed_days.tolist()):
            rows.append(
                {
                    "solver": diagnostics.solver_name,
                    "solver_label": diagnostics.solver_label,
                    "runtime_backend": diagnostics.runtime_backend,
                    "surface_interaction_model": diagnostics.surface_interaction_model,
                    "elapsed_days": float(day),
                    "recharge_mm_day": float(recharge_mm_day[idx]),
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
            f"Total overflow overlay: `{figures_dir / 'total_overflow_overlay.png'}`",
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
        help=(
            "Solver variants to compare. Defaults to: "
            + ", ".join(DEFAULT_SOLVERS)
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
    _write_execution_times_figure(
        results,
        figures_dir / "execution_times.png",
        dpi=int(args.dpi),
    )
    _write_csv(output_root / "timeseries.csv", _build_timeseries_rows(results))
    _write_csv(output_root / "execution_times.csv", _build_execution_rows(results))
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
                "execution_times_csv": str(output_root / "execution_times.csv"),
                "total_overflow_overlay_png": str(figures_dir / "total_overflow_overlay.png"),
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
