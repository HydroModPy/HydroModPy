"""Cross-solver comparison report for simple transient analytical validation cases."""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CASE_IDS = (
    "lu_recharge_step_1d",
    "lu_boundary_step_1d",
    "lu_recharge_step_deep_1d",
)
DEFAULT_SOLVERS = ("modflownwt", "modflow6", "boussinesq")
CASE_SPECS: dict[str, tuple[str, str, str]] = {
    "lu_recharge_step_1d": (
        "validation_cases.analytical.transient.linearized_unconfined_recharge_step_1d.comparison",
        "run_linearized_unconfined_recharge_step_comparison",
        "Linearized unconfined recharge step 1D",
    ),
    "lu_boundary_step_1d": (
        "validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.comparison",
        "run_linearized_unconfined_boundary_step_comparison",
        "Linearized unconfined boundary step 1D",
    ),
    "lu_recharge_step_deep_1d": (
        "validation_cases.analytical.transient.linearized_unconfined_recharge_step_deep_1d.comparison",
        "run_linearized_unconfined_recharge_step_deep_comparison",
        "Linearized unconfined recharge step deep 1D",
    ),
}
SOLVER_LABELS = {
    "modflownwt": "MODFLOW-NWT",
    "modflow6": "MODFLOW 6",
    "boussinesq": "Boussinesq",
}
SOLVER_COLORS = {
    "modflownwt": "#1f77b4",
    "modflow6": "#ff7f0e",
    "boussinesq": "#2ca02c",
}


@dataclass(frozen=True, slots=True)
class TransientSimpleComparisonResult:
    case_id: str
    case_title: str
    solver: str
    out_path: Path
    postprocess_dir: Path
    x: np.ndarray
    elapsed_days: np.ndarray
    numerical_profiles: np.ndarray
    analytical_profiles: np.ndarray
    residual_profiles: np.ndarray
    monitor_positions: np.ndarray
    numerical_monitor_series: np.ndarray
    analytical_monitor_series: np.ndarray
    space_time_rmse: float
    space_time_max_error: float
    final_profile_rmse: float
    final_profile_max_error: float
    row_spread: float


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_")


def _import_case_runner(case_id: str):
    module_name, function_name, _title = CASE_SPECS[case_id]
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def _run_case(case_id: str, solver: str, timeout: int) -> TransientSimpleComparisonResult:
    runner = _import_case_runner(case_id)
    _module_name, _function_name, case_title = CASE_SPECS[case_id]
    comparison = runner(caller_file=__file__, timeout=timeout, solver=solver)
    return TransientSimpleComparisonResult(
        case_id=case_id,
        case_title=case_title,
        solver=solver,
        out_path=Path(comparison.result.out_path),
        postprocess_dir=Path(comparison.result.postprocess_dir),
        x=np.asarray(comparison.x, dtype=float),
        elapsed_days=np.asarray(comparison.elapsed_days, dtype=float),
        numerical_profiles=np.asarray(comparison.numerical_profiles, dtype=float),
        analytical_profiles=np.asarray(comparison.analytical_profiles, dtype=float),
        residual_profiles=np.asarray(comparison.residual_profiles, dtype=float),
        monitor_positions=np.asarray(comparison.monitor_positions, dtype=float),
        numerical_monitor_series=np.asarray(comparison.numerical_monitor_series, dtype=float),
        analytical_monitor_series=np.asarray(comparison.analytical_monitor_series, dtype=float),
        space_time_rmse=float(comparison.space_time_rmse),
        space_time_max_error=float(comparison.space_time_max_error),
        final_profile_rmse=float(comparison.final_profile_rmse),
        final_profile_max_error=float(comparison.final_profile_max_error),
        row_spread=float(comparison.row_spread),
    )


def _interp_profile(x_source: np.ndarray, values: np.ndarray, x_target: np.ndarray) -> np.ndarray:
    return np.interp(x_target, x_source, values)


def _pairwise_rows(results: list[TransientSimpleComparisonResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_case: dict[str, list[TransientSimpleComparisonResult]] = {}
    for item in results:
        by_case.setdefault(item.case_id, []).append(item)
    for case_id, case_results in by_case.items():
        for idx, left in enumerate(case_results):
            for right in case_results[idx + 1 :]:
                # Final profile pairwise error on a common x support
                x_common = np.linspace(
                    max(float(left.x.min()), float(right.x.min())),
                    min(float(left.x.max()), float(right.x.max())),
                    num=max(left.x.size, right.x.size),
                    dtype=float,
                )
                left_final = _interp_profile(left.x, left.numerical_profiles[-1], x_common)
                right_final = _interp_profile(right.x, right.numerical_profiles[-1], x_common)
                final_diff = left_final - right_final

                # Monitor-series pairwise error on shared physical monitor positions
                monitor_diff_flat = np.array([], dtype=float)
                if left.monitor_positions.size and right.monitor_positions.size:
                    nmon = min(left.monitor_positions.size, right.monitor_positions.size)
                    left_order = np.argsort(left.monitor_positions)[:nmon]
                    right_order = np.argsort(right.monitor_positions)[:nmon]
                    left_mon = left.numerical_monitor_series[:, left_order]
                    right_mon = right.numerical_monitor_series[:, right_order]
                    monitor_diff_flat = np.ravel(left_mon - right_mon)

                rows.append(
                    {
                        "case_id": case_id,
                        "case_title": left.case_title,
                        "solver_left": left.solver,
                        "solver_right": right.solver,
                        "pairwise_final_profile_rmse_m": float(np.sqrt(np.mean(final_diff**2))),
                        "pairwise_final_profile_max_abs_error_m": float(np.max(np.abs(final_diff))),
                        "pairwise_monitor_rmse_m": float(np.sqrt(np.mean(monitor_diff_flat**2)))
                        if monitor_diff_flat.size
                        else float("nan"),
                        "pairwise_monitor_max_abs_error_m": float(np.max(np.abs(monitor_diff_flat)))
                        if monitor_diff_flat.size
                        else float("nan"),
                    }
                )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_case_figure(
    case_results: list[TransientSimpleComparisonResult], output_png: Path
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)

    ref = case_results[0]
    center_idx = ref.monitor_positions.size // 2 if ref.monitor_positions.size else 0
    center_position = (
        float(ref.monitor_positions[center_idx]) if ref.monitor_positions.size else float("nan")
    )
    final_time = float(ref.elapsed_days[-1])

    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.2), constrained_layout=True)

    # Final profile
    axes[0, 0].plot(
        ref.x, ref.analytical_profiles[-1], color="#222222", linewidth=2.0, label="Analytical"
    )
    for item in case_results:
        axes[0, 0].plot(
            item.x,
            item.numerical_profiles[-1],
            color=SOLVER_COLORS[item.solver],
            linewidth=1.8,
            label=SOLVER_LABELS[item.solver],
        )
    axes[0, 0].set_title(f"Final profile at t={final_time:.1f} d")
    axes[0, 0].set_xlabel("x [m]")
    axes[0, 0].set_ylabel("Head [m]")
    axes[0, 0].grid(alpha=0.25, linewidth=0.6)
    axes[0, 0].legend(loc="best", fontsize=9, frameon=False)

    # Final residual profile
    for item in case_results:
        axes[0, 1].plot(
            item.x,
            item.residual_profiles[-1],
            color=SOLVER_COLORS[item.solver],
            linewidth=1.7,
            label=SOLVER_LABELS[item.solver],
        )
    axes[0, 1].axhline(0.0, color="#444444", linewidth=0.9)
    axes[0, 1].set_title("Final profile residual vs analytical")
    axes[0, 1].set_xlabel("x [m]")
    axes[0, 1].set_ylabel("Solver - analytical [m]")
    axes[0, 1].grid(alpha=0.25, linewidth=0.6)

    # Center monitor series
    if ref.monitor_positions.size:
        axes[1, 0].plot(
            ref.elapsed_days,
            ref.analytical_monitor_series[:, center_idx],
            color="#222222",
            linewidth=2.0,
            label="Analytical",
        )
        for item in case_results:
            item_center = int(np.argmin(np.abs(item.monitor_positions - center_position)))
            axes[1, 0].plot(
                item.elapsed_days,
                item.numerical_monitor_series[:, item_center],
                color=SOLVER_COLORS[item.solver],
                linewidth=1.8,
                label=SOLVER_LABELS[item.solver],
            )
        axes[1, 0].set_title(f"Monitor at x={center_position:.1f} m")
        axes[1, 0].set_xlabel("Time [days]")
        axes[1, 0].set_ylabel("Head [m]")
        axes[1, 0].grid(alpha=0.25, linewidth=0.6)
        axes[1, 0].legend(loc="best", fontsize=9, frameon=False)
    else:
        axes[1, 0].set_visible(False)

    # Monitor residuals at center
    if ref.monitor_positions.size:
        for item in case_results:
            item_center = int(np.argmin(np.abs(item.monitor_positions - center_position)))
            analytical_center = item.analytical_monitor_series[:, item_center]
            residual = item.numerical_monitor_series[:, item_center] - analytical_center
            axes[1, 1].plot(
                item.elapsed_days,
                residual,
                color=SOLVER_COLORS[item.solver],
                linewidth=1.7,
                label=SOLVER_LABELS[item.solver],
            )
        axes[1, 1].axhline(0.0, color="#444444", linewidth=0.9)
        axes[1, 1].set_title("Monitor residual vs analytical")
        axes[1, 1].set_xlabel("Time [days]")
        axes[1, 1].set_ylabel("Solver - analytical [m]")
        axes[1, 1].grid(alpha=0.25, linewidth=0.6)
    else:
        axes[1, 1].set_visible(False)

    fig.suptitle(case_results[0].case_title, fontsize=13)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_overview_bar(results: list[TransientSimpleComparisonResult], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)

    case_ids = [
        case_id for case_id in DEFAULT_CASE_IDS if any(item.case_id == case_id for item in results)
    ]
    solvers = [
        solver for solver in DEFAULT_SOLVERS if any(item.solver == solver for item in results)
    ]
    values = np.full((len(solvers), len(case_ids)), np.nan, dtype=float)
    titles = {case_id: CASE_SPECS[case_id][2] for case_id in case_ids}
    index_case = {case_id: idx for idx, case_id in enumerate(case_ids)}
    index_solver = {solver: idx for idx, solver in enumerate(solvers)}
    for item in results:
        values[index_solver[item.solver], index_case[item.case_id]] = item.space_time_rmse

    x = np.arange(len(case_ids), dtype=float)
    width = 0.22
    fig, ax = plt.subplots(figsize=(11.0, 4.8), constrained_layout=True)
    for idx, solver in enumerate(solvers):
        offset = (idx - (len(solvers) - 1) / 2.0) * width
        heights = values[idx]
        bars = ax.bar(
            x + offset,
            heights,
            width=width,
            color=SOLVER_COLORS[solver],
            label=SOLVER_LABELS[solver],
        )
        for bar, height in zip(bars, heights, strict=False):
            if np.isfinite(height):
                ax.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    height,
                    f"{height:.3f}",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                )
    ax.set_ylabel("Space-time RMSE vs analytical [m]")
    ax.set_xticks(x)
    ax.set_xticklabels([titles[case_id] for case_id in case_ids], rotation=10, ha="right")
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    ax.legend(fontsize=9, frameon=False, ncols=len(solvers))
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_markdown_summary(
    *,
    results: list[TransientSimpleComparisonResult],
    pairwise_rows: list[dict[str, Any]],
    output_md: Path,
    figures_dir: Path,
) -> None:
    by_case: dict[str, list[TransientSimpleComparisonResult]] = {}
    for item in results:
        by_case.setdefault(item.case_id, []).append(item)

    lines: list[str] = [
        "# Simple Transient Cross-Solver Comparison",
        "",
        "This report compares MODFLOW-NWT, MODFLOW 6, and Boussinesq on transient 1D analytical cases with minimal surface interaction.",
        "",
    ]
    for case_id in [case for case in DEFAULT_CASE_IDS if case in by_case]:
        case_results = sorted(by_case[case_id], key=lambda item: DEFAULT_SOLVERS.index(item.solver))
        lines.append(f"## {case_results[0].case_title}")
        lines.append("")
        lines.append(
            "| Solver | Space-time RMSE [m] | Space-time max abs [m] | Final profile RMSE [m] | Final profile max abs [m] | Row spread [m] | Results dir |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
        for item in case_results:
            lines.append(
                f"| {SOLVER_LABELS[item.solver]} | {item.space_time_rmse:.4f} | {item.space_time_max_error:.4f} | {item.final_profile_rmse:.4f} | {item.final_profile_max_error:.4f} | {item.row_spread:.3e} | `{item.out_path}` |"
            )
        case_pairwise = [row for row in pairwise_rows if row["case_id"] == case_id]
        if case_pairwise:
            lines.append("")
            lines.append(
                "| Pair | Final profile RMSE [m] | Final profile max abs [m] | Monitor RMSE [m] | Monitor max abs [m] |"
            )
            lines.append("| --- | ---: | ---: | ---: | ---: |")
            for row in case_pairwise:
                left = SOLVER_LABELS[row["solver_left"]]
                right = SOLVER_LABELS[row["solver_right"]]
                lines.append(
                    f"| {left} vs {right} | {row['pairwise_final_profile_rmse_m']:.4f} | {row['pairwise_final_profile_max_abs_error_m']:.4f} | {row['pairwise_monitor_rmse_m']:.4f} | {row['pairwise_monitor_max_abs_error_m']:.4f} |"
                )
        figure_path = figures_dir / f"{_slug(case_id)}__transient.png"
        lines.append("")
        lines.append(f"Figure: `{figure_path}`")
        lines.append("")

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run transient analytical cross-solver comparisons and write report artifacts."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "out" / "vtcs_20260412",
        help="Directory where report artifacts are written.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Per-solver timeout in seconds.",
    )
    parser.add_argument(
        "--cases",
        nargs="+",
        default=list(DEFAULT_CASE_IDS),
        choices=sorted(CASE_SPECS),
        help="Validation cases to include.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    os.environ["HYDROMODPY_OUT_PATH"] = str(output_root)

    selected_cases = tuple(args.cases)
    results: list[TransientSimpleComparisonResult] = []
    for case_id in selected_cases:
        for solver in DEFAULT_SOLVERS:
            results.append(_run_case(case_id, solver, int(args.timeout)))

    metrics_rows = [
        {
            "case_id": item.case_id,
            "case_title": item.case_title,
            "solver": item.solver,
            "solver_label": SOLVER_LABELS[item.solver],
            "space_time_rmse_m": item.space_time_rmse,
            "space_time_max_abs_error_m": item.space_time_max_error,
            "final_profile_rmse_m": item.final_profile_rmse,
            "final_profile_max_abs_error_m": item.final_profile_max_error,
            "row_spread_m": item.row_spread,
            "results_dir": str(item.out_path),
            "postprocess_dir": str(item.postprocess_dir),
        }
        for item in results
    ]
    pairwise_rows = _pairwise_rows(results)
    _write_csv(output_root / "metrics.csv", metrics_rows)
    _write_csv(output_root / "pairwise_metrics.csv", pairwise_rows)

    figures_dir = output_root / "figures"
    for case_id in selected_cases:
        case_results = [item for item in results if item.case_id == case_id]
        _write_case_figure(case_results, figures_dir / f"{_slug(case_id)}__transient.png")
    _write_overview_bar(results, figures_dir / "space_time_rmse_overview.png")
    _write_markdown_summary(
        results=results,
        pairwise_rows=pairwise_rows,
        output_md=output_root / "summary.md",
        figures_dir=figures_dir,
    )
    (output_root / "summary.json").write_text(
        json.dumps(
            {
                "cases": list(selected_cases),
                "solvers": list(DEFAULT_SOLVERS),
                "metrics_csv": str(output_root / "metrics.csv"),
                "pairwise_metrics_csv": str(output_root / "pairwise_metrics.csv"),
                "summary_md": str(output_root / "summary.md"),
                "figures_dir": str(figures_dir),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
