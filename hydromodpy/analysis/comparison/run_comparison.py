"""Compare N sealed runs of one case and write the comparison folder.

The runs are read from their directories (:mod:`.runs`, :mod:`.runtime`); the
observables are extracted, then the shared output pipeline writes the
differences, the stability checks, the budget closure, the maps and the series
(:mod:`.output_pipeline`). ``comparison_manifest.json`` closes the folder: it
lists what was compared, the ``case_check`` verdict and every artefact. This
module is its only writer and its only reader. The HTML page is rendered on
top of the folder by :mod:`hydromodpy.reporting.comparison`.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.config import BudgetZone, ComparisonSpec
from hydromodpy.analysis.comparison.output_pipeline import write_comparison_output_bundle
from hydromodpy.analysis.comparison.runs import (
    CaseCheck,
    ComparedRun,
    check_same_case,
    comparison_fine_raster,
    comparison_observables,
    comparison_simulation,
    simulation_summary,
)
from hydromodpy.analysis.comparison.runtime import extract_observable_rows
from hydromodpy.analysis.comparison.runtime.run_source import RunSource
from hydromodpy.core import progress

COMPARISON_MANIFEST_FILENAME = "comparison_manifest.json"
"""Manifest of a comparison folder, written last."""

COMPARISON_MANIFEST_SCHEMA = "hydromodpy.comparison.v2"
"""Schema of ``comparison_manifest.json``."""

METRICS_SCHEMA_VERSION = "comparison_metrics_v2"

_CLOSURE_SCORES = {
    "closure_max_abs_m3_s": "max_abs_closure_m3_s",
    "closure_max_abs_mm_d": "max_abs_closure_mm_d",
    "closure_relative_error_p95": "relative_closure_error_p95",
}
CLOSURE_METRIC_NAMES = tuple(_CLOSURE_SCORES)
"""The scores of the budget closure the comparison manifest carries, lower is better."""


@dataclass(frozen=True)
class ComparisonOutcome:
    """Where a comparison was written and what its manifest says."""

    comparison_root: Path
    manifest_path: Path
    manifest: dict[str, Any]


def write_comparison_manifest(comparison_root: Path, manifest: dict[str, Any]) -> Path:
    """Write ``comparison_manifest.json`` into *comparison_root*."""
    path = Path(comparison_root) / COMPARISON_MANIFEST_FILENAME
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def read_comparison_manifest(comparison_root: Path) -> dict[str, Any]:
    """Read ``comparison_manifest.json`` of *comparison_root*, empty when absent."""
    path = Path(comparison_root) / COMPARISON_MANIFEST_FILENAME
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def run_comparison(
    runs: Sequence[ComparedRun],
    *,
    comparison_root: Path,
    comparison_id: str,
    variables: Sequence[str] | None = None,
    allow_different_mesh: bool = False,
    budget_zone: BudgetZone = "domain",
) -> ComparisonOutcome:
    """Compare *runs*, the first one as the reference, into *comparison_root*.

    The budget exports sum the zone *budget_zone* names, the model domain by
    default, and label it.

    Raises :class:`~hydromodpy.analysis.comparison.runs.ComparisonCaseError`
    before writing anything when the runs are not one case.
    """
    if len(runs) < 2:
        raise ValueError("A comparison needs at least two runs.")
    case_check = check_same_case(runs, allow_different_mesh=allow_different_mesh)
    started_at = time.monotonic()
    root = Path(comparison_root).expanduser().resolve()
    spec = ComparisonSpec(
        comparison_id=comparison_id,
        comparison_root=root,
        reference_simulation=runs[0].name,
        fine_raster=comparison_fine_raster(runs[0]),
        budget_zone=budget_zone,
        simulation=[comparison_simulation(run) for run in runs],
        observable=comparison_observables(runs, variables),
    )
    root.mkdir(parents=True, exist_ok=True)
    summaries = [simulation_summary(run) for run in runs]
    rows = _extract_rows(spec, runs, summaries)

    outputs = write_comparison_output_bundle(
        cfg=spec,
        comparison_id=comparison_id,
        comparison_root=root,
        simulation_summaries=summaries,
        observables=spec.observable,
        rows=rows,
        reference_simulation=spec.reference_simulation,
        metrics_schema_version=METRICS_SCHEMA_VERSION,
        report_text_transform=lambda text: _prepend_case_check(text, case_check),
    )
    manifest: dict[str, Any] = {
        "schema": COMPARISON_MANIFEST_SCHEMA,
        "comparison_id": comparison_id,
        "comparison_root": str(root),
        "reference_simulation": spec.reference_simulation,
        "case_check": case_check.as_dict(),
        "observables_csv": str(outputs.observables_csv),
        "comparison_metrics_csv": str(outputs.metrics_csv),
        "comparison_differences_csv": str(outputs.differences_csv),
        "comparison_metrics_json": str(outputs.metrics_json),
        "comparison_report_md": str(outputs.report_path),
        "comparison_figures_dir": str(root / "comparison_figures"),
        "comparison_figures": outputs.figure_artifacts,
        "comparison_data_artifacts": outputs.data_artifacts,
        "boussinesq_vi_obstacle_diagnostics": _prefixed_artifact_index(
            outputs.data_artifacts, prefix="vi_obstacle_"
        ),
        "boussinesq_ts_vi_obstacle_diagnostics": _prefixed_artifact_index(
            outputs.data_artifacts, prefix="ts_vi_obstacle_"
        ),
        "n_observable_rows": len(rows),
        "n_metric_rows": len(outputs.summary_metrics),
        "n_difference_rows": len(outputs.detail_metrics),
        "wall_time_seconds": round(time.monotonic() - started_at, 2),
        "simulations": summaries,
        "observables": [observable.model_dump(mode="json") for observable in spec.observable],
    }
    closure = _numerical_closure_manifest(outputs.closure_summary_rows)
    if closure:
        manifest["numerical_closure"] = closure
        manifest.update({name: closure[field] for name, field in _CLOSURE_SCORES.items()})
        manifest.update(
            {
                "closure_status": closure["diagnostic"],
                "closure_status_code": closure["diagnostic_code"],
            }
        )
    manifest_path = write_comparison_manifest(root, manifest)
    return ComparisonOutcome(comparison_root=root, manifest_path=manifest_path, manifest=manifest)


def _extract_rows(
    spec: ComparisonSpec, runs: Sequence[ComparedRun], summaries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with progress.task("Reading the compared runs", total=len(runs)) as bar:
        for run, simulation, summary in zip(runs, spec.simulation, summaries, strict=True):
            with RunSource(run.run_dir, run.record) as source:
                simulation_rows = extract_observable_rows(
                    comparison_id=spec.comparison_id,
                    simulation=simulation,
                    run_folder=run.run_dir,
                    observables=tuple(spec.observable),
                    store=source,
                    sim_id=source.sim_id,
                )
            summary["n_observable_rows"] = len(simulation_rows)
            rows.extend(simulation_rows)
            bar.advance()
    return rows


def _prepend_case_check(report_text: str, case_check: CaseCheck) -> str:
    lines = [
        f"# Comparison report: site {case_check.site or 'n/a'}",
        "",
        f"- Same case: `{case_check.status}`",
        f"- Site fingerprint: `{case_check.site_fingerprint or 'n/a'}`",
        *(f"- {issue}" for issue in case_check.issues),
        "",
    ]
    return "\n".join(lines) + report_text


def _prefixed_artifact_index(
    artifacts: list[dict[str, Any]], *, prefix: str
) -> dict[str, dict[str, str]]:
    """Group diagnostic artifacts with a common kind prefix by simulation id."""
    grouped: dict[str, dict[str, str]] = {}
    for artifact in artifacts:
        kind = str(artifact.get("kind", ""))
        simulation_id = str(artifact.get("simulation_id", ""))
        path = str(artifact.get("path", ""))
        if kind.startswith(prefix) and simulation_id and path:
            grouped.setdefault(simulation_id, {})[kind.removeprefix(prefix)] = path
    return grouped


_CLOSURE_RANK = {"OK": 0, "WARN": 1, "UNKNOWN": 2, "CHECK": 3}
_CLOSURE_CODE = {"OK": 0.0, "WARN": 1.0, "CHECK": 2.0}


def _numerical_closure_manifest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    worst = max(
        (str(row.get("diagnostic", "")).upper() for row in rows),
        key=lambda value: _CLOSURE_RANK.get(value, -1),
    )
    diagnostic = worst if worst in _CLOSURE_RANK else "UNKNOWN"
    return {
        "schema_version": "numerical_closure_manifest_v1",
        "diagnostic": diagnostic,
        "diagnostic_code": _CLOSURE_CODE.get(diagnostic),
        "max_abs_closure_m3_s": _max_finite(rows, "max_abs_closure_m3_s"),
        "max_abs_closure_mm_d": _max_finite(rows, "max_abs_closure_mm_d"),
        "relative_closure_error_p95": _max_finite(rows, "relative_closure_error_p95"),
        "rows": rows,
    }


def _max_finite(rows: list[dict[str, Any]], field: str) -> float | None:
    values: list[float] = []
    for row in rows:
        try:
            value = float(row.get(field))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    return max(values) if values else None


__all__ = (
    "CLOSURE_METRIC_NAMES",
    "COMPARISON_MANIFEST_FILENAME",
    "ComparisonOutcome",
    "read_comparison_manifest",
    "run_comparison",
    "write_comparison_manifest",
)
