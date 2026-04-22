"""Linux benchmark comparing MODFLOW-NWT with selected Boussinesq methods."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tools.investigate_surface_interaction_hillslope_transient as base
from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.diagnostics import (
    build_hillslope_overflow_diagnostics,
)
from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.runtime_boussinesq import (
    LINUX_NWT_BOUSS_RAMP_CONTEXT_PRESET,
    run_boussinesq_hillslope_overflow_case,
)
from validation_cases.shared import load_case_metadata

SOLVER_ORDER = ("modflownwt", "petsc_partition", "petsc")
SOLVER_LABELS = {
    "modflownwt": "MODFLOW-NWT",
    "petsc_partition": "Boussinesq PETSc partition",
    "petsc": "Boussinesq PETSc complementarity",
}
SOLVER_COLORS = {
    "modflownwt": "#1f77b4",
    "petsc_partition": "#9467bd",
    "petsc": "#d62728",
}
RECHARGE_SERIES_MM_DAY = (
    0.50,
    1.00,
    1.50,
    2.00,
    2.50,
    3.00,
    3.50,
    4.00,
    4.50,
    5.00,
    5.50,
    6.00,
    5.50,
    5.00,
    4.50,
    4.00,
    3.50,
    3.00,
    2.50,
    2.00,
    1.50,
    1.00,
    0.50,
    0.25,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
)
SNAPSHOT_DAYS = (10.0, 60.0, 120.0, 240.0, 330.0, 420.0)
OUTPUT_ROOT_DEFAULT = REPO_ROOT / "out" / "linux_nwt_bouss_4m4m6m_r005_dt2_refined_20260414"
BOUSS_RUNTIME_MAX_ITERATIONS = 400
BOUSS_RUNTIME_TOL_RESIDUAL_INF = 5.0e-6
PARTITION_REGULARIZATION_RADIUS = 0.005
HYDRAULIC_CONDUCTIVITY_SCALE = 0.1
DRAINAGE_CONDUCTANCE_M2_S = 2.0e-4
BOUSS_NX = 80
BOUSS_NY = 6
_ORIGINAL_COMPARISON_PLOT_STYLE = base._comparison_plot_style


def _linux_comparison_plot_style(solver: str) -> dict[str, Any]:
    if solver == "modflownwt":
        return {
            "color": SOLVER_COLORS[solver],
            "linewidth": 2.1,
            "linestyle": "-",
            "zorder": 5,
        }
    return _ORIGINAL_COMPARISON_PLOT_STYLE(solver)


def _configure_base_module() -> None:
    base.SOLVER_ORDER = SOLVER_ORDER
    base.SOLVER_LABELS = SOLVER_LABELS
    base.SOLVER_COLORS = SOLVER_COLORS
    base.RECHARGE_SERIES_MM_DAY = RECHARGE_SERIES_MM_DAY
    base.SNAPSHOT_DAYS = SNAPSHOT_DAYS
    base.DT_DAYS = 2.0
    base.HYDRAULIC_CONDUCTIVITY_SCALE = HYDRAULIC_CONDUCTIVITY_SCALE
    base.DRAINAGE_CONDUCTANCE_M2_S = DRAINAGE_CONDUCTANCE_M2_S
    base.BOUSS_NX = BOUSS_NX
    base.BOUSS_NY = BOUSS_NY
    base.EAST_HEAD_M = base.TOPOGRAPHY_BASE_ELEVATION_M + (
        base.TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M / (2.0 * BOUSS_NX)
    )
    base.INITIAL_HEAD_M = base.EAST_HEAD_M
    base._comparison_plot_style = _linux_comparison_plot_style


def _bouss_diagnostics_to_result(
    solver_name: str,
    *,
    diagnostics,
    wall_time_seconds: float,
) -> base.TransientResult:
    total_outflow = np.asarray(diagnostics.total_outflow_m3_day, dtype=float)
    east_boundary = np.asarray(diagnostics.east_boundary_outflow_m3_day, dtype=float)
    surface_excess = np.asarray(diagnostics.surface_excess_flux_m3_day, dtype=float)
    drainage_flux = np.asarray(diagnostics.drainage_flux_m3_day, dtype=float)
    recharge_flux = np.asarray(diagnostics.recharge_flux_m3_day, dtype=float)
    east_boundary_inflow = np.zeros_like(total_outflow, dtype=float)
    total_inflow = np.asarray(recharge_flux + east_boundary_inflow, dtype=float)
    storage_change = np.asarray(
        getattr(
            diagnostics,
            "storage_change_m3_day",
            diagnostics.storage_balance_m3_day,
        ),
        dtype=float,
    )
    peak_drainage_idx = int(np.argmax(drainage_flux))
    peak_total_idx = int(np.argmax(total_outflow))
    return base.TransientResult(
        solver=solver_name,
        out_path=diagnostics.result.out_path,
        postprocess_dir=diagnostics.result.postprocess_dir,
        elapsed_days=np.asarray(diagnostics.elapsed_days, dtype=float),
        x=np.asarray(diagnostics.x_m, dtype=float),
        topography_profile=np.asarray(diagnostics.topography_profile_m, dtype=float),
        head_profiles=np.asarray(diagnostics.mean_head_profiles_m, dtype=float),
        clearance_profiles=np.asarray(diagnostics.mean_head_clearance_m, dtype=float),
        drainage_flux_m3_day=drainage_flux,
        east_boundary_inflow_m3_day=east_boundary_inflow,
        east_boundary_outflow_m3_day=east_boundary,
        total_inflow_m3_day=total_inflow,
        total_outflow_m3_day=total_outflow,
        recharge_flux_m3_day=recharge_flux,
        net_inflow_m3_day=np.asarray(
            total_inflow - total_outflow,
            dtype=float,
        ),
        storage_change_m3_day=storage_change,
        residual_m3_day=np.asarray(
            total_inflow - total_outflow - storage_change,
            dtype=float,
        ),
        max_clearance_m=float(np.max(np.asarray(diagnostics.mean_head_clearance_m, dtype=float))),
        onset_day=float(diagnostics.onset_day),
        peak_drainage_flux_m3_day=float(drainage_flux[peak_drainage_idx]),
        peak_drainage_day=float(diagnostics.elapsed_days[peak_drainage_idx]),
        peak_total_outflow_m3_day=float(total_outflow[peak_total_idx]),
        peak_total_outflow_day=float(diagnostics.elapsed_days[peak_total_idx]),
        bouss_surface_flux_m3_day=surface_excess,
        accumulation_proxy_m3_day=None,
        wall_time_seconds=wall_time_seconds,
    )


def _align_recharge_to_elapsed(elapsed_days: np.ndarray) -> np.ndarray:
    recharge = np.asarray(RECHARGE_SERIES_MM_DAY, dtype=float).reshape(-1)
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


def _write_flux_dashboard(results: list[base.TransientResult], output_png: Path) -> None:
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)

    fig, axis = base.plt.subplots(1, 1, figsize=(11.2, 4.8), constrained_layout=True)

    elapsed_days = np.asarray(ordered[0].elapsed_days, dtype=float)
    recharge_mm_day = _align_recharge_to_elapsed(elapsed_days)
    recharge_ax = axis.twinx()

    for item in ordered:
        axis.plot(
            item.elapsed_days,
            item.total_outflow_m3_day,
            label=SOLVER_LABELS[item.solver],
            **base._comparison_plot_style(item.solver),
        )
    recharge_ax.step(
        elapsed_days,
        recharge_mm_day,
        where="mid",
        color="#444444",
        linewidth=2.0,
        alpha=0.85,
        label="Recharge",
    )
    axis.set_ylabel("Total outflow [m3/day]")
    recharge_ax.set_ylabel("Recharge [mm/day]")
    axis.set_xlabel("Time [days]")
    axis.set_title("Recharge and total outflow", fontsize=10.6)
    axis.grid(alpha=0.25, linewidth=0.6)

    handles_left, labels_left = axis.get_legend_handles_labels()
    handles_right, labels_right = recharge_ax.get_legend_handles_labels()
    axis.legend(
        handles_left + handles_right,
        labels_left + labels_right,
        loc="upper left",
        fontsize=8.6,
        frameon=False,
        ncols=3,
    )

    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    base.plt.close(fig)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Linux benchmark comparing MODFLOW-NWT and selected Boussinesq methods "
            "on a 4-month rise, 4-month fall, 6-month dry transient."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT_DEFAULT,
        help="Directory where figures, CSV exports, and run outputs are written.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=2400,
        help="Per-solver timeout in seconds.",
    )
    return parser


def _write_summary(
    output_md: Path, *, results: list[base.TransientResult], figures_dir: Path
) -> None:
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    lines = [
        "# Linux NWT vs Boussinesq Transient Benchmark",
        "",
        "One common hillslope case with:",
        "",
        "- west no-flow",
        "- east fixed head",
        "- top drainage / surface response",
        "- recharge ramp up during 4 months, ramp down during 4 months, then 6 months with zero recharge",
        f"- time step: `{base.DT_DAYS:.1f} day`",
        f"- regularized partition radius: `{PARTITION_REGULARIZATION_RADIUS}`",
        f"- recharge series [mm/day]: `{list(RECHARGE_SERIES_MM_DAY)}`",
        "",
        "| Solver | Onset day [d] | Peak total outflow [m3/day] | Max clearance [m] | Wall time [s] | Results dir |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in ordered:
        wall_time_text = (
            "n/a" if item.wall_time_seconds is None else f"{item.wall_time_seconds:.2f}"
        )
        lines.append(
            f"| {SOLVER_LABELS[item.solver]} | {item.onset_day:.1f} | "
            f"{item.peak_total_outflow_m3_day:.4f} | {item.max_clearance_m:.4f} | "
            f"{wall_time_text} | `{item.out_path}` |"
        )
    lines.extend(
        [
            "",
            f"Head snapshots: `{figures_dir / 'head_snapshots.png'}`",
            f"Head point time series: `{figures_dir / 'head_point_timeseries.png'}`",
            f"Flux dashboard: `{figures_dir / 'flux_timeseries.png'}`",
            f"Total outflow overlay: `{figures_dir / 'total_outflow_overlay.png'}`",
            f"Complete flux budget: `{figures_dir / 'flux_budget_comparison.png'}`",
            f"Execution times: `{figures_dir / 'execution_times.png'}`",
            "",
        ]
    )
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _configure_base_module()
    parser = _build_parser()
    args = parser.parse_args(argv)
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    os.environ["HYDROMODPY_OUT_PATH"] = str(output_root)

    metadata = load_case_metadata(base.CASE_DIR)
    hydraulic_conductivity_m_s = float(
        metadata["reference"]["hydraulic_conductivity_m_per_s"]
    ) * float(base.HYDRAULIC_CONDUCTIVITY_SCALE)
    runtime_configs_dir = output_root / "runtime_configs"
    results: list[base.TransientResult] = []

    t0 = time.perf_counter()
    nwt_result = base._run_launcher_solver(
        metadata=metadata,
        solver="modflownwt",
        hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
        timeout=int(args.timeout),
        runtime_configs_dir=runtime_configs_dir,
    )
    results.append(base._build_result(nwt_result, wall_time_seconds=time.perf_counter() - t0))

    for solver_name in ("petsc_partition", "petsc"):
        t0 = time.perf_counter()
        run_result = run_boussinesq_hillslope_overflow_case(
            caller_file=__file__,
            timeout=int(args.timeout),
            solver=solver_name,
            context_preset=LINUX_NWT_BOUSS_RAMP_CONTEXT_PRESET,
            runtime_max_iterations=BOUSS_RUNTIME_MAX_ITERATIONS,
            runtime_tol_residual_inf=BOUSS_RUNTIME_TOL_RESIDUAL_INF,
            saturation_excess_regularization_radius=(
                PARTITION_REGULARIZATION_RADIUS if solver_name == "petsc_partition" else None
            ),
        )
        wall_time_seconds = time.perf_counter() - t0
        diagnostics = build_hillslope_overflow_diagnostics(result=run_result)
        results.append(
            _bouss_diagnostics_to_result(
                solver_name,
                diagnostics=diagnostics,
                wall_time_seconds=wall_time_seconds,
            )
        )

    timeseries_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    execution_rows: list[dict[str, Any]] = []
    for item in sorted(results, key=lambda row: SOLVER_ORDER.index(row.solver)):
        recharge_aligned = _align_recharge_to_elapsed(item.elapsed_days)
        for idx, day in enumerate(item.elapsed_days.tolist()):
            row: dict[str, Any] = {
                "solver": item.solver,
                "solver_label": SOLVER_LABELS[item.solver],
                "elapsed_days": float(day),
                "recharge_mm_day": float(recharge_aligned[idx]),
                "recharge_flux_m3_day": float(item.recharge_flux_m3_day[idx]),
                "drainage_flux_m3_day": float(item.drainage_flux_m3_day[idx]),
                "east_boundary_outflow_m3_day": float(item.east_boundary_outflow_m3_day[idx]),
                "total_outflow_m3_day": float(item.total_outflow_m3_day[idx]),
                "storage_balance_m3_day": float(item.storage_balance_m3_day[idx]),
                "max_clearance_m": float(np.max(item.clearance_profiles[idx])),
            }
            if item.bouss_surface_flux_m3_day is not None:
                row["surface_excess_flux_m3_day"] = float(item.bouss_surface_flux_m3_day[idx])
            timeseries_rows.append(row)
        summary_rows.append(
            {
                "solver": item.solver,
                "solver_label": SOLVER_LABELS[item.solver],
                "onset_day": item.onset_day,
                "peak_total_outflow_m3_day": item.peak_total_outflow_m3_day,
                "peak_total_outflow_day": item.peak_total_outflow_day,
                "max_clearance_m": item.max_clearance_m,
                "wall_time_seconds": item.wall_time_seconds,
                "results_dir": str(item.out_path),
                "postprocess_dir": str(item.postprocess_dir),
            }
        )
        execution_rows.append(
            {
                "solver": item.solver,
                "solver_label": SOLVER_LABELS[item.solver],
                "wall_time_seconds": item.wall_time_seconds,
                "results_dir": str(item.out_path),
            }
        )

    base._write_csv(output_root / "timeseries.csv", timeseries_rows)
    base._write_csv(output_root / "summary_metrics.csv", summary_rows)
    base._write_csv(output_root / "execution_times.csv", execution_rows)

    figures_dir = output_root / "figures"
    base._write_head_snapshots(results, figures_dir / "head_snapshots.png")
    _write_flux_dashboard(results, figures_dir / "flux_timeseries.png")
    base._write_total_outflow_overlay_figure(results, figures_dir / "total_outflow_overlay.png")
    base._write_flux_budget_figure(results, figures_dir / "flux_budget_comparison.png")
    base._write_execution_times_figure(results, figures_dir / "execution_times.png")
    head_point_rows = base._write_head_point_figure(
        results, figures_dir / "head_point_timeseries.png"
    )
    base._write_csv(output_root / "head_point_timeseries.csv", head_point_rows)
    _write_summary(output_root / "summary.md", results=results, figures_dir=figures_dir)
    (output_root / "summary.json").write_text(
        json.dumps(
            {
                "output_root": str(output_root),
                "timeseries_csv": str(output_root / "timeseries.csv"),
                "summary_metrics_csv": str(output_root / "summary_metrics.csv"),
                "execution_times_csv": str(output_root / "execution_times.csv"),
                "head_point_timeseries_csv": str(output_root / "head_point_timeseries.csv"),
                "figures_dir": str(figures_dir),
                "solver_names": list(SOLVER_ORDER),
                "context_preset": LINUX_NWT_BOUSS_RAMP_CONTEXT_PRESET,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
