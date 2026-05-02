"""Diagnostics helpers for XT3D on irregular MODFLOW 6 validation cases."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .validation_case_registry import ValidationCaseRecord, build_validation_case_records

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_PATH = (
    REPO_ROOT
    / "tools"
    / "doc_gallery"
    / "manifests"
    / "xt3d_irregular_tri_method_choice_report.json"
)
DISABLE_XT3D_SITECUSTOMIZE_DIR = (
    REPO_ROOT / "tools" / "doc_gallery" / "disable_xt3d_sitecustomize"
)


def _selected_records() -> tuple[ValidationCaseRecord, ...]:
    records = build_validation_case_records(repo_root=REPO_ROOT)
    selected = [
        record
        for record in records
        if record.regime == "steady"
        and "modflow6_irregular_tri" in tuple(record.metadata.get("solver_variants", ()))
    ]
    return tuple(sorted(selected, key=lambda item: item.slug))


def _comparison_runner(record: ValidationCaseRecord):
    module = importlib.import_module(str(record.metadata["run_case_module"]))
    return getattr(module, str(record.metadata["comparison_function_name"]))


@contextmanager
def _patched_pythonpath(extra_path: Path | None) -> Iterator[None]:
    previous = os.environ.get("PYTHONPATH")
    if extra_path is None:
        yield
        return

    parts = [str(extra_path)]
    if previous:
        parts.append(previous)
    os.environ["PYTHONPATH"] = os.pathsep.join(parts)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = previous


def collect_irregular_tri_metrics(*, force_xt3d_disabled: bool) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    extra_path = DISABLE_XT3D_SITECUSTOMIZE_DIR if force_xt3d_disabled else None

    with _patched_pythonpath(extra_path):
        for record in _selected_records():
            runner = _comparison_runner(record)
            started = time.perf_counter()
            comparison = runner(
                caller_file=__file__,
                solver="modflow6_irregular_tri",
                timeout=1800,
            )
            duration_seconds = time.perf_counter() - started
            rows.append(
                {
                    "slug": record.slug,
                    "title": record.title,
                    "regime": record.regime,
                    "dimension": record.dimension,
                    "rms_error": float(comparison.rms_error),
                    "max_error": float(comparison.max_error),
                    "row_spread": float(comparison.row_spread),
                    "duration_seconds": float(duration_seconds),
                }
            )

    return {
        "label": "no_xt3d" if force_xt3d_disabled else "xt3d_auto",
        "case_count": len(rows),
        "cases": rows,
        "total_duration_seconds": float(sum(item["duration_seconds"] for item in rows)),
    }


def build_xt3d_method_choice_payload() -> dict[str, Any]:
    baseline = collect_irregular_tri_metrics(force_xt3d_disabled=True)
    current = collect_irregular_tri_metrics(force_xt3d_disabled=False)
    current_by_slug = {item["slug"]: item for item in current["cases"]}

    rows: list[dict[str, Any]] = []
    improved_count = 0
    regressed_count = 0
    strong_improvement_count = 0
    for old in baseline["cases"]:
        new = current_by_slug[old["slug"]]
        old_rmse = float(old["rms_error"])
        new_rmse = float(new["rms_error"])
        old_time = float(old["duration_seconds"])
        new_time = float(new["duration_seconds"])
        rmse_factor = (old_rmse / new_rmse) if new_rmse > 0.0 else float("inf")
        runtime_ratio = (new_time / old_time) if old_time > 0.0 else float("inf")
        improved = new_rmse < old_rmse
        if improved:
            improved_count += 1
        else:
            regressed_count += 1
        if rmse_factor >= 5.0:
            strong_improvement_count += 1
        rows.append(
            {
                "slug": old["slug"],
                "title": old["title"],
                "rmse_without_xt3d": old_rmse,
                "rmse_with_xt3d": new_rmse,
                "rmse_delta": new_rmse - old_rmse,
                "rmse_improvement_factor": rmse_factor,
                "max_error_without_xt3d": float(old["max_error"]),
                "max_error_with_xt3d": float(new["max_error"]),
                "time_without_xt3d_s": old_time,
                "time_with_xt3d_s": new_time,
                "time_ratio": runtime_ratio,
                "improved": improved,
            }
        )

    rows.sort(key=lambda item: float(item["rmse_without_xt3d"]), reverse=True)
    total_without = float(baseline["total_duration_seconds"])
    total_with = float(current["total_duration_seconds"])
    time_ratio_total = (total_with / total_without) if total_without > 0.0 else float("inf")
    improved_rows = [row for row in rows if row["improved"]]
    regressed_rows = [row for row in rows if not row["improved"]]

    return {
        "comparison_label": "MODFLOW 6 irregular triangles with and without XT3D",
        "case_count": len(rows),
        "rows": rows,
        "baseline": baseline,
        "current": current,
        "improved_count": improved_count,
        "regressed_count": regressed_count,
        "strong_improvement_count": strong_improvement_count,
        "total_time_without_xt3d_s": total_without,
        "total_time_with_xt3d_s": total_with,
        "total_time_ratio": time_ratio_total,
        "improved_case_slugs": [row["slug"] for row in improved_rows],
        "regressed_case_slugs": [row["slug"] for row in regressed_rows],
    }


def _round_float(value: float, digits: int) -> float:
    return round(float(value), digits)


def rounded_xt3d_method_choice_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rounded_rows: list[dict[str, Any]] = []
    for row in payload["rows"]:
        rounded_rows.append(
            {
                **row,
                "rmse_without_xt3d": _round_float(row["rmse_without_xt3d"], 6),
                "rmse_with_xt3d": _round_float(row["rmse_with_xt3d"], 6),
                "rmse_delta": _round_float(row["rmse_delta"], 6),
                "rmse_improvement_factor": _round_float(row["rmse_improvement_factor"], 4),
                "max_error_without_xt3d": _round_float(row["max_error_without_xt3d"], 6),
                "max_error_with_xt3d": _round_float(row["max_error_with_xt3d"], 6),
                "time_without_xt3d_s": _round_float(row["time_without_xt3d_s"], 2),
                "time_with_xt3d_s": _round_float(row["time_with_xt3d_s"], 2),
                "time_ratio": _round_float(row["time_ratio"], 4),
            }
        )
    return {
        **payload,
        "rows": rounded_rows,
        "baseline": {
            **payload["baseline"],
            "total_duration_seconds": _round_float(
                payload["baseline"]["total_duration_seconds"], 2
            ),
            "cases": [
                {
                    **case,
                    "rms_error": _round_float(case["rms_error"], 6),
                    "max_error": _round_float(case["max_error"], 6),
                    "row_spread": _round_float(case["row_spread"], 12),
                    "duration_seconds": _round_float(case["duration_seconds"], 2),
                }
                for case in payload["baseline"]["cases"]
            ],
        },
        "current": {
            **payload["current"],
            "total_duration_seconds": _round_float(payload["current"]["total_duration_seconds"], 2),
            "cases": [
                {
                    **case,
                    "rms_error": _round_float(case["rms_error"], 6),
                    "max_error": _round_float(case["max_error"], 6),
                    "row_spread": _round_float(case["row_spread"], 12),
                    "duration_seconds": _round_float(case["duration_seconds"], 2),
                }
                for case in payload["current"]["cases"]
            ],
        },
        "total_time_without_xt3d_s": _round_float(payload["total_time_without_xt3d_s"], 2),
        "total_time_with_xt3d_s": _round_float(payload["total_time_with_xt3d_s"], 2),
        "total_time_ratio": _round_float(payload["total_time_ratio"], 4),
    }


def write_xt3d_method_choice_report(output_path: Path | None = None) -> Path:
    resolved_path = DEFAULT_REPORT_PATH if output_path is None else Path(output_path).resolve()
    payload = rounded_xt3d_method_choice_payload(build_xt3d_method_choice_payload())
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return resolved_path


def load_xt3d_method_choice_report(report_path: Path | None = None) -> dict[str, Any]:
    resolved_path = DEFAULT_REPORT_PATH if report_path is None else Path(report_path).resolve()
    return json.loads(resolved_path.read_text(encoding="utf-8"))


def render_xt3d_tradeoff_figure(payload: dict[str, Any], output_path: Path) -> None:
    rows = list(payload["rows"])
    labels = [str(row["title"]) for row in rows]
    rmse_without = np.asarray([float(row["rmse_without_xt3d"]) for row in rows], dtype=float)
    rmse_with = np.asarray([float(row["rmse_with_xt3d"]) for row in rows], dtype=float)
    time_without = np.asarray([float(row["time_without_xt3d_s"]) for row in rows], dtype=float)
    time_with = np.asarray([float(row["time_with_xt3d_s"]) for row in rows], dtype=float)
    y = np.arange(len(rows))

    fig, axes = plt.subplots(1, 2, figsize=(15.5, max(7.5, 0.48 * len(rows) + 1.5)))
    ax_rmse, ax_time = axes

    ax_rmse.barh(y + 0.18, rmse_without, height=0.34, label="Without XT3D", color="#d95f02")
    ax_rmse.barh(y - 0.18, rmse_with, height=0.34, label="XT3D auto default", color="#1b9e77")
    ax_rmse.set_xlabel("Head-profile RMSE [m]")
    ax_rmse.set_yticks(y)
    ax_rmse.set_yticklabels(labels, fontsize=8)
    ax_rmse.invert_yaxis()
    ax_rmse.grid(axis="x", linestyle=":", alpha=0.35)
    ax_rmse.legend(loc="lower right", fontsize=8)
    ax_rmse.set_title("Accuracy on the 11 affected steady validation cases")

    ax_time.barh(y + 0.18, time_without, height=0.34, label="Without XT3D", color="#d95f02")
    ax_time.barh(y - 0.18, time_with, height=0.34, label="XT3D auto default", color="#1b9e77")
    ax_time.set_xlabel("Wall-clock time [s]")
    ax_time.set_yticks(y)
    ax_time.set_yticklabels([])
    ax_time.grid(axis="x", linestyle=":", alpha=0.35)
    ax_time.set_title("Observed local runtime cost in hydromodpy-kpg")

    fig.suptitle(
        "MODFLOW 6 irregular triangles: XT3D sharply reduces RMSE on recharge-driven cases\n"
        "while changing local runtime in mixed ways on the validation environment",
        fontsize=12,
    )
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


__all__ = [
    "build_xt3d_method_choice_payload",
    "collect_irregular_tri_metrics",
    "load_xt3d_method_choice_report",
    "render_xt3d_tradeoff_figure",
    "rounded_xt3d_method_choice_payload",
    "write_xt3d_method_choice_report",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the committed XT3D irregular-triangle diagnostics report."
    )
    parser.add_argument(
        "--output",
        help="Optional output JSON path. Defaults to the committed report source used by doc_gallery.",
    )
    args = parser.parse_args(argv)
    output = write_xt3d_method_choice_report(
        None if not args.output else Path(args.output).resolve()
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
