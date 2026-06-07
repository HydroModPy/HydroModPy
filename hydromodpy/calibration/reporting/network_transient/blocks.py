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
        subtitle=("Diagnostic reproductible de calibration reseau permanent + debit transitoire."),
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
        warnings.append("Artefacts absents ou non exploitables: " + ", ".join(missing[:8]))
    return ReportBlock(
        block_id="calibration_problem",
        title="Probleme de calibration",
        level="compact",
        status=status,
        lead=(
            "On cherche deux parametres globaux: le multiplicateur de conductivite "
            "hydraulique mK et le stockage specifique libre Sy."
        ),
        metrics=(
            ReportMetric("contrat artefacts", "complet" if artifact_report.ok else "incomplet"),
            ReportMetric("manquants requis", len(artifact_report.required_missing)),
            ReportMetric("manquants optionnels", len(artifact_report.optional_missing)),
            ReportMetric("alertes contrat", len(artifact_report.contract_warnings)),
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
        ReportMetric("points termines", f"{len(completed)} / {len(score_rows)}"),
        ReportMetric("points en echec", failed_count),
        ReportMetric("meilleur candidat non cible", best.get("candidate_id", "-")),
        ReportMetric("mK trouve", _nt_io.fmt_float(best.get("mK"), 2)),
        ReportMetric("Sy trouve", _nt_io.fmt_float(best.get("Sy"), 3)),
        ReportMetric("J minimum", _nt_io.fmt_float(best.get("J"), 5)),
    ]
    if target is not None:
        metrics.insert(
            0,
            ReportMetric(
                "valeur cible",
                f"mK={_nt_io.fmt_float(target[0], 2)}, Sy={_nt_io.fmt_float(target[1], 3)}",
            ),
        )
    return ReportBlock(
        block_id="candidate_ranking",
        title="Classement des candidats",
        level="compact",
        lead="Synthese de la grille de candidats et du meilleur point non cible.",
        metrics=tuple(metrics),
        warnings=() if completed else ("Aucun candidat termine dans la table de score.",),
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
        title="Configuration spatiale et temporelle",
        level="standard",
        lead="Caracterisation du site, du support spatial et de la fenetre de score.",
        metrics=(
            ReportMetric("site", metadata.get("site_id", "")),
            ReportMetric("solveur", metadata.get("steady_solver", "modflow6")),
            ReportMetric("cellules DISV", metadata.get("n_cells", "")),
            ReportMetric("periodes debit", metadata.get("n_timesteps", "")),
            ReportMetric("cellules drainantes cible", active_count),
            ReportMetric(
                "Q steady cible", _nt_io.fmt_float(normalization.get("Q_ref_steady"), 5), "m3/s"
            ),
            ReportMetric(
                "Q moyen cible", _nt_io.fmt_float(normalization.get("Qbar_ref"), 5), "m3/s"
            ),
            ReportMetric("L reseau cible", _nt_io.fmt_float(normalization.get("L_ref"), 1), "m"),
            ReportMetric("d_tol", _nt_io.fmt_float(normalization.get("d_tol"), 1), "m"),
        ),
        tables=(
            key_value_table(
                "score_window",
                "Fenetre temporelle",
                (
                    ("Fenetre temporelle", period_text),
                    ("Pas de temps", "mensuel"),
                ),
            ),
        ),
    )


def _recharge_block(figures: dict[str, Path]) -> ReportBlock:
    return ReportBlock(
        block_id="forcing_flux_context",
        title="Recharge imposee",
        level="standard",
        lead="Forcage de recharge utilise pour construire et diagnostiquer les runs.",
        figures=(
            ReportFigure(
                "recharge_chronicle",
                "Chronique de recharge",
                figures.get("recharge_chronicle"),
                "Recharge mensuelle issue de la configuration transitoire source.",
                required=False,
            ),
        ),
    )


def _basin_steady_context_block(figures: dict[str, Path]) -> ReportBlock:
    return ReportBlock(
        block_id="basin_steady_context",
        title="Contexte bassin et permanent cible",
        level="standard",
        lead=(
            "Le signal de calibration reseau vient de la repartition spatiale des "
            "cellules drainantes, pas seulement du bilan steady total."
        ),
        figures=(
            ReportFigure(
                "watershed_id_card",
                "Bassin, maillage et exutoire",
                figures.get("watershed_id_card"),
                "Carte d'identite du bassin et de son support.",
                required=False,
            ),
            ReportFigure(
                "dem_context_map",
                "Contexte topographique / DEM",
                figures.get("dem_context_map"),
                "Fond topographique ou repli z_top_mean porte par le maillage.",
                required=False,
            ),
            ReportFigure(
                "steady_balance_didactic",
                "Lecture didactique du permanent",
                figures.get("steady_balance_didactic"),
                "Bilan total du permanent cible et effet de mK.",
                required=False,
            ),
        ),
    )


def _objective_landscape_block(figures: dict[str, Path]) -> ReportBlock:
    return ReportBlock(
        block_id="objective_landscape",
        title="Fonction objectif dans l'espace des parametres",
        level="standard",
        lead=(
            "Lecture de la fonction objectif dans le plan (mK, Sy), avec cartes "
            "2D et coupes autour de la cible."
        ),
        figures=(
            ReportFigure(
                "objective_parameter_maps",
                "Objectifs flux, reseau et combine",
                figures.get("objective_parameter_maps"),
                "Echelle logarithmique; blancs pour simulations absentes ou non terminees.",
                required=False,
            ),
            ReportFigure(
                "objective_profile_cuts",
                "Coupes autour de la cible",
                figures.get("objective_profile_cuts"),
                "Coupes a mK cible et Sy cible.",
                required=False,
            ),
        ),
    )


def _hydrographic_network_block(figures: dict[str, Path]) -> ReportBlock:
    return ReportBlock(
        block_id="hydrographic_network",
        title="Cartes de drainage vis-a-vis de la cible",
        level="standard",
        lead=("Comparaison spatiale entre le reseau cible et le meilleur candidat non cible."),
        figures=(
            ReportFigure(
                "outflow_drain_maps",
                "Cible et meilleur candidat sur fond topographique",
                figures.get("outflow_drain_maps"),
                "Drainage actif en couleur, cellules inactives en gris transparent.",
                required=False,
            ),
        ),
    )


def _flow_timeseries_block(figures: dict[str, Path]) -> ReportBlock:
    return ReportBlock(
        block_id="flow_timeseries",
        title="Chroniques de flux",
        level="standard",
        lead="Comparaison des chroniques Q_total_release candidates et de la cible.",
        figures=(
            ReportFigure(
                "q_total_release_timeseries",
                "Q_total_release mensuel",
                figures.get("q_total_release_timeseries"),
                "Somme de tous les flux outflow_drain sortant du domaine.",
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
        links.append(ReportLink("Package de reference", truth_dir, "truth"))
    if score_table is not None:
        links.append(ReportLink("Table de scores", score_table, "score"))
    links.extend(ReportLink(path.name, path, "figure") for _, path in sorted(figures.items()))
    rows = (
        {"kind": "available", "items": ", ".join(artifact_report.available)},
        {"kind": "required_missing", "items": ", ".join(artifact_report.required_missing)},
        {"kind": "optional_missing", "items": ", ".join(artifact_report.optional_missing)},
    )
    return ReportBlock(
        block_id="artifact_links",
        title="Artefacts",
        level="audit",
        tables=(
            key_value_table(
                "artifact_contract",
                "Contrat artefacts",
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
