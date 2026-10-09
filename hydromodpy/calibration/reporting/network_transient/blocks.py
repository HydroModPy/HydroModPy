"""Report blocks for the network/transient calibration diagnostic page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.calibration.reporting.network_transient import io as _nt_io
from hydromodpy.display.report_blocks import (
    ReportBlock,
    ReportFigure,
    ReportLink,
    ReportMetric,
    key_value_table,
    render_report_page,
)


def build_page(
    *,
    normalization: dict[str, Any],
    score_rows: list[dict[str, str]],
    figures: dict[str, Path],
    truth_dir: Path | None,
    score_table: Path | None,
    artifact_report: _nt_io.NetworkTransientHtmlArtifactReport,
    page_title: str,
    web_root: Path,
) -> str:
    """Render the diagnostic page through the shared report-block structure."""

    return render_report_page(
        title=page_title,
        subtitle=(
            "Reproducible diagnostic of a calibration on a steady network and a transient discharge."
        ),
        blocks=build_network_transient_blocks(
            normalization=normalization,
            score_rows=score_rows,
            figures=figures,
            truth_dir=truth_dir,
            score_table=score_table,
            artifact_report=artifact_report,
        ),
        web_dir=web_root,
    )


def build_network_transient_blocks(
    *,
    normalization: dict[str, Any],
    score_rows: list[dict[str, str]],
    figures: dict[str, Path],
    truth_dir: Path | None,
    score_table: Path | None,
    artifact_report: _nt_io.NetworkTransientHtmlArtifactReport,
) -> list[ReportBlock]:
    """Build reusable blocks for one network/transient calibration report."""

    return [
        _calibration_problem_block(artifact_report),
        _candidate_ranking_block(score_rows, truth_dir),
        _configuration_block(normalization, truth_dir),
        _recharge_block(figures),
        _basin_steady_context_block(figures),
        _objective_landscape_block(figures),
        _hydrographic_network_block(figures),
        _flow_timeseries_block(figures),
        _artifact_links_block(
            artifact_report=artifact_report,
            truth_dir=truth_dir,
            score_table=score_table,
            figures=figures,
        ),
    ]


def _calibration_problem_block(
    artifact_report: _nt_io.NetworkTransientHtmlArtifactReport,
) -> ReportBlock:
    status = "available" if artifact_report.ok else "partial"
    missing = list(artifact_report.required_missing) + list(artifact_report.optional_missing)
    warnings = list(artifact_report.contract_warnings)
    if missing:
        warnings.append("Artifacts missing or unreadable: " + ", ".join(missing[:8]))
    return ReportBlock(
        block_id="calibration_problem",
        title="Calibration problem",
        level="compact",
        status=status,
        lead=(
            "Two global parameters are sought: the hydraulic conductivity multiplier "
            "mK and the specific yield Sy."
        ),
        metrics=(
            ReportMetric("artifact contract", "complete" if artifact_report.ok else "incomplete"),
            ReportMetric("required missing", len(artifact_report.required_missing)),
            ReportMetric("optional missing", len(artifact_report.optional_missing)),
            ReportMetric("contract warnings", len(artifact_report.contract_warnings)),
        ),
        warnings=tuple(warnings),
    )


def _candidate_ranking_block(
    score_rows: list[dict[str, str]],
    truth_dir: Path | None,
) -> ReportBlock:
    completed = [row for row in score_rows if row.get("status") == "completed"]
    failed_count = len([row for row in score_rows if row.get("status") != "completed"])
    target = _report_module()._truth_parameters(truth_dir)
    best_candidates = [
        row for row in completed if not _report_module()._candidate_is_truth(row)
    ] or completed
    best = (
        min(best_candidates, key=lambda row: _nt_io.coerce_float(row.get("J"), float("inf")))
        if best_candidates
        else {}
    )
    metrics = [
        ReportMetric("points completed", f"{len(completed)} / {len(score_rows)}"),
        ReportMetric("points failed", failed_count),
        ReportMetric("best candidate other than the target", best.get("candidate_id", "-")),
        ReportMetric("mK found", _nt_io.fmt_float(best.get("mK"), 2)),
        ReportMetric("Sy found", _nt_io.fmt_float(best.get("Sy"), 3)),
        ReportMetric("J minimum", _nt_io.fmt_float(best.get("J"), 5)),
    ]
    if target is not None:
        metrics.insert(
            0,
            ReportMetric(
                "target value",
                f"mK={_nt_io.fmt_float(target[0], 2)}, Sy={_nt_io.fmt_float(target[1], 3)}",
            ),
        )
    return ReportBlock(
        block_id="candidate_ranking",
        title="Candidate ranking",
        level="compact",
        lead="Summary of the candidate grid and of the best point other than the target.",
        metrics=tuple(metrics),
        warnings=() if completed else ("No candidate completed in the score table.",),
    )


def _configuration_block(normalization: dict[str, Any], truth_dir: Path | None) -> ReportBlock:
    metadata = _read_json(truth_dir / "metadata.json") if truth_dir is not None else {}
    q_rows = (
        _nt_io.read_csv(truth_dir / "transient_q_total_release.csv")
        if truth_dir is not None
        else []
    )
    active_count = ""
    if truth_dir is not None and (truth_dir / "steady_network_active_mask.npz").is_file():
        active = np.load(truth_dir / "steady_network_active_mask.npz")["active_mask"]
        active_count = str(int(np.asarray(active, dtype=bool).sum()))
    period_text = ""
    if q_rows:
        period_text = f"{q_rows[0].get('datetime', '')} -> {q_rows[-1].get('datetime', '')}"
    return ReportBlock(
        block_id="site_characterization",
        title="Spatial and temporal setup",
        level="standard",
        lead="The site, the spatial support and the scoring window.",
        metrics=(
            ReportMetric("site", metadata.get("site_id", "")),
            ReportMetric("solver", metadata.get("steady_solver", "modflow6")),
            ReportMetric("DISV cells", metadata.get("n_cells", "")),
            ReportMetric("discharge periods", metadata.get("n_timesteps", "")),
            ReportMetric("target draining cells", active_count),
            ReportMetric(
                "target steady Q", _nt_io.fmt_float(normalization.get("Q_ref_steady"), 5), "m3/s"
            ),
            ReportMetric(
                "target mean Q", _nt_io.fmt_float(normalization.get("Qbar_ref"), 5), "m3/s"
            ),
            ReportMetric("target network L", _nt_io.fmt_float(normalization.get("L_ref"), 1), "m"),
            ReportMetric("d_tol", _nt_io.fmt_float(normalization.get("d_tol"), 1), "m"),
        ),
        tables=(
            key_value_table(
                "score_window",
                "Time window",
                (
                    ("Time window", period_text),
                    ("Time step", "monthly"),
                ),
            ),
        ),
    )


def _recharge_block(figures: dict[str, Path]) -> ReportBlock:
    return ReportBlock(
        block_id="forcing_flux_context",
        title="Imposed recharge",
        level="standard",
        lead="Recharge forcing used to build and diagnose the runs.",
        figures=(
            ReportFigure(
                "recharge_chronicle",
                "Recharge series",
                figures.get("recharge_chronicle"),
                "Monthly recharge taken from the source transient configuration.",
                required=False,
            ),
        ),
    )


def _basin_steady_context_block(figures: dict[str, Path]) -> ReportBlock:
    return ReportBlock(
        block_id="basin_steady_context",
        title="Catchment and target steady state",
        level="standard",
        lead=(
            "The network calibration signal comes from where the draining cells are, "
            "not only from the total steady budget."
        ),
        figures=(
            ReportFigure(
                "watershed_id_card",
                "Catchment, mesh and outlet",
                figures.get("watershed_id_card"),
                "Identity card of the catchment and of its support.",
                required=False,
            ),
            ReportFigure(
                "dem_context_map",
                "Topographic context / DEM",
                figures.get("dem_context_map"),
                "Topographic background, or the z_top_mean of the mesh as a fallback.",
                required=False,
            ),
            ReportFigure(
                "steady_balance_didactic",
                "Reading the steady state",
                figures.get("steady_balance_didactic"),
                "Total budget of the target steady state, and the effect of mK.",
                required=False,
            ),
        ),
    )


def _objective_landscape_block(figures: dict[str, Path]) -> ReportBlock:
    return ReportBlock(
        block_id="objective_landscape",
        title="Objective function over the parameter space",
        level="standard",
        lead=(
            "The objective function over the (mK, Sy) plane, with 2D maps and cuts "
            "around the target."
        ),
        figures=(
            ReportFigure(
                "objective_parameter_maps",
                "Flux, network and combined objectives",
                figures.get("objective_parameter_maps"),
                "Logarithmic scale; blank where a simulation is missing or did not complete.",
                required=False,
            ),
            ReportFigure(
                "objective_profile_cuts",
                "Cuts around the target",
                figures.get("objective_profile_cuts"),
                "Cuts at the target mK and the target Sy.",
                required=False,
            ),
        ),
    )


def _hydrographic_network_block(figures: dict[str, Path]) -> ReportBlock:
    return ReportBlock(
        block_id="hydrographic_network",
        title="Drainage maps against the target",
        level="standard",
        lead=(
            "Spatial comparison of the target network and the best candidate other than the target."
        ),
        figures=(
            ReportFigure(
                "outflow_drain_maps",
                "Target and best candidate on the topography",
                figures.get("outflow_drain_maps"),
                "Active drainage in colour, inactive cells in transparent grey.",
                required=False,
            ),
        ),
    )


def _flow_timeseries_block(figures: dict[str, Path]) -> ReportBlock:
    return ReportBlock(
        block_id="flow_timeseries",
        title="Flux series",
        level="standard",
        lead="Q_total_release series of the candidates and of the target.",
        figures=(
            ReportFigure(
                "q_total_release_timeseries",
                "Monthly Q_total_release",
                figures.get("q_total_release_timeseries"),
                "Sum of every outflow_drain flux leaving the domain.",
                required=False,
            ),
        ),
    )


def _artifact_links_block(
    *,
    artifact_report: _nt_io.NetworkTransientHtmlArtifactReport,
    truth_dir: Path | None,
    score_table: Path | None,
    figures: dict[str, Path],
) -> ReportBlock:
    links: list[ReportLink] = []
    if truth_dir is not None:
        links.append(ReportLink("Reference package", truth_dir, "truth"))
    if score_table is not None:
        links.append(ReportLink("Score table", score_table, "score"))
    links.extend(ReportLink(path.name, path, "figure") for _, path in sorted(figures.items()))
    rows = (
        {"kind": "available", "items": ", ".join(artifact_report.available)},
        {"kind": "required_missing", "items": ", ".join(artifact_report.required_missing)},
        {"kind": "optional_missing", "items": ", ".join(artifact_report.optional_missing)},
    )
    return ReportBlock(
        block_id="artifact_links",
        title="Artifacts",
        level="audit",
        tables=(
            key_value_table(
                "artifact_contract",
                "Artifact contract",
                ((row["kind"], row["items"]) for row in rows),
            ),
        ),
        links=tuple(links),
    )


def _read_json(path: Path) -> dict[str, Any]:
    return _nt_io.read_json(path)


def _report_module():
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html


__all__ = [
    "build_network_transient_blocks",
    "build_page",
]
