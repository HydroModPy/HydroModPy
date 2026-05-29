"""HTML section builders and metric summaries for the network/transient report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.calibration.reporting.network_transient.io import (
    NetworkTransientHtmlArtifactReport,
)
from hydromodpy.calibration.reporting.network_transient.io import (
    coerce_float as _float,
)
from hydromodpy.calibration.reporting.network_transient.io import (
    fmt_float as _fmt,
)
from hydromodpy.calibration.reporting.network_transient.io import (
    read_csv as _read_csv,
)
from hydromodpy.calibration.reporting.network_transient.io import (
    read_json as _read_json,
)
from hydromodpy.calibration.reporting.network_transient.io import (
    read_toml as _read_toml,
)
from hydromodpy.results.html_helpers import link_relative, safe_html

__all__ = [
    "artifact_contract_summary",
    "best_candidate_summary",
    "build_page",
    "conductivity_context",
    "configuration_metrics",
    "figure_card",
    "q_total_release_series",
    "score_catalog_path",
    "score_file_path",
    "source_k_values",
    "truth_label",
]


def _report_module():
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html


def build_page(
    *,
    normalization: dict[str, Any],
    score_rows: list[dict[str, str]],
    figures: dict[str, Path],
    truth_dir: Path | None,
    score_table: Path | None,
    artifact_report: NetworkTransientHtmlArtifactReport,
    page_title: str,
    web_root: Path,
) -> str:
    label = truth_label(truth_dir)
    score_label = link_relative(web_root, score_table) if score_table is not None else ""
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_html(page_title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --fg: #1f2933;
      --muted: #5d6875;
      --line: #d7dde5;
      --soft: #f4f7fa;
      --blue: #2662a5;
      --green: #26826a;
      --red: #b5413c;
      --orange: #b66a1f;
    }}
    body {{
      margin: 0;
      font: 15px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--fg);
      background: #ffffff;
    }}
    header {{
      padding: 24px 30px 16px;
      border-bottom: 1px solid var(--line);
    }}
    main {{
      padding: 18px 30px 34px;
      display: grid;
      gap: 22px;
    }}
    h1, h2, h3 {{ margin: 0; line-height: 1.2; }}
    h1 {{ font-size: 25px; }}
    h2 {{ font-size: 19px; }}
    h3 {{ font-size: 15px; margin-bottom: 8px; }}
    p {{ margin: 7px 0 0; color: var(--muted); }}
    code {{ background: #eef2f5; padding: 1px 4px; border-radius: 4px; }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 7px 8px;
      text-align: right;
      white-space: nowrap;
    }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ background: var(--soft); font-weight: 650; color: #2c3744; }}
    .lead {{ max-width: 1050px; font-size: 15px; }}
    .equation {{
      margin-top: 12px;
      padding: 10px 12px;
      background: var(--soft);
      border-left: 4px solid var(--blue);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #26313d;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(285px, 1fr));
      gap: 16px;
      align-items: start;
    }}
    .wide-grid {{
      display: grid;
      grid-template-columns: minmax(330px, 0.85fr) minmax(460px, 1.15fr);
      gap: 16px;
      align-items: start;
    }}
    @media (max-width: 920px) {{ .wide-grid {{ grid-template-columns: 1fr; }} }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px;
      overflow-x: auto;
    }}
    .metric-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .metric {{
      border-left: 3px solid var(--blue);
      background: var(--soft);
      padding: 7px 9px;
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ font-size: 15px; }}
    .figure-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 14px;
      align-items: start;
      margin-top: 12px;
    }}
    .figure-card {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fff;
    }}
    .figure-card img {{
      display: block;
      width: 100%;
      height: auto;
    }}
    .caption {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 7px;
    }}
    .note {{ color: var(--muted); font-size: 12px; margin-top: 8px; }}
    .muted {{ color: var(--muted); }}
    svg {{ max-width: 100%; height: auto; }}
  </style>
</head>
<body>
  <header>
    <h1>{safe_html(page_title)}</h1>
    <p class="lead">Diagnostic reproductible de calibration. La cible synthetique est construite avec <code>{safe_html(label)}</code>; les autres simulations sont lues comme candidats dans la table de score.</p>
  </header>
  <main>
    <section class="panel">
      <h2>Probleme de calibration</h2>
      <p>On cherche deux parametres globaux: le multiplicateur de conductivite hydraulique <code>mK</code> et le stockage specifique libre <code>Sy</code>. Le permanent sert a definir le reseau de drainage/affleurement cible, puis le transitoire mensuel compare la chronique de flux total <code>Q_total_release</code>.</p>
      <div class="equation">J(mK, Sy) = 0.5 C_reseau_phys(mK) + 0.5 C_debit_phys(mK, Sy)</div>
      {best_candidate_summary(score_rows, truth_dir)}
      <p class="note">Normalisation et reference: <code>{safe_html(str(truth_dir or ""))}</code>. Table de scores: <code>{safe_html(score_label)}</code>.</p>
      {artifact_contract_summary(artifact_report)}
    </section>

    <section class="wide-grid">
      <div class="panel">
        <h2>Configuration spatiale et temporelle</h2>
        {configuration_metrics(normalization, truth_dir)}
        <p class="note">Les axes des cartes de drainage ci-dessous sont exprimes en kilometres relatifs a l'exutoire.</p>
      </div>
      <div class="panel">
        <h2>Recharge imposee</h2>
        {figure_card(figures.get("recharge_chronicle"), "Chronique de recharge", "Recharge mensuelle issue de la configuration transitoire source; la moyenne sert aussi a construire le permanent de reference.", web_root=web_root)}
      </div>
    </section>

    <section class="panel">
      <h2>Contexte bassin et permanent cible</h2>
      <p>Le budget steady brut est peu explicite seul. La figure didactique rappelle que le bilan total ferme surtout le volume, tandis que le signal de calibration reseau vient de la repartition spatiale des cellules drainantes.</p>
      <div class="figure-grid">
        {figure_card(figures.get("watershed_id_card"), "Bassin, maillage et exutoire", "Carte d'identite reutilisee depuis les modules de diagnostic existants.", web_root=web_root)}
        {figure_card(figures.get("dem_context_map"), "Contexte topographique / DEM", "Le raster DEM est utilise quand il est present dans le catalogue. Sinon la figure indique et utilise le repli <code>z_top_mean</code> porte par le maillage.", web_root=web_root)}
        {figure_card(figures.get("steady_balance_didactic"), "Lecture didactique du permanent", "Bilan total du permanent cible et effet de mK sur Q_total_release et l'extension du drainage actif.", web_root=web_root)}
      </div>
    </section>

    <section class="panel">
      <h2>Fonction objectif dans l'espace des parametres</h2>
      <p>Les trois panneaux se lisent dans le plan <code>(mK, Sy)</code>: objectif sur les flux, objectif sur les affleurements/drainage, puis objectif combine. Les couleurs sont logarithmiques pour rendre visibles les faibles gradients pres de l'optimum et les valeurs elevees aux bords du domaine explore. L'etoile marque la valeur cible synthetique; le cercle rouge marque le minimum trouve. Les coupes 1D precisent ensuite quelle direction de parametre est la mieux contrainte.</p>
      <div class="figure-grid">
        {figure_card(figures.get("objective_parameter_maps"), "Objectifs flux, reseau et combine", "Echelle de couleur logarithmique. Les cases blanches correspondent aux simulations non terminees ou absentes de la grille.", web_root=web_root)}
        {figure_card(figures.get("objective_profile_cuts"), "Coupes autour de la cible", "Coupes a mK cible et Sy cible, avec les trois termes de cout en echelle logarithmique.", web_root=web_root)}
      </div>
    </section>

    <section class="panel">
      <h2>Cartes de drainage vis-a-vis de la cible</h2>
      <p>La carte de gauche est la cible synthetique. La carte de droite est le meilleur candidat non cible. Les valeurs actives de <code>outflow_drain</code> sont affichees sur une echelle logarithmique, au-dessus de la topographie, du contour de bassin et du reseau hydrographique en filigrane. L'affichage est limite aux bornes du bassin versant.</p>
      {figure_card(figures.get("outflow_drain_maps"), "Cible et meilleur candidat sur fond topographique", "Drainage actif en couleur, cellules inactives en gris transparent, axes en kilometres relatifs a l'exutoire.", web_root=web_root)}
    </section>

    <section class="panel">
      <h2>Chroniques de flux</h2>
      <p>La courbe noire est la cible synthetique. L'optimum calcule est en rouge. Toutes les autres chroniques candidates disponibles sont superposees en gris pour montrer l'amplitude de variabilite des flux.</p>
      {figure_card(figures.get("q_total_release_timeseries"), "Q_total_release mensuel", "Somme de tous les flux <code>outflow_drain</code> sortant du domaine a chaque periode.", web_root=web_root)}
    </section>
  </main>
</body>
</html>
"""


def truth_label(truth_dir: Path | None) -> str:
    if truth_dir is None:
        return "absent"
    metadata = _read_json(truth_dir / "metadata.json")
    mk = metadata.get("mK_true")
    sy = metadata.get("Sy_true")
    if mk is not None and sy is not None:
        return f"{truth_dir.name} (mK={mk}, Sy={sy})"
    return truth_dir.name


def artifact_contract_summary(report: NetworkTransientHtmlArtifactReport) -> str:
    required = len(report.required_missing)
    optional = len(report.optional_missing)
    warnings = len(report.contract_warnings)
    status = "complet" if report.ok else "incomplet"
    cells = [
        f'<div class="metric"><span>contrat artefacts</span><strong>{status}</strong></div>',
        f'<div class="metric"><span>manquants requis</span><strong>{required}</strong></div>',
        f'<div class="metric"><span>manquants optionnels</span><strong>{optional}</strong></div>',
        f'<div class="metric"><span>alertes contrat</span><strong>{warnings}</strong></div>',
    ]
    details: list[str] = []
    if report.required_missing or report.optional_missing:
        missing = list(report.required_missing) + list(report.optional_missing)
        details.append(
            '<p class="note">Artefacts absents ou non exploitables: '
            f"<code>{safe_html(', '.join(missing[:8]))}</code>"
            f"{' ...' if len(missing) > 8 else ''}</p>"
        )
    if report.contract_warnings:
        details.append(
            '<p class="note">Alertes non bloquantes du contrat B0: '
            f"<code>{safe_html(', '.join(report.contract_warnings[:8]))}</code>"
            f"{' ...' if len(report.contract_warnings) > 8 else ''}</p>"
        )
    return f'<div class="metric-row">{"".join(cells)}</div>{"".join(details)}'


def best_candidate_summary(score_rows: list[dict[str, str]], truth_dir: Path | None) -> str:
    completed = [row for row in score_rows if row.get("status") == "completed"]
    if not completed:
        return '<p class="note">Aucun candidat termine dans la table de score.</p>'
    failed_count = len([row for row in score_rows if row.get("status") != "completed"])
    best_candidates = [
        row for row in completed if not _report_module()._candidate_is_truth(row)
    ] or completed
    best = min(best_candidates, key=lambda row: _float(row.get("J"), float("inf")))
    target = _report_module()._truth_parameters(truth_dir)
    target_text = ""
    if target is not None:
        target_text = (
            f'<div class="metric"><span>valeur cible</span>'
            f"<strong>mK={_fmt(target[0], 2)}, Sy={_fmt(target[1], 3)}</strong></div>"
        )
    cells = [
        target_text,
        f'<div class="metric"><span>points termines</span><strong>{len(completed)} / {len(score_rows)}</strong></div>',
        f'<div class="metric"><span>points en echec</span><strong>{failed_count}</strong></div>',
        f'<div class="metric"><span>meilleur candidat non cible</span><strong>{safe_html(best.get("candidate_id", ""))}</strong></div>',
        f'<div class="metric"><span>mK trouve</span><strong>{_fmt(best.get("mK"), 2)}</strong></div>',
        f'<div class="metric"><span>Sy trouve</span><strong>{_fmt(best.get("Sy"), 3)}</strong></div>',
        f'<div class="metric"><span>J minimum</span><strong>{_fmt(best.get("J"), 5)}</strong></div>',
    ]
    return f'<div class="metric-row">{"".join(cell for cell in cells if cell)}</div>'


def configuration_metrics(normalization: dict[str, Any], truth_dir: Path | None) -> str:
    metadata = _read_json(truth_dir / "metadata.json") if truth_dir is not None else {}
    q_rows = _read_csv(truth_dir / "transient_q_total_release.csv") if truth_dir is not None else []
    active_count = ""
    if truth_dir is not None and (truth_dir / "steady_network_active_mask.npz").is_file():
        active = np.load(truth_dir / "steady_network_active_mask.npz")["active_mask"]
        active_count = str(int(np.asarray(active, dtype=bool).sum()))
    recharge = _report_module()._recharge_values_from_config()
    period_text = ""
    if q_rows:
        period_text = f"{q_rows[0].get('datetime', '')} -> {q_rows[-1].get('datetime', '')}"
    conductivity = conductivity_context(metadata)
    values = [
        ("site", metadata.get("site_id", "")),
        ("solveur", metadata.get("steady_solver", "modflow6")),
        ("cellules DISV", metadata.get("n_cells", "")),
        ("periodes debit", metadata.get("n_timesteps", "")),
        ("fenetre temporelle", period_text),
        ("pas de temps", "mensuel"),
        ("cellules drainantes cible", active_count),
        ("Q steady cible", f"{_fmt(normalization.get('Q_ref_steady'), 5)} m3/s"),
        ("Q moyen cible", f"{_fmt(normalization.get('Qbar_ref'), 5)} m3/s"),
        ("L reseau cible", f"{_fmt(normalization.get('L_ref'), 1)} m"),
        ("d_tol", f"{_fmt(normalization.get('d_tol'), 1)} m"),
        (
            "recharge moyenne",
            f"{_fmt(float(np.nanmean(recharge)) if recharge.size else np.nan, 3)} mm/j",
        ),
        ("K moyen cible", f"{_fmt(conductivity.get('K_mean_target'), 4)} m/s"),
        ("K median cible", f"{_fmt(conductivity.get('K_median_target'), 4)} m/s"),
        ("K moyen / R moyen", _fmt(conductivity.get("K_over_R_mean"), 2)),
    ]
    cells = []
    for label, value in values:
        cells.append(
            f'<div class="metric"><span>{safe_html(str(label))}</span>'
            f"<strong>{safe_html(str(value))}</strong></div>"
        )
    return f'<div class="metric-row">{"".join(cells)}</div>'


def conductivity_context(metadata: dict[str, Any]) -> dict[str, float]:
    mk = _float(metadata.get("mK_true"), 1.0)
    values = source_k_values()
    recharge = _report_module()._recharge_values_from_config()
    recharge_mean = float(np.nanmean(recharge)) if recharge.size else float("nan")
    recharge_m_s = recharge_mean * 1.0e-3 / 86400.0
    if values.size == 0:
        return {}
    k_mean = float(np.nanmean(values) * mk)
    k_median = float(np.nanmedian(values) * mk)
    return {
        "K_mean_target": k_mean,
        "K_median_target": k_median,
        "K_over_R_mean": k_mean / recharge_m_s if recharge_m_s > 0.0 else float("nan"),
    }


def source_k_values() -> np.ndarray:
    cfg = _read_toml(_report_module().SOURCE_TRANSIENT_CONFIG)
    flow = cfg.get("flow", {}) if isinstance(cfg.get("flow"), dict) else {}
    param = flow.get("param", {}) if isinstance(flow.get("param"), dict) else {}
    k_param = param.get("K", {}) if isinstance(param.get("K"), dict) else {}
    k_cfg = k_param.get("field", {}) if isinstance(k_param.get("field"), dict) else {}
    raw_path = k_cfg.get("values_csv_file")
    if not raw_path:
        return np.asarray([], dtype=float)
    path = Path(str(raw_path))
    if not path.is_absolute():
        path = (_report_module().SOURCE_TRANSIENT_CONFIG.parent / path).resolve()
    rows = _read_csv(path)
    return np.asarray([_float(row.get("K_value")) for row in rows], dtype=float)


def figure_card(path: Path | None, title: str, caption: str, *, web_root: Path) -> str:
    if path is None or not path.is_file():
        return (
            f'<div class="figure-card"><h3>{safe_html(title)}</h3>'
            '<p class="muted">Figure non disponible pour cette relance.</p></div>'
        )
    href = safe_html(link_relative(web_root, path))
    return (
        f'<figure class="figure-card"><h3>{safe_html(title)}</h3>'
        f'<a href="{href}"><img src="{href}" alt="{safe_html(title)}"></a>'
        f'<figcaption class="caption">{caption}</figcaption></figure>'
    )


def q_total_release_series(**kwargs) -> dict[str, list[float]]:
    return _report_module()._q_total_release_series(**kwargs)


def score_catalog_path(raw: Any) -> Path | None:
    return _report_module()._score_catalog_path(raw)


def score_file_path(raw: Any) -> Path | None:
    return _report_module()._score_file_path(raw)
