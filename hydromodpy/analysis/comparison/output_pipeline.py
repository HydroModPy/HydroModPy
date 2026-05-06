"""Shared comparison output pipeline.

This module owns the neutral post-processing sequence used by comparison
launchers after their runs have been resolved and observable rows extracted.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.exports import (
    write_boussinesq_obstacle_diagnostics_export,
    write_budget_exports,
    write_execution_summary_csv,
    write_hydrographic_network_metrics_export,
    write_native_timeseries_exports,
    write_observable_chronicle_exports,
    write_simulated_active_network_distance_metrics_export,
    write_simulated_active_network_metrics_export,
    write_simulated_active_network_overlap_metrics_export,
    write_simulated_active_network_reference_figure_export,
    write_ts_vi_obstacle_runtime_diagnostics_export,
    write_vi_obstacle_runtime_diagnostics_export,
)
from hydromodpy.analysis.comparison.metric_diff import (
    DETAIL_METRIC_FIELDS,
    SUMMARY_METRIC_FIELDS,
    build_comparison_metrics,
    write_metrics_csv,
    write_metrics_json,
)
from hydromodpy.analysis.comparison.reporting import build_comparison_report
from hydromodpy.analysis.comparison.runtime import write_observables_csv
from hydromodpy.analysis.comparison.visuals import generate_comparison_figures


@dataclass(frozen=True)
class ComparisonOutputBundle:
    """Paths and payloads produced by the shared comparison output pipeline."""

    observables_csv: Path
    metrics_csv: Path
    differences_csv: Path
    metrics_json: Path
    report_path: Path
    figure_artifacts: list[dict[str, Any]]
    data_artifacts: list[dict[str, Any]]
    detail_metrics: list[dict[str, Any]]
    summary_metrics: list[dict[str, Any]]


def write_comparison_output_bundle(
    *,
    cfg: Any,
    comparison_id: str,
    comparison_root: Path,
    observables: Sequence[Any],
    rows: list[dict[str, Any]],
    metrics_schema_version: str,
    simulation_summaries: list[dict[str, Any]],
    reference_simulation: str | None,
    initial_data_artifacts: Sequence[dict[str, Any]] = (),
    report_text_transform: Callable[[str], str] | None = None,
) -> ComparisonOutputBundle:
    """Write common comparison artifacts after observable extraction."""
    summaries = simulation_summaries
    reference_id = reference_simulation
    observable_payloads = [_dump_observable(observable) for observable in observables]

    observables_csv = comparison_root / "observables.csv"
    write_observables_csv(observables_csv, rows)

    detail_metrics, summary_metrics = build_comparison_metrics(
        rows,
        reference_simulation=reference_id,
    )
    metrics_csv = comparison_root / "comparison_metrics.csv"
    differences_csv = comparison_root / "comparison_differences.csv"
    metrics_json = comparison_root / "comparison_metrics.json"
    write_metrics_csv(metrics_csv, summary_metrics, fieldnames=SUMMARY_METRIC_FIELDS)
    write_metrics_csv(differences_csv, detail_metrics, fieldnames=DETAIL_METRIC_FIELDS)
    write_metrics_json(
        metrics_json,
        {
            "schema_version": metrics_schema_version,
            "comparison_id": comparison_id,
            "reference_simulation": reference_id,
            "summary": summary_metrics,
            "differences": detail_metrics,
        },
    )

    data_artifacts: list[dict[str, Any]] = list(initial_data_artifacts)
    (
        observable_artifacts,
        _observable_long_rows,
        _observable_wide_rows,
        _observable_delta_rows,
    ) = write_observable_chronicle_exports(
        comparison_root=comparison_root,
        rows=rows,
        detail_metrics=detail_metrics,
        observables=observable_payloads,
    )
    data_artifacts.extend(observable_artifacts)
    native_artifacts, native_long_rows, _native_wide_rows, native_delta_rows = (
        write_native_timeseries_exports(
            comparison_id=comparison_id,
            comparison_root=comparison_root,
            simulation_summaries=summaries,
            reference_simulation=reference_id,
        )
    )
    data_artifacts.extend(native_artifacts)
    hydrographic_artifacts, _hydrographic_rows = write_hydrographic_network_metrics_export(
        comparison_id=comparison_id,
        comparison_root=comparison_root,
        simulation_summaries=summaries,
    )
    data_artifacts.extend(hydrographic_artifacts)
    simulated_active_artifacts, _simulated_active_rows = (
        write_simulated_active_network_metrics_export(
            comparison_id=comparison_id,
            comparison_root=comparison_root,
            simulation_summaries=summaries,
        )
    )
    data_artifacts.extend(simulated_active_artifacts)
    simulated_active_overlap_artifacts, _simulated_active_overlap_rows = (
        write_simulated_active_network_overlap_metrics_export(
            comparison_id=comparison_id,
            comparison_root=comparison_root,
            simulation_summaries=summaries,
        )
    )
    data_artifacts.extend(simulated_active_overlap_artifacts)
    simulated_active_distance_artifacts, _simulated_active_distance_rows = (
        write_simulated_active_network_distance_metrics_export(
            comparison_id=comparison_id,
            comparison_root=comparison_root,
            simulation_summaries=summaries,
        )
    )
    data_artifacts.extend(simulated_active_distance_artifacts)
    budget_artifacts, budget_rows = write_budget_exports(
        comparison_root=comparison_root,
        simulation_summaries=summaries,
    )
    data_artifacts.extend(budget_artifacts)
    obstacle_artifacts, _obstacle_rows = write_boussinesq_obstacle_diagnostics_export(
        comparison_root=comparison_root,
        simulation_summaries=summaries,
    )
    data_artifacts.extend(obstacle_artifacts)
    vi_diagnostic_artifacts, _vi_diagnostic_rows = write_vi_obstacle_runtime_diagnostics_export(
        comparison_root=comparison_root,
        simulation_summaries=summaries,
    )
    data_artifacts.extend(vi_diagnostic_artifacts)
    ts_vi_diagnostic_artifacts, _ts_vi_diagnostic_rows = (
        write_ts_vi_obstacle_runtime_diagnostics_export(
            comparison_root=comparison_root,
            simulation_summaries=summaries,
        )
    )
    data_artifacts.extend(ts_vi_diagnostic_artifacts)
    execution_artifacts, execution_rows = write_execution_summary_csv(
        comparison_root=comparison_root,
        simulation_summaries=summaries,
        reference_simulation=reference_id,
    )
    data_artifacts.extend(execution_artifacts)

    figure_artifacts = generate_comparison_figures(
        cfg=cfg,
        simulation_summaries=summaries,
        rows=rows,
        detail_metrics=detail_metrics,
        reference_simulation=reference_id,
        comparison_root=comparison_root,
        native_timeseries_rows=native_long_rows,
        native_timeseries_delta_rows=native_delta_rows,
        budget_rows=budget_rows,
        execution_rows=execution_rows,
    )
    simulated_active_figure_artifacts, _simulated_active_figure_rows = (
        write_simulated_active_network_reference_figure_export(
            comparison_root=comparison_root,
            simulation_summaries=summaries,
        )
    )
    figure_artifacts.extend(simulated_active_figure_artifacts)

    report_text = build_comparison_report(
        comparison_id=comparison_id,
        reference_simulation=reference_id,
        simulation_summaries=summaries,
        observables=observable_payloads,
        rows=rows,
        summary_metrics=summary_metrics,
        figure_artifacts=figure_artifacts,
        data_artifacts=data_artifacts,
    )
    if report_text_transform is not None:
        report_text = report_text_transform(report_text)

    report_path = comparison_root / "comparison_report.md"
    report_path.write_text(report_text, encoding="utf-8")

    return ComparisonOutputBundle(
        observables_csv=observables_csv,
        metrics_csv=metrics_csv,
        differences_csv=differences_csv,
        metrics_json=metrics_json,
        report_path=report_path,
        figure_artifacts=figure_artifacts,
        data_artifacts=data_artifacts,
        detail_metrics=detail_metrics,
        summary_metrics=summary_metrics,
    )


def _dump_observable(observable: Any) -> dict[str, Any]:
    if hasattr(observable, "model_dump"):
        return observable.model_dump(mode="json")
    return dict(observable)


__all__ = ("ComparisonOutputBundle", "write_comparison_output_bundle")
