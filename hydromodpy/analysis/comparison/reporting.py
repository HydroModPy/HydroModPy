"""Human-readable reporting helpers for comparison runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from hydromodpy.analysis.comparison.metric_diff import build_unmatched_groups


def _format_number(value: Any) -> str:
    if value in ("", None):
        return ""
    try:
        return f"{float(value):.6g}"
    except Exception:
        return str(value)


def build_comparison_report(
    *,
    comparison_id: str,
    observables: Iterable[Mapping[str, Any]],
    rows: list[dict[str, Any]],
    summary_metrics: list[dict[str, Any]],
    reference_simulation: str | None,
    simulation_summaries: list[dict[str, Any]],
    figure_artifacts: Iterable[Mapping[str, Any]] | None = None,
    data_artifacts: Iterable[Mapping[str, Any]] | None = None,
) -> str:
    """Build a short Markdown report for one comparison run."""
    unmatched = build_unmatched_groups(rows, reference_simulation=reference_simulation)
    figures = list(figure_artifacts or [])
    data_files = list(data_artifacts or [])
    completed_simulations = [
        summary
        for summary in simulation_summaries
        if summary.get("status") in {"completed", "reused"}
    ]

    lines = [
        f"# Simulation Comparison Report: {comparison_id}",
        "",
        f"- Reference simulation: `{reference_simulation or 'none'}`",
        f"- Completed simulations: {len(completed_simulations)} / {len(simulation_summaries)}",
        f"- Observable rows: {len(rows)}",
        f"- Comparable metric groups: {len(summary_metrics)}",
        f"- Unmatched row groups: {len(unmatched)}",
        "",
        "## Simulations",
    ]
    for summary in simulation_summaries:
        wall_time = summary.get("wall_time_seconds")
        run_folder = summary.get("run_folder", "")
        lines.append(
            f"- `{summary.get('id', '')}`: {summary.get('status', '')}"
            f", solver=`{summary.get('solver', '') or 'n/a'}`"
            f", mesh=`{summary.get('mesh_mode', '')}`"
            f", rows={summary.get('n_observable_rows', 0)}"
            f", wall_time={_format_number(wall_time)}"
            f", run_folder=`{run_folder}`"
        )

    lines.extend(
        [
            "",
            "## Observables",
        ]
    )
    for observable in observables:
        lines.append(
            f"- `{observable.get('name', '')}`:"
            f" variable=`{observable.get('variable', '')}`"
            f", support=`{observable.get('support', '')}`"
            f", unit=`{observable.get('unit', '') or 'native'}`"
        )

    lines.extend(
        [
            "",
            "## Figures",
        ]
    )
    if not figures:
        lines.append("- No comparison figures were generated.")
    else:
        for figure in figures:
            lines.append(
                f"- `{figure.get('kind', '')}` / `{figure.get('observable', '')}`:"
                f" `{figure.get('path', '')}`"
            )

    lines.extend(
        [
            "",
            "## Data Exports",
        ]
    )
    if not data_files:
        lines.append("- No supplemental CSV exports were written.")
    else:
        for artifact in data_files:
            path = str(artifact.get("path", ""))
            note = str(artifact.get("note", "")).strip()
            if path not in {"", "None"}:
                line = f"- `{artifact.get('kind', '')}`: `{path}`"
            else:
                line = f"- `{artifact.get('kind', '')}`"
            if note != "":
                line += f" ({note})"
            lines.append(line)

    vi_section = _vi_obstacle_diagnostics_section(data_files)
    if vi_section:
        lines.extend(["", "## Boussinesq PETSc VI obstacle diagnostics"])
        lines.extend(vi_section)
    ts_vi_section = _ts_vi_obstacle_diagnostics_section(data_files)
    if ts_vi_section:
        lines.extend(["", "## Boussinesq PETSc TS VI obstacle diagnostics"])
        lines.extend(ts_vi_section)

    lines.extend(
        [
            "",
            "## Metrics",
        ]
    )
    if not summary_metrics:
        lines.append("- No comparable metric groups were produced.")
    else:
        lines.append(
            "| Simulation | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |"
        )
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for row in summary_metrics:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("simulation_id", "")),
                        str(row.get("observable", "")),
                        str(row.get("unit", "")),
                        str(row.get("n_pairs", "")),
                        _format_number(row.get("bias")),
                        _format_number(row.get("mae")),
                        _format_number(row.get("rmse")),
                        _format_number(row.get("max_abs_error")),
                        _format_number(row.get("mean_relative_error")),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Gaps",
        ]
    )
    if not unmatched:
        lines.append("- No unmatched rows.")
    else:
        for item in unmatched:
            simulation_id = str(item.get("simulation_id", ""))
            lines.append(
                f"- `{simulation_id}` / `{item['observable']}` / `{item['unit'] or 'no-unit'}`:"
                f" {item['n_rows']} rows skipped ({item['reason']})."
            )

    return "\n".join(lines).rstrip() + "\n"


def _vi_obstacle_diagnostics_section(
    data_files: Iterable[Mapping[str, Any]],
) -> list[str]:
    artifacts = [
        artifact
        for artifact in data_files
        if str(artifact.get("kind", "")).startswith("vi_obstacle_")
    ]
    if not artifacts:
        return []
    runtime_artifacts = [
        artifact
        for artifact in artifacts
        if str(artifact.get("kind", "")) == "vi_obstacle_runtime_summary"
    ]
    lines: list[str] = []
    for artifact in runtime_artifacts:
        summary = artifact.get("summary")
        if not isinstance(summary, Mapping):
            summary = {}
        simulation_id = artifact.get("simulation_id", "")
        lines.append(
            f"- `{simulation_id}`:"
            f" requested_substeps={_format_number(summary.get('vi_substeps_per_period'))}"
            f", max_substeps_used={_format_number(summary.get('max_substeps_used'))}"
            f", adaptive_used={_yes_no(summary.get('adaptive_substepping_used_any'))}"
            f", all_periods_converged={_yes_no(summary.get('all_periods_converged'))}"
            f", max_active_top={_format_number(summary.get('max_active_top_count'))}"
            f", max_active_bottom={_format_number(summary.get('max_active_bottom_count'))}"
            f", max_upper_violation={_format_number(summary.get('max_upper_violation'))}"
            f", max_lower_violation={_format_number(summary.get('max_lower_violation'))}"
        )
    for artifact in artifacts:
        path = str(artifact.get("path", ""))
        if path:
            lines.append(
                f"- `{artifact.get('kind', '')}`"
                f" for `{artifact.get('simulation_id', '')}`: `{path}`"
            )
    return lines


def _ts_vi_obstacle_diagnostics_section(
    data_files: Iterable[Mapping[str, Any]],
) -> list[str]:
    artifacts = [
        artifact
        for artifact in data_files
        if str(artifact.get("kind", "")).startswith("ts_vi_obstacle_")
    ]
    if not artifacts:
        return []
    runtime_artifacts = [
        artifact
        for artifact in artifacts
        if str(artifact.get("kind", "")) == "ts_vi_obstacle_runtime_summary"
    ]
    lines: list[str] = []
    for artifact in runtime_artifacts:
        summary = artifact.get("summary")
        if not isinstance(summary, Mapping):
            summary = {}
        simulation_id = artifact.get("simulation_id", "")
        lines.append(
            f"- `{simulation_id}`:"
            f" ts_steps_per_period={_format_number(summary.get('ts_vi_steps_per_period'))}"
            f", total_ts_steps={_format_number(summary.get('total_ts_steps'))}"
            f", adapt={_yes_no(summary.get('ts_vi_adapt'))}"
            f", all_periods_converged={_yes_no(summary.get('all_periods_converged'))}"
            f", max_active_top={_format_number(summary.get('max_active_top_count'))}"
            f", max_active_bottom={_format_number(summary.get('max_active_bottom_count'))}"
            f", max_upper_violation={_format_number(summary.get('max_upper_violation'))}"
            f", max_lower_violation={_format_number(summary.get('max_lower_violation'))}"
        )
    for artifact in artifacts:
        path = str(artifact.get("path", ""))
        if path:
            lines.append(
                f"- `{artifact.get('kind', '')}`"
                f" for `{artifact.get('simulation_id', '')}`: `{path}`"
            )
    return lines


def _yes_no(value: Any) -> str:
    if value is None or value == "":
        return ""
    return "yes" if bool(value) else "no"


__all__ = ("build_comparison_report",)
