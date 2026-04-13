from __future__ import annotations

import csv
import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from hydromodpy.analysis.display import display_options_from_raw_toml, plot_posthoc_all
from hydromodpy.analysis.display.posthoc import PosthocContext


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[2]
OUTPUT_ROOT = REPO_ROOT / "reporting" / "regional_lab_pilot_2026-04-12" / "outputs" / "linux_compare_outlet_27"
SUMMARY_PNG = THIS_DIR / "linux_backend_comparison.png"
SUMMARY_CSV = THIS_DIR / "linux_backend_comparison.csv"


@dataclass(frozen=True)
class BackendCase:
    backend_id: str
    label: str
    config_path: Path
    project_dir: Path


CASES = (
    BackendCase(
        backend_id="scipy_sparse",
        label="SciPy sparse",
        config_path=THIS_DIR / "run_headwater_100km2_outlet_27_boussinesq_scipy_sparse_linux.toml",
        project_dir=OUTPUT_ROOT / "scipy_sparse",
    ),
    BackendCase(
        backend_id="petsc_partition",
        label="PETSc partition",
        config_path=THIS_DIR / "run_headwater_100km2_outlet_27_boussinesq_petsc_partition_linux.toml",
        project_dir=OUTPUT_ROOT / "petsc_partition",
    ),
    BackendCase(
        backend_id="petsc_mixed",
        label="PETSc mixed",
        config_path=THIS_DIR / "run_headwater_100km2_outlet_27_boussinesq_petsc_mixed_linux.toml",
        project_dir=OUTPUT_ROOT / "petsc_mixed",
    ),
)


def _load_raw_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _render_posthoc_figures(case: BackendCase) -> list[Path]:
    raw = _load_raw_toml(case.config_path)
    options = display_options_from_raw_toml(raw)
    ctx = PosthocContext.from_project_dir(case.project_dir)
    return plot_posthoc_all(ctx, options)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _load_case_row(case: BackendCase) -> dict[str, object]:
    raw = _load_raw_toml(case.config_path)
    run_id = str(raw.get("simulation", {}).get("run_id", "")).strip()
    run_dir = case.project_dir / "results_simulations" / "flow_main__boussinesq"
    summary = _load_json(run_dir / "_boussinesq_summary.json")
    metrics_path = case.project_dir / "results_simulations" / run_id / "_metrics.json"
    wall_time = None
    if metrics_path.exists():
        wall_time = _load_json(metrics_path).get("wall_time_seconds")
    figures_dir = run_dir / "_postprocess" / "_figures"
    return {
        "backend_id": case.backend_id,
        "label": case.label,
        "status": summary.get("solve_stage"),
        "surface_model": summary.get("surface_interaction_model_resolved"),
        "nonlinear_iterations": summary.get("steady_nonlinear_iterations"),
        "residual_inf": summary.get("steady_residual_norm_inf"),
        "peak_active_fraction": summary.get("surface_threshold_peak_active_fraction"),
        "peak_head_above_top_m": summary.get("surface_threshold_peak_head_above_top_m"),
        "peak_surface_total_m3_day": summary.get("surface_threshold_peak_total_m3_day"),
        "wall_time_seconds": wall_time,
        "figures_dir": str(figures_dir),
    }


def _write_csv(rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "backend_id",
        "label",
        "status",
        "surface_model",
        "nonlinear_iterations",
        "residual_inf",
        "peak_active_fraction",
        "peak_head_above_top_m",
        "peak_surface_total_m3_day",
        "wall_time_seconds",
        "figures_dir",
    ]
    with SUMMARY_CSV.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _series(rows: list[dict[str, object]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if value is None:
            values.append(math.nan)
        else:
            values.append(float(value))
    return values


def _plot_summary(rows: list[dict[str, object]]) -> None:
    labels = [str(row["label"]) for row in rows]
    colors = ["#b2182b" if row["status"] != "solved" else "#2166ac" for row in rows]
    iterations = _series(rows, "nonlinear_iterations")
    residuals = _series(rows, "residual_inf")
    active_fraction = _series(rows, "peak_active_fraction")
    head_above_top = _series(rows, "peak_head_above_top_m")
    wall_time = _series(rows, "wall_time_seconds")

    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    fig.suptitle("Outlet 27 Linux Boussinesq comparison", fontsize=14)

    axes[0, 0].bar(labels, iterations, color=colors)
    axes[0, 0].set_title("Nonlinear iterations")
    axes[0, 0].tick_params(axis="x", rotation=15)

    axes[0, 1].bar(labels, residuals, color=colors)
    axes[0, 1].set_yscale("log")
    axes[0, 1].set_title("Residual inf")
    axes[0, 1].tick_params(axis="x", rotation=15)

    axes[0, 2].bar(labels, active_fraction, color=colors)
    axes[0, 2].set_ylim(0.0, 1.0)
    axes[0, 2].set_title("Peak active fraction")
    axes[0, 2].tick_params(axis="x", rotation=15)

    axes[1, 0].bar(labels, head_above_top, color=colors)
    axes[1, 0].set_yscale("log")
    axes[1, 0].set_title("Peak head above top [m]")
    axes[1, 0].tick_params(axis="x", rotation=15)

    axes[1, 1].bar(labels, wall_time, color=colors)
    axes[1, 1].set_title("Wall time [s]")
    axes[1, 1].tick_params(axis="x", rotation=15)

    axes[1, 2].axis("off")
    summary_lines = [
        f"{row['label']}: {row['status']} ({row['surface_model']})"
        for row in rows
    ]
    axes[1, 2].text(
        0.0,
        1.0,
        "\n".join(summary_lines),
        va="top",
        ha="left",
        fontsize=10,
        family="monospace",
    )

    fig.tight_layout()
    fig.savefig(SUMMARY_PNG, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    for case in CASES:
        figure_dirs = _render_posthoc_figures(case)
        print(f"[posthoc] {case.backend_id}: {', '.join(str(path) for path in figure_dirs)}")

    rows = [_load_case_row(case) for case in CASES]
    _write_csv(rows)
    _plot_summary(rows)
    print(f"[summary] csv={SUMMARY_CSV}")
    print(f"[summary] png={SUMMARY_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
