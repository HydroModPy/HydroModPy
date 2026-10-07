"""MODFLOW 6 on irregular triangles, with and without XT3D, on the analytical cases.

The fast regression ``test_xt3d_irregular_tri_fast_regression`` runs the steady
analytical cases that declare a ``modflow6_irregular_tri`` variant twice, XT3D
forced off then left to its automatic choice, and compares compact signatures.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from validation_cases.shared.case_records import CaseRecord, discover_case_records

REPO_ROOT = Path(__file__).resolve().parents[2]
DISABLE_XT3D_SITECUSTOMIZE_DIR = Path(__file__).resolve().parent / "xt3d_disable_sitecustomize"


def _selected_records(
    selected_case_slugs: Iterable[str] | None = None,
) -> tuple[CaseRecord, ...]:
    wanted = None if selected_case_slugs is None else {str(slug) for slug in selected_case_slugs}
    return tuple(
        record
        for record in discover_case_records(REPO_ROOT)
        if record.regime == "steady"
        and "modflow6_irregular_tri" in record.solver_variants
        and (wanted is None or record.slug in wanted)
    )


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


@contextmanager
def _patched_modflow6_xt3d_disabled(enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return

    from hydromodpy.solver.modflow6 import modflow6 as modflow6_module
    from hydromodpy.solver.modflow6.builders import solver_options

    Modflow6 = modflow6_module.Modflow6
    original_enabled = getattr(Modflow6, "_xt3d_is_enabled", None)
    original_mode = getattr(Modflow6, "_xt3d_activation_mode", None)
    original_resolve = getattr(Modflow6, "_resolve_xt3d_npf_options", None)
    original_builder_enabled = solver_options.xt3d_is_enabled
    original_builder_mode = solver_options.xt3d_activation_mode
    original_builder_resolve = solver_options.resolve_xt3d_npf_options
    original_module_enabled = modflow6_module.xt3d_is_enabled
    original_module_mode = modflow6_module.xt3d_mode
    original_module_resolve = modflow6_module.resolve_xt3d_options

    def _xt3d_disabled(self, solver_mesh=None) -> bool:
        return False

    def _xt3d_disabled_mode(self, solver_mesh=None) -> str:
        return "forced_disabled_for_doc_gallery"

    def _xt3d_disabled_options(self, solver_mesh=None) -> None:
        return None

    Modflow6._xt3d_is_enabled = _xt3d_disabled
    Modflow6._xt3d_activation_mode = _xt3d_disabled_mode
    Modflow6._resolve_xt3d_npf_options = _xt3d_disabled_options
    solver_options.xt3d_is_enabled = _xt3d_disabled
    solver_options.xt3d_activation_mode = _xt3d_disabled_mode
    solver_options.resolve_xt3d_npf_options = _xt3d_disabled_options
    modflow6_module.xt3d_is_enabled = _xt3d_disabled
    modflow6_module.xt3d_mode = _xt3d_disabled_mode
    modflow6_module.resolve_xt3d_options = _xt3d_disabled_options
    try:
        yield
    finally:
        if original_enabled is None:
            delattr(Modflow6, "_xt3d_is_enabled")
        else:
            Modflow6._xt3d_is_enabled = original_enabled
        if original_mode is None:
            delattr(Modflow6, "_xt3d_activation_mode")
        else:
            Modflow6._xt3d_activation_mode = original_mode
        if original_resolve is None:
            delattr(Modflow6, "_resolve_xt3d_npf_options")
        else:
            Modflow6._resolve_xt3d_npf_options = original_resolve
        solver_options.xt3d_is_enabled = original_builder_enabled
        solver_options.xt3d_activation_mode = original_builder_mode
        solver_options.resolve_xt3d_npf_options = original_builder_resolve
        modflow6_module.xt3d_is_enabled = original_module_enabled
        modflow6_module.xt3d_mode = original_module_mode
        modflow6_module.resolve_xt3d_options = original_module_resolve


def collect_irregular_tri_metrics(
    *,
    force_xt3d_disabled: bool,
    selected_case_slugs: Iterable[str] | None = None,
    timeout: int = 1800,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    extra_path = DISABLE_XT3D_SITECUSTOMIZE_DIR if force_xt3d_disabled else None

    with (
        _patched_pythonpath(extra_path),
        _patched_modflow6_xt3d_disabled(force_xt3d_disabled),
    ):
        for record in _selected_records(selected_case_slugs):
            runner = record.comparison_runner()
            started = time.perf_counter()
            comparison = runner(
                caller_file=__file__,
                solver="modflow6_irregular_tri",
                timeout=timeout,
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


def build_xt3d_method_choice_payload(
    *,
    selected_case_slugs: Iterable[str] | None = None,
    timeout: int = 1800,
) -> dict[str, Any]:
    baseline = collect_irregular_tri_metrics(
        force_xt3d_disabled=True,
        selected_case_slugs=selected_case_slugs,
        timeout=timeout,
    )
    current = collect_irregular_tri_metrics(
        force_xt3d_disabled=False,
        selected_case_slugs=selected_case_slugs,
        timeout=timeout,
    )
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
