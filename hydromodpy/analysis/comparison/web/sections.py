"""Modular sections for static comparison web reports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.web.context import ComparisonWebContext
from hydromodpy.analysis.comparison.web.html_utils import (
    link_relative,
    relative,
    render_links,
    render_table,
    safe,
    short,
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
            "reading_principle",
            "Principe de lecture",
            10,
            _render_reading_principle,
        ),
        ReportSection(
            "persistence_contract",
            "Persistance des sorties",
            15,
            _render_persistence_contract,
        ),
        ReportSection("audit", "Audit format", 20, _render_audit),
        ReportSection(
            "case_configuration",
            "Configuration du cas",
            30,
            _render_case_configuration,
            lambda ctx: bool(ctx.configuration_figures),
        ),
        ReportSection(
            "categorized_figures",
            "Figures par categorie",
            35,
            _render_categorized_figures,
            lambda ctx: bool(ctx.figure_categories),
        ),
        ReportSection("simulations", "Simulations", 40, _render_simulations),
        ReportSection("files", "Fichiers", 45, _render_files),
        ReportSection(
            "comparable_flux",
            "Flux sortant comparable",
            50,
            _render_comparable_flux,
        ),
        ReportSection("metrics", "Metriques principales", 60, _render_metrics),
    ]


def render_sections(ctx: ComparisonWebContext) -> str:
    """Render all available default report sections."""
    blocks: list[str] = []
    for section in sorted(default_sections(), key=lambda item: item.priority):
        if section.is_available(ctx):
            blocks.append(section.render(ctx))
    return "\n\n".join(blocks)


def render_header(ctx: ComparisonWebContext) -> str:
    """Render the report header."""
    payload = ctx.manifest
    return f"""
  <header>
    <p class="muted">Rapport HTML standard genere depuis les sorties de comparaison.</p>
    <h1>{safe(payload.get("comparison_id", "Comparison report"))}</h1>
    <p>Lecture rapide des simulations, metriques, figures et flux comparables. Cette page ne relance aucun solveur.</p>
    <div class="pillrow">
      <span class="pill">Audit: {safe(payload.get("audit_status", ctx.audit.get("status", "")))}</span>
      <span class="pill">Reference: {safe(payload.get("reference_simulation", ""))}</span>
      <span class="pill">Figures: {safe(len(ctx.figure_items))}</span>
      <span class="pill">Web root: {safe(relative(ctx.root, ctx.web_dir))}</span>
    </div>
  </header>
"""


def render_facts(ctx: ComparisonWebContext) -> str:
    """Render compact counters used as a quick sanity check."""
    return f"""
  <section class="facts">
    <div class="fact"><span>Simulations</span><strong>{safe(len(ctx.simulations))}</strong></div>
    <div class="fact"><span>Metriques</span><strong>{safe(len(ctx.metrics_rows))}</strong></div>
    <div class="fact"><span>Lignes budget</span><strong>{safe(len(ctx.budget_rows))}</strong></div>
    <div class="fact"><span>Categories figures</span><strong>{safe(len(ctx.figure_categories))}</strong></div>
  </section>
"""


def _render_reading_principle(_ctx: ComparisonWebContext) -> str:
    return """
  <section>
    <div class="card">
      <h2>Principe de lecture</h2>
      <p>Les sorties natives restent visibles. Pour comparer les flux entre solveurs, utiliser <code>comparable_outflow_total_m3_s</code>.</p>
      <p>Definition: <code>drainage_total_m3_s + surface_excess_total_m3_s</code>. Une composante absente vaut zero.</p>
      <p class="muted">Cela evite de comparer directement un drain MF6 a un excedent de surface Boussinesq, qui ne portent pas exactement la meme semantique.</p>
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
    <h2>Configuration du cas</h2>
    <p class="muted">A ouvrir avant les resultats: ces figures decrivent le support, les limites, les points, les forcages et le contexte spatial du benchmark.</p>
    <div class="figure-grid">
      {_render_figures(ctx=ctx, figures=ctx.configuration_figures)}
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
    <article class="card figure-category" id="figures-{safe(category.category_id)}">
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
    <h2>Figures par categorie</h2>
    <p class="muted">Aucune figure de resultat hors configuration.</p>
  </section>
"""
    return f"""
  <section>
    <h2>Figures par categorie</h2>
    <p class="muted">Les figures sont classees par usage de lecture. Les categories gardent les noms de fichiers originaux pour rester tracables vers le dossier <code>comparison_figures/</code>.</p>
    {"".join(category_blocks)}
  </section>
"""


def _render_simulations(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <div class="card">
      <h2>Simulations</h2>
      {render_table(ctx.simulations, [("id", "id"), ("solver", "solver"), ("mesh_mode", "mesh"), ("status", "status"), ("wall_time_seconds", "runtime s")], empty="Aucune simulation dans le manifeste.")}
    </div>
  </section>
"""


def _render_files(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <div class="card">
      <h2>Fichiers</h2>
      {render_links(root=ctx.root, web_dir=ctx.web_dir, links=ctx.data_links)}
    </div>
  </section>
"""


def _render_comparable_flux(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <h2>Flux sortant comparable</h2>
    {render_table(ctx.comparable_budget_rows[:16], [("time_label", "temps"), ("period_index", "periode"), ("value__mf6_ref", "mf6_ref"), ("value__bouss_candidate", "bouss_candidate")], empty="Aucune ligne comparable_outflow_total_m3_s trouvee.")}
  </section>
"""


def _render_metrics(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <h2>Metriques principales</h2>
    {render_table(ctx.metrics_rows[:24], [("simulation_id", "simulation"), ("observable", "observable"), ("n_pairs", "n"), ("mae", "mae"), ("rmse", "rmse"), ("max_abs_error", "max abs")], empty="Aucune metrique.")}
  </section>
"""


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
        blocks.append(
            "<figure>"
            f'<a href="{safe(link_relative(ctx.web_dir, path))}">'
            f'<img src="{safe(link_relative(ctx.web_dir, path))}" alt="{safe(title)}">'
            "</a>"
            f"<figcaption>{safe(title)}"
            + (f" - {safe(kind)}" if kind else "")
            + "</figcaption></figure>"
        )
    if not blocks:
        return '<p class="muted">Aucune figure PNG disponible.</p>'
    return "\n".join(blocks)


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
    "render_facts",
    "render_header",
    "render_sections",
)
