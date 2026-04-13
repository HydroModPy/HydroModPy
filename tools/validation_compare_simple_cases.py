"""Cross-solver comparison report for simple analytical validation cases.

This utility runs a selected set of low-surface-interaction validation cases
for MODFLOW-NWT, MODFLOW 6, and Boussinesq, then writes stable comparison
figures and summary tables under one reporting directory.
"""

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
    "dupuit_fixed_head_1d",
    "dupuit_uniform_recharge_1d",
    "boussinesq_fixed_head_piecewise_k_1d",
)
DEFAULT_SOLVERS = ("modflownwt", "modflow6", "boussinesq")
CASE_SPECS: dict[str, tuple[str, str, str]] = {
    "dupuit_fixed_head_1d": (
        "validation_cases.analytical.steady.dupuit_fixed_head_1d.comparison",
        "run_dupuit_fixed_head_comparison",
        "Dupuit fixed-head 1D",
    ),
    "dupuit_uniform_recharge_1d": (
        "validation_cases.analytical.steady.dupuit_uniform_recharge_1d.comparison",
        "run_dupuit_uniform_recharge_comparison",
        "Dupuit uniform recharge 1D",
    ),
    "boussinesq_fixed_head_piecewise_k_1d": (
        "validation_cases.analytical.steady.boussinesq_fixed_head_piecewise_k_1d.comparison",
        "run_boussinesq_fixed_head_piecewise_k_comparison",
        "Boussinesq fixed-head piecewise-K 1D",
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
class SimpleComparisonResult:
    case_id: str
    case_title: str
    solver: str
    out_path: Path
    postprocess_dir: Path
    x: np.ndarray
    numerical_profile: np.ndarray
    analytical_profile: np.ndarray
    residual_profile: np.ndarray
    rms_error: float
    max_error: float
    row_spread: float


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_")


def _import_case_runner(case_id: str):
    module_name, function_name, _title = CASE_SPECS[case_id]
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def _run_case(case_id: str, solver: str, timeout: int) -> SimpleComparisonResult:
    runner = _import_case_runner(case_id)
    _module_name, _function_name, case_title = CASE_SPECS[case_id]
    comparison = runner(caller_file=__file__, timeout=timeout, solver=solver)
    return SimpleComparisonResult(
        case_id=case_id,
        case_title=case_title,
        solver=solver,
        out_path=Path(comparison.result.out_path),
        postprocess_dir=Path(comparison.result.postprocess_dir),
        x=np.asarray(comparison.x, dtype=float),
        numerical_profile=np.asarray(comparison.numerical_profile, dtype=float),
        analytical_profile=np.asarray(comparison.analytical_profile, dtype=float),
        residual_profile=np.asarray(comparison.residual_profile, dtype=float),
        rms_error=float(comparison.rms_error),
        max_error=float(comparison.max_error),
        row_spread=float(comparison.row_spread),
    )


def _pairwise_rows(results: list[SimpleComparisonResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_case: dict[str, list[SimpleComparisonResult]] = {}
    for item in results:
        by_case.setdefault(item.case_id, []).append(item)
    for case_id, case_results in by_case.items():
        for idx, left in enumerate(case_results):
            for right in case_results[idx + 1 :]:
                diff = np.asarray(left.numerical_profile - right.numerical_profile, dtype=float)
                rows.append(
                    {
                        "case_id": case_id,
                        "case_title": left.case_title,
                        "solver_left": left.solver,
                        "solver_right": right.solver,
                        "pairwise_profile_rmse_m": float(np.sqrt(np.mean(diff**2))),
                        "pairwise_max_abs_error_m": float(np.max(np.abs(diff))),
                        "pairwise_mean_abs_error_m": float(np.mean(np.abs(diff))),
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


def _profile_ylim(results: list[SimpleComparisonResult]) -> tuple[float, float]:
    values = [item.analytical_profile for item in results] + [item.numerical_profile for item in results]
    finite = np.concatenate([arr[np.isfinite(arr)] for arr in values if np.any(np.isfinite(arr))])
    if finite.size == 0:
        return 0.0, 1.0
    lo = float(np.min(finite))
    hi = float(np.max(finite))
    pad = max((hi - lo) * 0.08, 0.05)
    return lo - pad, hi + pad


def _residual_ylim(results: list[SimpleComparisonResult]) -> tuple[float, float]:
    finite = np.concatenate(
        [item.residual_profile[np.isfinite(item.residual_profile)] for item in results if np.any(np.isfinite(item.residual_profile))]
    )
    if finite.size == 0:
        return -1.0, 1.0
    bound = max(float(np.max(np.abs(finite))) * 1.15, 0.02)
    return -bound, bound


def _difference_ylim(results: list[SimpleComparisonResult]) -> tuple[float, float]:
    diffs: list[np.ndarray] = []
    for idx, left in enumerate(results):
        for right in results[idx + 1 :]:
            diffs.append(np.asarray(left.numerical_profile - right.numerical_profile, dtype=float))
    finite = np.concatenate([arr[np.isfinite(arr)] for arr in diffs if np.any(np.isfinite(arr))]) if diffs else np.array([])
    if finite.size == 0:
        return -1.0, 1.0
    bound = max(float(np.max(np.abs(finite))) * 1.15, 0.02)
    return -bound, bound


def _write_case_figure(case_results: list[SimpleComparisonResult], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    x = case_results[0].x
    analytical = case_results[0].analytical_profile
    fig, axes = plt.subplots(3, 1, figsize=(10.0, 9.0), sharex=True, constrained_layout=True)

    axes[0].plot(x, analytical, color="#222222", linewidth=2.0, label="Analytical")
    for item in case_results:
        axes[0].plot(
            item.x,
            item.numerical_profile,
            color=SOLVER_COLORS[item.solver],
            linewidth=1.8,
            label=SOLVER_LABELS[item.solver],
        )
    axes[0].set_ylabel("Head [m]")
    axes[0].set_ylim(*_profile_ylim(case_results))
    axes[0].grid(alpha=0.25, linewidth=0.6)
    axes[0].legend(loc="best", fontsize=9, frameon=False)

    for item in case_results:
        axes[1].plot(
            item.x,
            item.residual_profile,
            color=SOLVER_COLORS[item.solver],
            linewidth=1.6,
            label=SOLVER_LABELS[item.solver],
        )
    axes[1].axhline(0.0, color="#444444", linewidth=0.9)
    axes[1].set_ylabel("Solver - analytical [m]")
    axes[1].set_ylim(*_residual_ylim(case_results))
    axes[1].grid(alpha=0.25, linewidth=0.6)

    labels_seen: set[str] = set()
    for idx, left in enumerate(case_results):
        for right in case_results[idx + 1 :]:
            label = f"{SOLVER_LABELS[left.solver]} - {SOLVER_LABELS[right.solver]}"
            axes[2].plot(
                left.x,
                left.numerical_profile - right.numerical_profile,
                linewidth=1.5,
                label=label if label not in labels_seen else None,
            )
            labels_seen.add(label)
    axes[2].axhline(0.0, color="#444444", linewidth=0.9)
    axes[2].set_ylabel("Solver - solver [m]")
    axes[2].set_xlabel("x [m]")
    axes[2].set_ylim(*_difference_ylim(case_results))
    axes[2].grid(alpha=0.25, linewidth=0.6)
    axes[2].legend(loc="best", fontsize=8.5, frameon=False)

    case_title = case_results[0].case_title
    fig.suptitle(case_title, fontsize=13)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_rmse_bar_figure(results: list[SimpleComparisonResult], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    case_ids = [case_id for case_id in DEFAULT_CASE_IDS if any(item.case_id == case_id for item in results)]
    solvers = [solver for solver in DEFAULT_SOLVERS if any(item.solver == solver for item in results)]
    values = np.full((len(solvers), len(case_ids)), np.nan, dtype=float)
    titles = {case_id: CASE_SPECS[case_id][2] for case_id in case_ids}
    index_case = {case_id: idx for idx, case_id in enumerate(case_ids)}
    index_solver = {solver: idx for idx, solver in enumerate(solvers)}
    for item in results:
        values[index_solver[item.solver], index_case[item.case_id]] = item.rms_error

    x = np.arange(len(case_ids), dtype=float)
    width = 0.22
    fig, ax = plt.subplots(figsize=(10.5, 4.8), constrained_layout=True)
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
    ax.set_ylabel("RMSE vs analytical [m]")
    ax.set_xticks(x)
    ax.set_xticklabels([titles[case_id] for case_id in case_ids], rotation=12, ha="right")
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    ax.legend(fontsize=9, frameon=False, ncols=len(solvers))
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_markdown_summary(
    *,
    results: list[SimpleComparisonResult],
    pairwise_rows: list[dict[str, Any]],
    output_md: Path,
    figures_dir: Path,
) -> None:
    by_case: dict[str, list[SimpleComparisonResult]] = {}
    for item in results:
        by_case.setdefault(item.case_id, []).append(item)
    lines: list[str] = [
        "# Simple Validation Cross-Solver Comparison",
        "",
        "This report compares MODFLOW-NWT, MODFLOW 6, and Boussinesq on simple analytical cases with minimal surface interaction.",
        "",
    ]
    for case_id in [case for case in DEFAULT_CASE_IDS if case in by_case]:
        case_results = sorted(by_case[case_id], key=lambda item: DEFAULT_SOLVERS.index(item.solver))
        lines.append(f"## {case_results[0].case_title}")
        lines.append("")
        lines.append("| Solver | RMSE vs analytical [m] | Max abs error [m] | Cross-row spread [m] | Results dir |")
        lines.append("| --- | ---: | ---: | ---: | --- |")
        for item in case_results:
            lines.append(
                f"| {SOLVER_LABELS[item.solver]} | {item.rms_error:.4f} | {item.max_error:.4f} | {item.row_spread:.3e} | `{item.out_path}` |"
            )
        case_pairwise = [row for row in pairwise_rows if row["case_id"] == case_id]
        if case_pairwise:
            lines.append("")
            lines.append("| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |")
            lines.append("| --- | ---: | ---: | ---: |")
            for row in case_pairwise:
                left = SOLVER_LABELS[row["solver_left"]]
                right = SOLVER_LABELS[row["solver_right"]]
                lines.append(
                    f"| {left} vs {right} | {row['pairwise_profile_rmse_m']:.4f} | {row['pairwise_max_abs_error_m']:.4f} | {row['pairwise_mean_abs_error_m']:.4f} |"
                )
        figure_path = figures_dir / f"{_slug(case_id)}__profiles.png"
        lines.append("")
        lines.append(f"Figure: `{figure_path}`")
        lines.append("")

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run simple analytical cross-solver comparisons and write report artifacts."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "out" / "vscs_20260412",
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
    results: list[SimpleComparisonResult] = []
    for case_id in selected_cases:
        for solver in DEFAULT_SOLVERS:
            results.append(_run_case(case_id, solver, int(args.timeout)))

    metrics_rows = [
        {
            "case_id": item.case_id,
            "case_title": item.case_title,
            "solver": item.solver,
            "solver_label": SOLVER_LABELS[item.solver],
            "rmse_vs_analytical_m": item.rms_error,
            "max_abs_error_vs_analytical_m": item.max_error,
            "cross_row_spread_m": item.row_spread,
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
        _write_case_figure(case_results, figures_dir / f"{_slug(case_id)}__profiles.png")
    _write_rmse_bar_figure(results, figures_dir / "rmse_overview.png")
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
