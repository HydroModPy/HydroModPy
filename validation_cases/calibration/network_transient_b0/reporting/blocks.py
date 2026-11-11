"""Report blocks for the network/transient calibration diagnostic page."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.display.report.engine import (
    Block,
    Level,
    Link,
    Metric,
    Picture,
    pairs_table,
    write_pages,
)
from validation_cases.calibration.network_transient_b0.reporting import io as _nt_io


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
    """Write the diagnostic pages under ``web_root`` and return the text of ``index.html``."""

    index = write_pages(
        web_root,
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
        rendered=date.today(),
        preset="network_transient",
    )
    return index.read_text(encoding="utf-8")


def _block(
    *,
    block_id: str,
    title: str,
    level: Level,
    lead: str = "",
    status: str = "",
    metrics: tuple[Metric, ...] = (),
    figures: tuple[Picture, ...] = (),
    tables: tuple[Any, ...] = (),
    links: tuple[Link, ...] = (),
    warnings: tuple[str, ...] = (),
) -> Block:
    """Return a block whose items all start at ``level``."""

    items = (
        *([Metric("status", status)] if status else []),
        *metrics,
        *figures,
        *tables,
        *links,
        *warnings,
    )
    return Block(
        block_id, title, lead, min_level=level, items=tuple((level, item) for item in items)
    )


def build_network_transient_blocks(
    *,
    normalization: dict[str, Any],
    score_rows: list[dict[str, str]],
    figures: dict[str, Path],
    truth_dir: Path | None,
    score_table: Path | None,
    artifact_report: _nt_io.NetworkTransientHtmlArtifactReport,
) -> list[Block]:
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
) -> Block:
    status = "available" if artifact_report.ok else "partial"
    missing = list(artifact_report.required_missing) + list(artifact_report.optional_missing)
    warnings = list(artifact_report.contract_warnings)
    if missing:
        warnings.append("Artifacts missing or unreadable: " + ", ".join(missing[:8]))
    return _block(
        block_id="calibration_problem",
        title="Calibration problem",
        level="compact",
        status=status,
        lead=(
            "Two global parameters are sought: the hydraulic conductivity multiplier "
            "mK and the specific yield Sy."
        ),
        metrics=(
            Metric("artifact contract", "complete" if artifact_report.ok else "incomplete"),
            Metric("required missing", len(artifact_report.required_missing)),
            Metric("optional missing", len(artifact_report.optional_missing)),
            Metric("contract warnings", len(artifact_report.contract_warnings)),
        ),
        warnings=tuple(warnings),
    )


def _candidate_ranking_block(
    score_rows: list[dict[str, str]],
    truth_dir: Path | None,
) -> Block:
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
        Metric("points completed", f"{len(completed)} / {len(score_rows)}"),
        Metric("points failed", failed_count),
        Metric("best candidate other than the target", best.get("candidate_id", "-")),
        Metric("mK found", _nt_io.fmt_float(best.get("mK"), 2)),
        Metric("Sy found", _nt_io.fmt_float(best.get("Sy"), 3)),
        Metric("J minimum", _nt_io.fmt_float(best.get("J"), 5)),
    ]
    if target is not None:
        metrics.insert(
            0,
            Metric(
                "target value",
                f"mK={_nt_io.fmt_float(target[0], 2)}, Sy={_nt_io.fmt_float(target[1], 3)}",
            ),
        )
    return _block(
        block_id="candidate_ranking",
        title="Candidate ranking",
        level="compact",
        lead="Summary of the candidate grid and of the best point other than the target.",
        metrics=tuple(metrics),
        warnings=() if completed else ("No candidate completed in the score table.",),
    )


def _configuration_block(normalization: dict[str, Any], truth_dir: Path | None) -> Block:
    metadata = _nt_io.read_json(truth_dir / "metadata.json") if truth_dir is not None else {}
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
    return _block(
        block_id="site_characterization",
        title="Spatial and temporal setup",
        level="standard",
        lead="The site, the spatial support and the scoring window.",
        metrics=(
            Metric("site", metadata.get("site_id", "")),
            Metric("solver", metadata.get("steady_solver", "modflow6")),
            Metric("DISV cells", metadata.get("n_cells", "")),
            Metric("discharge periods", metadata.get("n_timesteps", "")),
            Metric("target draining cells", active_count),
            Metric(
                "target steady Q", _nt_io.fmt_float(normalization.get("Q_ref_steady"), 5), "m3/s"
            ),
            Metric("target mean Q", _nt_io.fmt_float(normalization.get("Qbar_ref"), 5), "m3/s"),
            Metric("target network L", _nt_io.fmt_float(normalization.get("L_ref"), 1), "m"),
            Metric("d_tol", _nt_io.fmt_float(normalization.get("d_tol"), 1), "m"),
        ),
        tables=(
            pairs_table(
                "score_window",
                "Time window",
                (
                    ("Time window", period_text),
                    ("Time step", "monthly"),
                ),
            ),
        ),
    )


def _recharge_block(figures: dict[str, Path]) -> Block:
    return _block(
        block_id="forcing_flux_context",
        title="Imposed recharge",
        level="standard",
        lead="Recharge forcing used to build and diagnose the runs.",
        figures=(
            Picture(
                "recharge_chronicle",
                "Recharge series",
                figures.get("recharge_chronicle"),
                "Monthly recharge taken from the source transient configuration.",
                required=False,
            ),
        ),
    )


def _basin_steady_context_block(figures: dict[str, Path]) -> Block:
    return _block(
        block_id="basin_steady_context",
        title="Catchment and target steady state",
        level="standard",
        lead=(
            "The network calibration signal comes from where the draining cells are, "
            "not only from the total steady budget."
        ),
        figures=(
            Picture(
                "watershed_id_card",
                "Catchment, mesh and outlet",
                figures.get("watershed_id_card"),
                "Identity card of the catchment and of its support.",
                required=False,
            ),
            Picture(
                "dem_context_map",
                "Topographic context / DEM",
                figures.get("dem_context_map"),
                "Topographic background, or the z_top_mean of the mesh as a fallback.",
                required=False,
            ),
            Picture(
                "steady_balance_didactic",
                "Reading the steady state",
                figures.get("steady_balance_didactic"),
                "Total budget of the target steady state, and the effect of mK.",
                required=False,
            ),
        ),
    )


def _objective_landscape_block(figures: dict[str, Path]) -> Block:
    return _block(
        block_id="objective_landscape",
        title="Objective function over the parameter space",
        level="standard",
        lead=(
            "The objective function over the (mK, Sy) plane, with 2D maps and cuts "
            "around the target."
        ),
        figures=(
            Picture(
                "objective_parameter_maps",
                "Flux, network and combined objectives",
                figures.get("objective_parameter_maps"),
                "Logarithmic scale; blank where a simulation is missing or did not complete.",
                required=False,
            ),
            Picture(
                "objective_profile_cuts",
                "Cuts around the target",
                figures.get("objective_profile_cuts"),
                "Cuts at the target mK and the target Sy.",
                required=False,
            ),
        ),
    )


def _hydrographic_network_block(figures: dict[str, Path]) -> Block:
    return _block(
        block_id="hydrographic_network",
        title="Drainage maps against the target",
        level="standard",
        lead=(
            "Spatial comparison of the target network and the best candidate other than the target."
        ),
        figures=(
            Picture(
                "outflow_drain_maps",
                "Target and best candidate on the topography",
                figures.get("outflow_drain_maps"),
                "Active drainage in color, inactive cells in transparent grey.",
                required=False,
            ),
        ),
    )


def _flow_timeseries_block(figures: dict[str, Path]) -> Block:
    return _block(
        block_id="flow_timeseries",
        title="Flux series",
        level="standard",
        lead="Q_total_release series of the candidates and of the target.",
        figures=(
            Picture(
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
) -> Block:
    links: list[Link] = []
    if truth_dir is not None:
        links.append(Link("Reference package", truth_dir, "truth"))
    if score_table is not None:
        links.append(Link("Score table", score_table, "score"))
    links.extend(Link(path.name, path, "figure") for _, path in sorted(figures.items()))
    rows = (
        {"kind": "available", "items": ", ".join(artifact_report.available)},
        {"kind": "required_missing", "items": ", ".join(artifact_report.required_missing)},
        {"kind": "optional_missing", "items": ", ".join(artifact_report.optional_missing)},
    )
    return _block(
        block_id="artifact_links",
        title="Artifacts",
        level="audit",
        tables=(
            pairs_table(
                "artifact_contract",
                "Artifact contract",
                ((row["kind"], row["items"]) for row in rows),
            ),
        ),
        links=tuple(links),
    )


def _report_module():
    from validation_cases.calibration.network_transient_b0 import network_transient_html

    return network_transient_html


__all__ = [
    "build_network_transient_blocks",
    "build_page",
]
