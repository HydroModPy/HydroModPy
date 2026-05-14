"""Modular sections for static comparison web reports."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.web.context import ComparisonWebContext
from hydromodpy.analysis.comparison.web.html_utils import (
    link_relative,
    render_links,
    safe,
    short,
)
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


@dataclass(frozen=True)
class ReportSection:
    """One independently rendered block of the comparison report."""

    section_id: str
    title: str
    priority: int
    render: Callable[[ComparisonWebContext], str]
    is_available: Callable[[ComparisonWebContext], bool] = lambda _ctx: True


def default_sections() -> list[ReportSection]:
    """Return the standard section set for a comparison report."""
    return [
        ReportSection(
            "introduction",
            "Introduction",
            10,
            _render_introduction,
        ),
        ReportSection(
            "case_configuration",
            "Contexte du cas",
            20,
            _render_case_configuration,
            lambda ctx: bool(ctx.configuration_figures),
        ),
        ReportSection(
            "numerical_methods",
            "Methodes numeriques",
            25,
            _render_numerical_methods,
        ),
        ReportSection(
            "categorized_figures",
            "Comparaisons de resultats",
            30,
            _render_categorized_figures,
            lambda ctx: bool(ctx.figure_categories),
        ),
        ReportSection(
            "numerical_closure",
            "Precision de resolution",
            45,
            _render_numerical_closure,
            lambda ctx: bool(ctx.numerical_closure_rows),
        ),
        ReportSection("metrics", "Metriques principales", 50, _render_metrics),
        ReportSection(
            "coherence_analysis",
            "Lecture physique des ecarts",
            55,
            _render_coherence_analysis,
            _has_head_error_metrics,
        ),
        ReportSection("simulations", "Simulations", 60, _render_simulations),
        ReportSection("audit", "Audit format", 70, _render_audit),
        ReportSection("files", "Fichiers", 80, _render_files),
    ]


def render_sections(ctx: ComparisonWebContext) -> str:
    """Render all available default report sections."""
    blocks: list[str] = []
    for section in sorted(default_sections(), key=lambda item: item.priority):
        if section.is_available(ctx):
            blocks.append(section.render(ctx))
    return "\n\n".join(blocks)


def report_title(ctx: ComparisonWebContext) -> str:
    """Return a readable report title."""
    payload = ctx.manifest
    explicit = payload.get("title") or payload.get("comparison_title")
    if explicit:
        return str(explicit)
    comparison_id = str(payload.get("comparison_id", "")).strip()
    if "synthetic_patchy" in comparison_id:
        return "Comparaison synthetique MF6 / Boussinesq - recharge heterogene"
    return comparison_id.replace("_", " ") or "Rapport de comparaison"


def render_header(ctx: ComparisonWebContext) -> str:
    """Render the report header."""
    payload = ctx.manifest
    if _is_synthetic_patchy(ctx):
        subtitle = (
            "Cas synthetique 2D a geometrie carree, aquifere heterogene, "
            "drainage de surface et recharge mensuelle longue. L'objectif est "
            "de comparer une reference MODFLOW 6 et un candidat Boussinesq sur "
            "les charges, le stockage global et le bilan externe."
        )
    else:
        subtitle = (
            "Rapport de comparaison entre simulations. Les figures et metriques "
            "sont limitees aux observables declares dans la configuration."
        )
    return f"""
  <header>
    <h1>{safe(report_title(ctx))}</h1>
    <p>{safe(subtitle)}</p>
    <div class="pillrow">
      <span class="pill">Audit: {safe(payload.get("audit_status", ctx.audit.get("status", "")))}</span>
      <span class="pill">Reference: {safe(payload.get("reference_simulation", ""))}</span>
    </div>
  </header>
"""


def _render_introduction(ctx: ComparisonWebContext) -> str:
    if not _is_synthetic_patchy(ctx):
        return """
  <section>
    <div class="card">
      <h2>Introduction</h2>
      <p>Ce rapport compare plusieurs simulations sur une selection d'observables communes. La lecture principale est limitee aux grandeurs ayant le meme sens physique entre les methodes.</p>
    </div>
  </section>
"""

    rows = _synthetic_context_rows(_base_config_payload(ctx))
    return f"""
  <section>
    <div class="card">
      <h2>Introduction</h2>
      <p>Le cas est un aquifere synthetique libre, en plan 2D, pose sur un domaine carre d'environ 5,0 km par 5,0 km. La topographie est un plan incline avec environ 20 m de denivele lateral et une epaisseur aquifere constante de 80 m.</p>
      <p>Le milieu est volontairement heterogene: trois bandes geologiques verticales traversent tout le domaine. Elles imposent une zone ouest peu conductrice, un couloir central plus conducteur et une zone est de conductivite intermediaire.</p>
      <p>La comparaison cherche a verifier que la methode Boussinesq reproduit, sur le meme maillage genere et sous la meme recharge, les charges hydrauliques, le stockage global et le bilan externe obtenus avec MODFLOW 6.</p>
      <div class="info-grid">
        {_render_key_values(rows)}
      </div>
      <p>Les flux natifs par processus ne sont pas affiches comme figures de comparaison, car ils ne representent pas toujours le meme objet numerique. Les sorties sont donc relues a travers des grandeurs globales alignees physiquement.</p>
      <p>Pour Boussinesq, la sortie globale peut etre deduite du bilan lorsque le flux de limite n'est pas expose comme composante native; elle est alors identifiee par <code>balance_implied_outflow_total_m3_s</code>.</p>
    </div>
  </section>
"""


def _render_persistence_contract(_ctx: ComparisonWebContext) -> str:
    return """
  <section>
    <div class="card">
      <h2>Persistance des sorties</h2>
      <p>Les simulations enfants ecrivent leurs resultats dans leur catalogue de simulation. La comparaison est une surcouche: elle ecrit des artefacts HTML, CSV, JSON et PNG dans le dossier de comparaison.</p>
      <p><code>comparison_manifest.json</code> joue le role d'index local: il reference les figures, donnees derivees, rapports et dossiers enfants.</p>
      <p class="muted">Ce choix evite de transformer un rapport de comparaison en simulation artificielle. Si l'on veut faire des requetes globales sur des centaines de comparaisons, il faudra ajouter un catalogue de comparaisons dedie.</p>
    </div>
  </section>
"""


def _render_audit(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <div class="card">
      <h2>Audit format</h2>
      {_audit_block(ctx.audit)}
    </div>
  </section>
"""


def _render_case_configuration(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <h2>Contexte du cas</h2>
    <p class="muted">Support, zones geologiques, points de comparaison, forcages et contexte spatial utilises par les deux simulations. Cette figure est volontairement plus grande que les resultats pour poser le cas avant la comparaison.</p>
    <div class="figure-grid context-figure-grid">
      {_render_figures(ctx=ctx, figures=ctx.configuration_figures)}
    </div>
  </section>
"""


def _render_numerical_methods(ctx: ComparisonWebContext) -> str:
    payload = _base_config_payload(ctx)
    flow = _mapping(payload.get("flow"))
    simulation_payloads = _simulation_config_payloads(ctx)
    mf6_flow = _flow_payload_for_solver(simulation_payloads, "modflow6") or flow
    bouss_flow = _flow_payload_for_solver(simulation_payloads, "boussinesq") or flow
    mf6 = _mapping(payload.get("modflow6"))
    mf6_runtime = _mapping(mf6.get("runtime"))
    mf6_sgrid = _mapping(_mapping(mf6.get("sgrid")).get("vertical"))
    bouss_method = _boussinesq_method_text(bouss_flow)
    hydraulic_rows = [
        ("Regime hydraulique", _format_value(flow.get("flow_regime"), default="transient")),
        ("Recharge transitoire", _recharge_text(flow)),
        ("Conditions initiales", _initial_condition_text(flow)),
        ("Conditions aux limites MODFLOW 6", _boundary_condition_text(mf6_flow)),
        (
            "Conditions aux limites Boussinesq",
            _boundary_condition_text(bouss_flow, solver="boussinesq"),
        ),
        (
            "Proprietes hydrauliques",
            "K et Sy heterogenes par zones geologiques; Ss homogene; "
            "epaisseur aquifere constante dans le cas synthetique.",
        ),
    ]
    numerical_rows = [
        (
            "MODFLOW 6",
            "reference volumes finis/volumes de controle sur maillage DISV; "
            f"{_format_value(mf6_sgrid.get('nlay'), default='1')} couche; "
            f"IMS {_format_value(mf6_runtime.get('mf6_ims_complexity'), default='COMPLEX')}; "
            f"dvclose={_format_value(mf6_runtime.get('mf6_inner_dvclose'), default='1e-4')}",
        ),
        (
            "Boussinesq",
            bouss_method,
        ),
        (
            "Discretisation spatiale",
            "maillage genere a chaque simulation par mesh_catchment, conforme aux "
            "interfaces geologiques; aucun maillage preexistant n'est fourni au solveur.",
        ),
    ]
    return f"""
  <section>
    <div class="card">
      <h2>Methodes numeriques</h2>
      <p>Les deux simulations suivent le chemin standard HydroModPy: preparation des donnees, generation du maillage, assemblage solveur, calcul, extraction des observables et generation du rapport. Les choix hydrauliques sont separes ci-dessous des choix strictement numeriques.</p>
      <h3>Configuration hydraulique et conditions aux limites</h3>
      <div class="info-grid">
        {_render_key_values(hydraulic_rows)}
      </div>
      <h3>Parametrage numerique</h3>
      <div class="info-grid">
        {_render_key_values(numerical_rows)}
      </div>
    </div>
  </section>
"""


def _render_categorized_figures(ctx: ComparisonWebContext) -> str:
    category_blocks: list[str] = []
    for category in ctx.figure_categories:
        if category.category_id == "configuration":
            continue
        category_blocks.append(
            f"""
    <article class="card figure-category category-{safe(category.category_id)}" id="figures-{safe(category.category_id)}">
      <h3>{safe(category.title)} <span class="muted">({safe(len(category.figures))})</span></h3>
      <p class="muted">{safe(category.description)}</p>
      <div class="figure-grid compact">
        {_render_figures(ctx=ctx, figures=category.figures)}
      </div>
    </article>
"""
        )
    if not category_blocks:
        return """
  <section>
    <h2>Comparaisons de resultats</h2>
    <p class="muted">Aucune figure de resultat hors configuration.</p>
  </section>
"""
    return f"""
  <section>
    <h2>Comparaisons de resultats</h2>
    <p class="muted">Une seule carte de charge est conservee, avec les chroniques ponctuelles. Le stockage global et le bilan entrees/sorties sont affiches separement.</p>
    {"".join(category_blocks)}
  </section>
"""


def _render_simulations(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <div class="card">
      <h2>Simulations</h2>
      <p class="muted">Temps de resolution de la partie flow uniquement, releves dans les metriques solver. Les phases de preparation, maillage, extraction et rendu ne sont pas incluses dans cette comparaison.</p>
      {_render_runtime_table(ctx.simulations)}
    </div>
  </section>
"""


def _render_files(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <div class="card">
      <h2>Fichiers sources</h2>
      {render_links(root=ctx.root, web_dir=ctx.web_dir, links=ctx.data_links)}
    </div>
  </section>
"""


def _render_comparable_flux(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <h2>Flux sortant agrege</h2>
    <p class="muted">Grandeur commune seulement si les composantes agregees representent le meme processus de sortie. Si le flux de limite n'est pas disponible nativement, la sortie comparable peut etre deduite du bilan et doit rester libellee comme telle.</p>
    {_render_table(ctx.comparable_budget_rows[:16], [("time_label", "temps"), ("period_index", "periode"), ("value__mf6_ref", "mf6_ref"), ("value__bouss_candidate", "bouss_candidate")], empty="Aucune ligne comparable_outflow_total_m3_s trouvee. Consulter alors balance_implied_outflow_total_m3_s dans budget_timeseries_long.csv.")}
  </section>
"""


def _render_numerical_closure(ctx: ComparisonWebContext) -> str:
    rows = _format_closure_rows(ctx.numerical_closure_rows)
    columns = [
        ("simulation_id", "simulation"),
        ("solver", "solveur"),
        ("n_periods", "periodes"),
        ("max_abs_closure_m3_s", "max |residu| debit"),
        ("max_abs_closure_mm_d", "max |residu| lame"),
        ("relative_closure_error_p95", "erreur rel. p95"),
        ("diagnostic", "avis"),
    ]
    return f"""
  <section>
    <div class="card">
      <h2>Precision de resolution</h2>
      <p class="muted">Diagnostic commun calcule apres coup sur les budgets normalises: entrees moins sorties moins variation de stockage. Il ne remplace pas les criteres internes des solveurs, mais indique si l'etat accepte ferme correctement le bilan d'eau.</p>
      {_render_table(rows, columns, empty="Aucun diagnostic de fermeture du bilan.")}
    </div>
  </section>
"""


def _render_metrics(ctx: ComparisonWebContext) -> str:
    rows = _format_metric_rows(ctx.metrics_rows[:24])
    return f"""
  <section>
    <h2>Metriques principales</h2>
    <p class="muted">Lecture compacte des ecarts sur les observables communes. Les unites sont explicites: les charges sont en metres, et le pourcentage correspond a <code>RMSE / valeur ref</code>. Ici, <code>valeur ref</code> est l'amplitude de la grandeur de reference utilisee pour normaliser l'observable.</p>
    {_render_metric_snapshot(rows)}
  </section>
"""


def _render_metric_snapshot(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<p class="muted">Aucune metrique.</p>'
    numeric_rows = [_metric_snapshot_row(row) for row in rows]
    percentages = [
        item["rmse_percent_value"]
        for item in numeric_rows
        if item["rmse_percent_value"] is not None
    ]
    scale = max(5.0, max(percentages, default=0.0))
    best = min(
        (item for item in numeric_rows if item["rmse_percent_value"] is not None),
        key=lambda item: item["rmse_percent_value"],
        default=None,
    )
    worst = max(
        (item for item in numeric_rows if item["rmse_percent_value"] is not None),
        key=lambda item: item["rmse_percent_value"],
        default=None,
    )
    summary = ""
    if best is not None and worst is not None:
        summary = (
            '<div class="metric-summary">'
            f'<div><span class="kv-label">Plus proche</span><strong>{safe(best["observable_label"])}</strong><small>{safe(best["rmse_percent"])}</small></div>'
            f'<div><span class="kv-label">Ecart max</span><strong>{safe(worst["observable_label"])}</strong><small>{safe(worst["rmse_percent"])}</small></div>'
            f'<div><span class="kv-label">Reference</span><strong>MF6</strong><small>valeur ref en {safe(best["unit"] or "unite")}</small></div>'
            "</div>"
        )
    body_rows: list[str] = []
    for item in numeric_rows:
        value = item["rmse_percent_value"]
        width = 0.0 if value is None or scale == 0 else max(2.0, min(100.0, 100.0 * value / scale))
        body_rows.append(
            "<tr>"
            f"<td>{safe(item['observable_label'])}</td>"
            f"<td>{safe(item['n_pairs'])}</td>"
            f"<td>{safe(item['rmse'])}</td>"
            f"<td>{safe(item['reference_value'])}</td>"
            "<td>"
            f"<strong>{safe(item['rmse_percent'])}</strong>"
            '<div class="metric-bar-track">'
            f'<span class="metric-bar" style="width: {width:.1f}%"></span>'
            "</div>"
            "</td>"
            "</tr>"
        )
    table = (
        '<table class="metric-table"><thead><tr>'
        "<th>observable</th><th>n</th><th>RMSE</th><th>valeur ref</th><th>RMSE / ref</th>"
        f"</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )
    return summary + table


def _metric_snapshot_row(row: Mapping[str, Any]) -> dict[str, Any]:
    unit = str(row.get("unit", "") or "").strip()
    rmse_value = _float_or_none(row.get("rmse"))
    reference_value = _float_or_none(row.get("normalization_scale"))
    rmse_percent = _float_or_none(row.get("rmse_normalized_percent"))
    return {
        "observable_label": str(row.get("observable_label") or row.get("observable") or ""),
        "n_pairs": str(row.get("n_pairs", "")),
        "unit": unit,
        "rmse": _format_with_unit(rmse_value, unit),
        "reference_value": _format_with_unit(reference_value, unit),
        "rmse_percent": _format_percent_value(rmse_percent),
        "rmse_percent_value": rmse_percent,
    }


def _render_coherence_analysis(ctx: ComparisonWebContext) -> str:
    head_rows = [
        _metric_analysis_row(row)
        for row in ctx.metrics_rows
        if str(row.get("observable", "")).startswith("head")
    ]
    head_rows = [row for row in head_rows if row["rmse_percent"] is not None]
    if not head_rows:
        return ""
    first = _analysis_row_by_token(head_rows, "first")
    wet = _analysis_row_by_token(head_rows, "wet")
    dry = _analysis_row_by_token(head_rows, "dry")
    last = _analysis_row_by_token(head_rows, "last")
    best = min(head_rows, key=lambda item: item["rmse_percent"])
    worst = max(head_rows, key=lambda item: item["rmse_percent"])
    max_percent = float(worst["rmse_percent"] or 0.0)
    if max_percent < 2.0:
        verdict = "accord tres serre"
    elif max_percent < 5.0:
        verdict = "accord globalement bon"
    elif max_percent < 10.0:
        verdict = "coherence globale avec ecarts notables"
    else:
        verdict = "ecarts marques a investiguer"

    evidence_rows = [
        ("Meilleur accord", _analysis_row_text(best)),
        ("Ecart le plus fort", _analysis_row_text(worst)),
    ]
    if first is not None:
        evidence_rows.append(("Premier pas calcule", _analysis_row_text(first)))
    if wet is not None:
        evidence_rows.append(("Apres saison humide", _analysis_row_text(wet)))
    if dry is not None:
        evidence_rows.append(("Etat sec", _analysis_row_text(dry)))
    if last is not None:
        evidence_rows.append(("Etat final", _analysis_row_text(last)))

    messages = [
        (
            f"Sur les charges comparees, ce cas presente {verdict}: la RMSE normalisee "
            f"va de {_format_percent_value(best['rmse_percent'])} a "
            f"{_format_percent_value(worst['rmse_percent'])}."
        ),
        (
            "Les ecarts les plus faibles apparaissent en general au debut ou juste apres "
            "un episode humide: la nappe est alors davantage controlee par la recharge "
            "et par le champ de conductivite commun aux deux solveurs."
        ),
        (
            "Les ecarts augmentent quand l'etat devient plus sec ou plus proche de la "
            "surface. C'est la zone la plus sensible aux differences de formulation: "
            "MODFLOW 6 accepte des charges au-dessus du toit et represente le drainage "
            "par une conductance de drain, alors que le calcul Boussinesq utilise une "
            "formulation nappe libre avec obstacle de surface et un traitement de drainage "
            "different."
        ),
        (
            "Les cas synthetiques restent le repere de coherence: support, geometrie, "
            "forcage et observables y sont controles, donc les ecarts doivent surtout "
            "venir de la formulation numerique et des termes de flux non strictement "
            "identiques. Les cas naturels ajoutent topographie, geologie et contrastes "
            "locaux; ils amplifient donc les differences la ou la nappe interagit avec "
            "le toit, les drains et les zones de forte pente."
        ),
    ]
    return f"""
  <section>
    <div class="card">
      <h2>Lecture physique des ecarts</h2>
      {_render_key_values(evidence_rows)}
      {"".join(f"<p>{safe(message)}</p>" for message in messages)}
    </div>
  </section>
"""


def _has_head_error_metrics(ctx: ComparisonWebContext) -> bool:
    return any(
        str(row.get("observable", "")).startswith("head")
        and _float_or_none(row.get("rmse_normalized_percent")) is not None
        for row in ctx.metrics_rows
    )


def _metric_analysis_row(row: Mapping[str, Any]) -> dict[str, Any]:
    observable = str(row.get("observable", ""))
    return {
        "observable": observable,
        "label": _observable_label(observable),
        "rmse": _float_or_none(row.get("rmse")),
        "rmse_percent": _float_or_none(row.get("rmse_normalized_percent")),
        "unit": str(row.get("unit", "") or "").strip(),
    }


def _analysis_row_by_token(
    rows: list[dict[str, Any]],
    token: str,
) -> dict[str, Any] | None:
    token = token.lower()
    for row in rows:
        if token in str(row["observable"]).lower():
            return row
    return None


def _analysis_row_text(row: Mapping[str, Any]) -> str:
    return (
        f"{row['label']} - RMSE {_format_with_unit(row.get('rmse'), str(row.get('unit') or ''))} "
        f"({_format_percent_value(row.get('rmse_percent'))})"
    )


def _render_figures(
    *,
    ctx: ComparisonWebContext,
    figures: list[Mapping[str, Any]],
) -> str:
    blocks: list[str] = []
    for item in figures:
        path = Path(str(item.get("path", "")))
        if not path.is_file():
            continue
        title = Path(path).name
        kind = item.get("kind", "")
        caption = _figure_caption(item)
        blocks.append(
            "<figure>"
            f'<a href="{safe(link_relative(ctx.web_dir, path))}">'
            f'<img src="{safe(link_relative(ctx.web_dir, path))}" alt="{safe(title)}">'
            "</a>"
            f"<figcaption>{safe(caption)}"
            + (
                f'<br><span class="muted">{safe(title)}'
                + (f" - {safe(kind)}" if kind else "")
                + "</span>"
            )
            + "</figcaption></figure>"
        )
    if not blocks:
        return '<p class="muted">Aucune figure PNG disponible.</p>'
    return "\n".join(blocks)


def _base_config_payload(ctx: ComparisonWebContext) -> dict[str, Any]:
    raw_path = ctx.manifest.get("base_simulation_config")
    if raw_path in (None, ""):
        return {}
    config_path = _existing_config_path(Path(str(raw_path)), ctx=ctx)
    if config_path is None:
        return {}
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _simulation_config_payloads(
    ctx: ComparisonWebContext,
) -> list[tuple[Mapping[str, Any], dict[str, Any]]]:
    payloads: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for simulation in ctx.simulations:
        raw_path = simulation.get("config_path")
        if raw_path in (None, ""):
            continue
        config_path = _existing_config_path(Path(str(raw_path)), ctx=ctx)
        if config_path is None:
            continue
        try:
            payload = load_toml_with_base_config(config_path)
        except Exception:
            continue
        if isinstance(payload, dict):
            payloads.append((simulation, payload))
    return payloads


def _flow_payload_for_solver(
    simulation_payloads: list[tuple[Mapping[str, Any], dict[str, Any]]],
    solver: str,
) -> Mapping[str, Any] | None:
    solver_key = solver.strip().lower()
    for simulation, payload in simulation_payloads:
        if str(simulation.get("solver", "")).strip().lower() == solver_key:
            flow = _mapping(payload.get("flow"))
            if flow:
                return flow
    return None


def _existing_config_path(path: Path, *, ctx: ComparisonWebContext) -> Path | None:
    """Return an existing local path for a manifest config path."""
    candidates = [path]
    text = str(path).replace("\\", "/")
    if text.startswith("/mnt/") and len(text) > 6 and text[6] == "/":
        drive = text[5].upper()
        candidates.append(Path(f"{drive}:/" + text[7:]))
    if not path.is_absolute():
        candidates.append((ctx.root / path).resolve())
        candidates.append((ctx.root.parent / path).resolve())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _is_synthetic_patchy(ctx: ComparisonWebContext) -> bool:
    comparison_id = str(ctx.manifest.get("comparison_id", "")).lower()
    return "synthetic_patchy" in comparison_id


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _format_value(value: Any, *, default: str = "") -> str:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if math.isfinite(value):
            return f"{value:.3g}"
        return str(value)
    return str(value)


def _quantity_is_zero(value: Any) -> bool:
    if value in (None, ""):
        return False
    if isinstance(value, int | float):
        return math.isfinite(float(value)) and float(value) == 0.0
    token = str(value).strip().split(maxsplit=1)[0]
    try:
        return float(token) == 0.0
    except ValueError:
        return False


def _synthetic_context_rows(payload: Mapping[str, Any]) -> list[tuple[str, str]]:
    geographic = _mapping(payload.get("geographic"))
    synthetic = _mapping(geographic.get("synthetic"))
    grid = _mapping(synthetic.get("grid"))
    topography = _mapping(synthetic.get("topography"))
    domain = _mapping(payload.get("domain"))
    depth_model = _mapping(domain.get("depth_model"))
    flow = _mapping(payload.get("flow"))
    param = _mapping(flow.get("param"))
    k_values = _mapping(_mapping(param.get("K")).get("field_heterogeneous")).get("values", {})
    sy_values = _mapping(_mapping(param.get("Sy")).get("field_heterogeneous")).get("values", {})
    ss_value = _mapping(_mapping(param.get("Ss")).get("field_homogeneous")).get("value")
    recharge_values = _recharge_values(payload)
    recharge_text = "chronique mensuelle"
    if recharge_values:
        mean_recharge = sum(recharge_values) / len(recharge_values)
        recharge_text = (
            f"{len(recharge_values)} mois; moyenne {mean_recharge:.2g} mm/j; "
            f"min {min(recharge_values):.2g}; max {max(recharge_values):.2g}"
        )
    length_x = _format_value(grid.get("length_x"), default="5025 m")
    length_y = _format_value(grid.get("length_y"), default="5025 m")
    rows = [
        (
            "Geometrie",
            f"domaine carre {length_x} x {length_y}, grille source "
            f"{_format_value(grid.get('nx'), default='67')} x "
            f"{_format_value(grid.get('ny'), default='67')}, CRS "
            f"{_format_value(grid.get('crs'), default='EPSG:2154')}",
        ),
        (
            "Topographie",
            f"plan incline, altitude de base {_format_value(topography.get('base_elevation'), default='20')} m, denivele lateral {_format_value(topography.get('right_to_left_amplitude'), default='20')} m",
        ),
        (
            "Epaisseur",
            f"substratum a epaisseur constante {_format_value(depth_model.get('thickness'), default='80 m')}",
        ),
        (
            "Conductivite K",
            _format_mapping_values(
                k_values, default="heterogene: ouest 1e-5, centre 8e-5, est 3e-5 m/s"
            ),
        ),
        (
            "Stockage",
            f"Sy {_format_mapping_values(sy_values, default='heterogene')}; Ss {_format_value(ss_value, default='1e-5 m-1')}",
        ),
        ("Recharge", recharge_text),
        ("Conditions limites", _boundary_condition_text(flow)),
    ]
    return rows


def _format_mapping_values(value: Any, *, default: str) -> str:
    if not isinstance(value, Mapping) or not value:
        return default
    labels = {
        "west_low_k": "ouest",
        "central_high_k": "centre",
        "east_medium_k": "est",
    }
    parts = [
        f"{labels.get(str(key), str(key))}: {_format_value(raw)}" for key, raw in value.items()
    ]
    return "; ".join(parts)


def _recharge_values(payload: Mapping[str, Any]) -> list[float]:
    data = _mapping(payload.get("data"))
    recharge = _mapping(data.get("recharge"))
    sources = recharge.get("sources")
    if not isinstance(sources, list):
        return []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        values = source.get("values")
        if isinstance(values, list):
            out: list[float] = []
            for item in values:
                try:
                    out.append(float(item))
                except Exception:
                    return []
            return out
    return []


def _initial_condition_text(flow: Mapping[str, Any]) -> str:
    ic = _mapping(flow.get("ic"))
    ic_type = str(ic.get("type", "")).strip()
    if ic_type == "steady_state":
        backend = str(flow.get("runtime_backend", "")).strip().lower()
        surface = str(flow.get("surface_interaction_model", "")).strip().lower()
        if backend == "petsc" and surface == "vi_obstacle":
            return (
                "charge initiale issue d'un calcul permanent auxiliaire avec "
                "la recharge moyenne; pour Boussinesq, le permanent et le "
                "transitoire utilisent PETSc SNESVI avec la fermeture "
                "vi_obstacle directe"
            )
        if backend == "petsc" and surface == "ts_vi_obstacle":
            return (
                "charge initiale issue d'un calcul permanent auxiliaire avec "
                "la recharge moyenne; pour Boussinesq, ce permanent utilise "
                "PETSc SNESVI avec la fermeture vi_obstacle avant le "
                "transitoire PETSc TS/SNESVI"
            )
        return (
            "charge initiale issue d'un calcul permanent auxiliaire avec la "
            "recharge moyenne de la chronique, appliquee ensuite au transitoire"
        )
    if ic_type == "top_offset":
        return f"charge initiale egale au toit moins {_format_value(ic.get('value'), default='un offset')}"
    return f"type {_format_value(ic_type, default='non documente')}"


def _recharge_text(flow: Mapping[str, Any]) -> str:
    sinks_sources = _mapping(flow.get("sinks_sources"))
    recharge = _mapping(sinks_sources.get("recharge"))
    first_clim = _format_value(recharge.get("first_clim"), default="mean")
    negative_to_evt = _format_value(recharge.get("negative_to_evt"), default="false")
    return (
        "chronique mensuelle lue depuis la configuration de donnees; "
        f"premiere periode first_clim={first_clim}; "
        f"negative_to_evt={negative_to_evt}"
    )


def _boundary_condition_text(flow: Mapping[str, Any], *, solver: str = "") -> str:
    active_bc = flow.get("active_bc")
    active = [str(item) for item in active_bc] if isinstance(active_bc, list) else []
    if "east_side" in active:
        return "ancienne configuration avec charge imposee sur le bord est"
    if "drainage" in active:
        bc = _mapping(flow.get("bc"))
        drainage = _mapping(_mapping(bc.get("cauchy")).get("drainage"))
        if not drainage:
            drainage = _mapping(_mapping(bc.get("robin")).get("drainage"))
        value = _format_value(drainage.get("value"))
        if _quantity_is_zero(drainage.get("value")):
            if solver.strip().lower() == "boussinesq":
                return (
                    "pas de charge laterale imposee; drainage Cauchy declare "
                    "mais desactive par conductance nulle; obstacle libre "
                    "strict h <= z_top conserve"
                )
            return "drainage declare mais desactive par conductance nulle"
        suffix = f", conductance {value}" if value else ""
        return f"pas de charge laterale imposee; drainage de surface actif sur le toit{suffix}"
    if not active:
        if solver.strip().lower() == "boussinesq":
            return "aucune condition limite active; obstacle libre strict h <= z_top"
        return "aucune condition limite active, hors recharge"
    return ", ".join(active)


def _boussinesq_method_text(flow: Mapping[str, Any]) -> str:
    backend = str(flow.get("runtime_backend", "") or "").strip().lower()
    surface = str(flow.get("surface_interaction_model", "") or "").strip().lower()
    if backend == "petsc" and surface == "vi_obstacle":
        retry_text = (
            "; retry adaptatif active"
            if bool(flow.get("vi_substep_on_failure", False))
            else "; retry adaptatif desactive"
        )
        return (
            "modele 2D non lineaire en nappe libre sur le meme maillage; "
            "backend PETSc complet; surface_interaction_model=vi_obstacle; "
            "solveur PETSc SNESVI direct; "
            f"{_format_value(flow.get('vi_substeps_per_period'), default='4')} sous-pas par periode"
            f"{retry_text}; "
            f"tolerance residu={_format_value(flow.get('runtime_tol_residual_inf'), default='')}"
        )
    if backend == "petsc" and surface == "ts_vi_obstacle":
        return (
            "modele 2D non lineaire en nappe libre sur le meme maillage; "
            "backend PETSc complet; surface_interaction_model=ts_vi_obstacle; "
            f"PETSc TS {_format_value(flow.get('ts_vi_type'), default='beuler')}; "
            f"SNESVI {_format_value(flow.get('ts_vi_snes_type'), default='vinewtonrsls')}; "
            f"{_format_value(flow.get('ts_vi_steps_per_period'), default='4')} sous-pas TS par periode; "
            f"tolerance residu={_format_value(flow.get('runtime_tol_residual_inf'), default='')}"
        )
    return (
        "modele 2D non lineaire en nappe libre sur le meme maillage; "
        f"backend {_format_value(flow.get('runtime_backend'), default='scipy_sparse')}; "
        f"iterations max={_format_value(flow.get('runtime_max_iterations'), default='')}; "
        f"tolerance residu={_format_value(flow.get('runtime_tol_residual_inf'), default='')}"
    )


def _render_key_values(rows: list[tuple[str, str]]) -> str:
    return "\n".join(
        f'<div><span class="kv-label">{safe(label)}</span><strong>{safe(value)}</strong></div>'
        for label, value in rows
    )


def _render_table(
    rows: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    columns: list[tuple[str, str]],
    *,
    empty: str,
) -> str:
    materialized = list(rows)
    if not materialized:
        return f'<p class="muted">{safe(empty)}</p>'
    header = "".join(f"<th>{safe(label)}</th>" for _, label in columns)
    body_rows: list[str] = []
    for row in materialized:
        cells = "".join(f"<td>{safe(short(row.get(key, '')))}</td>" for key, _ in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _render_runtime_table(
    rows: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> str:
    materialized = list(rows)
    if not materialized:
        return '<p class="muted">Aucune simulation dans le manifeste.</p>'
    runtime_items = [_row_runtime_seconds_with_scope(row) for row in materialized]
    values = [item[0] for item in runtime_items]
    maximum = max([value for value in values if value is not None], default=None)
    body_rows: list[str] = []
    for row, (value, scope) in zip(materialized, runtime_items, strict=False):
        solver = str(row.get("solver", "") or "").strip().lower()
        bar_class = (
            "modflow6" if solver == "modflow6" else "boussinesq" if solver == "boussinesq" else ""
        )
        width = 0.0
        if value is not None and maximum not in (None, 0):
            width = max(2.0, min(100.0, 100.0 * value / maximum))
        runtime = _format_runtime_seconds(value)
        body_rows.append(
            "<tr>"
            f"<td>{safe(short(row.get('id', '')))}</td>"
            f"<td>{safe(short(row.get('solver', '')))}</td>"
            f"<td>{safe(short(row.get('status', '')))}</td>"
            f"<td>{safe(runtime)}</td>"
            f"<td>{safe(scope)}</td>"
            "<td>"
            '<div class="runtime-bar-track">'
            f'<span class="runtime-bar {safe(bar_class)}" style="width: {width:.1f}%"></span>'
            "</div>"
            "</td>"
            "</tr>"
        )
    return (
        '<table class="runtime-table"><thead><tr>'
        "<th>id</th><th>solver</th><th>status</th><th>temps</th><th>portee</th><th>comparaison</th>"
        f"</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def _row_runtime_seconds_with_scope(row: Mapping[str, Any]) -> tuple[float | None, str]:
    metrics = row.get("metrics")
    metrics_map = metrics if isinstance(metrics, Mapping) else {}
    boussinesq_summary = row.get("boussinesq_summary")
    boussinesq_map = boussinesq_summary if isinstance(boussinesq_summary, Mapping) else {}
    for candidate in (
        row.get("flow_solve_time_seconds"),
        metrics_map.get("flow_solve_time_seconds"),
        boussinesq_map.get("flow_solve_time_seconds"),
    ):
        seconds = _runtime_seconds(candidate)
        if seconds is not None:
            return seconds, "flow_solve"
    return None, ""


def _runtime_seconds(value: Any) -> float | None:
    try:
        seconds = float(value)
    except Exception:
        return None
    if not math.isfinite(seconds):
        return None
    return seconds


def _format_runtime_seconds(value: float | None) -> str:
    if value is None:
        return ""
    if value < 60.0:
        return f"{value:.1f} s"
    minutes = value / 60.0
    if minutes < 60.0:
        return f"{minutes:.1f} min"
    return f"{minutes / 60.0:.2f} h"


def _format_metric_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    formatted: list[dict[str, str]] = []
    for row in rows:
        item = dict(row)
        item["observable_label"] = _observable_label(str(row.get("observable", "")))
        for key in (
            "mae",
            "rmse",
            "max_abs_error",
            "normalization_scale",
            "mae_normalized_percent",
            "rmse_normalized_percent",
            "max_abs_error_normalized_percent",
        ):
            item[key] = _format_number(row.get(key))
        formatted.append(item)
    return formatted


def _format_closure_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    formatted: list[dict[str, str]] = []
    for row in rows:
        item = dict(row)
        item["max_abs_closure_m3_s"] = _format_with_unit(row.get("max_abs_closure_m3_s"), "m3/s")
        item["max_abs_closure_mm_d"] = _format_with_unit(row.get("max_abs_closure_mm_d"), "mm/j")
        item["relative_closure_error_p95"] = _format_number(row.get("relative_closure_error_p95"))
        formatted.append(item)
    return formatted


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value if value is not None else "")
    if not math.isfinite(number):
        return ""
    if abs(number) > 0 and abs(number) < 0.01:
        return f"{number:.1e}"
    return f"{number:.1f}"


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _format_with_unit(value: Any, unit: str) -> str:
    number = _float_or_none(value)
    if number is None:
        return ""
    formatted = _format_number(number)
    return f"{formatted} {unit}".strip()


def _format_percent_value(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return ""
    return f"{_format_number(number)} %"


def _observable_label(name: str) -> str:
    labels = {
        "head_map_initial": "champ de charge initial",
        "head_map_first_computed": "champ de charge au premier pas calcule",
        "head_map_wet_year1": "champ de charge apres la premiere saison humide",
        "head_map_dry_late": "champ de charge en etat sec tardif",
        "head_map_drought_year2": "champ de charge en fin de periode seche",
        "head_map_extreme_recharge": "champ de charge pendant le pic de recharge",
        "head_map_last": "champ de charge final",
        "head_west_low_k_series": "chronique de charge dans la zone ouest peu conductrice",
        "head_west_interface_series": "chronique de charge pres de l'interface ouest/centre",
        "head_central_high_k_series": "chronique de charge dans le couloir central conducteur",
        "head_east_interface_series": "chronique de charge pres de l'interface centre/est",
        "head_east_medium_k_series": "chronique de charge dans la zone est intermediaire",
        "head_domain_low_series": "chronique de charge dans la partie basse du domaine",
        "head_domain_mid_series": "chronique de charge dans la partie mediane du domaine",
        "head_domain_high_series": "chronique de charge dans la partie haute du domaine",
    }
    return labels.get(name, name.replace("_", " "))


def _figure_caption(item: Mapping[str, Any]) -> str:
    observable = str(item.get("observable", ""))
    kind = str(item.get("kind", ""))
    if observable == "case_configuration":
        return "Contexte du cas: geometrie, zones K, recharge et points d'extraction."
    if kind == "fine_raster_map_comparison":
        return (
            _observable_label(observable) + ": reference et candidat sur la meme grille interpolee."
        )
    if "triptych" in kind or "head_map" in observable:
        return _observable_label(observable) + ": reference, candidat et ecart."
    if kind == "timeseries" or observable.endswith("_series"):
        point_label = str(item.get("point_label", "")).strip()
        prefix = f"Point {point_label} - " if point_label else ""
        return prefix + _observable_label(observable) + ": comparaison temporelle MF6 / Boussinesq."
    if observable in {"storage_change_total_m3_s", "storage_comparison_dashboard"}:
        return "Stockage global: variation instantanee du volume stocke dans l'aquifere."
    if observable in {"total_inputs_outputs_m3_s", "total_inputs_outputs_dashboard"}:
        return "Bilan externe: somme des entrees et somme des sorties, stockage exclu."
    return _observable_label(observable)


def _audit_block(audit: Mapping[str, Any]) -> str:
    status = str(audit.get("status", ""))
    issues = audit.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    klass = "warning" if status == "warn" else ""
    lines = [f'<p>Status: <strong class="{klass}">{safe(status or "unknown")}</strong></p>']
    lines.append(f"<p>Issues: <strong>{safe(len(issues))}</strong></p>")
    for issue in issues[:5]:
        if isinstance(issue, Mapping):
            message = issue.get("message", issue.get("description", issue))
        else:
            message = issue
        lines.append(f'<p class="muted">- {safe(short(message, limit=170))}</p>')
    return "\n".join(lines)


__all__ = (
    "ReportSection",
    "default_sections",
    "render_header",
    "render_sections",
)
