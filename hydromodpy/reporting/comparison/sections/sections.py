"""Modular sections for static comparison web reports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hydromodpy.reporting.comparison.context import ComparisonWebContext
from hydromodpy.reporting.comparison.html_utils import (
    render_links,
    safe,
)

from .io import (
    _base_config_payload,
    _boundary_condition_text,
    _boussinesq_method_text,
    _flow_payload_for_solver,
    _has_head_error_metrics,
    _initial_condition_text,
    _is_synthetic_patchy,
    _recharge_text,
    _simulation_config_payloads,
    _synthetic_context_rows,
)
from .templates import (
    _analysis_row_by_token,
    _analysis_row_text,
    _audit_block,
    _format_closure_rows,
    _format_metric_rows,
    _format_percent_value,
    _format_value,
    _mapping,
    _metric_analysis_row,
    _render_figures,
    _render_key_values,
    _render_metric_snapshot,
    _render_runtime_table,
    _render_table,
)


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
