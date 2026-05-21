"""HTML sections, CSS, lightbox and page rendering for compact network synthesis."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from hydromodpy.results.html_helpers import link_relative, safe_html

from .io import (
    CompactNetworkSynthesisConfig,
    GroupSection,
    SimulationRecord,
    _first,
    _fmt_m,
    _fmt_ratio,
    _row_value,
    read_json_mapping,
)


def relative_path(page_path: Path, target: Path) -> str:
    return link_relative(page_path.parent, target)


def solver_summary(record: SimulationRecord) -> str:
    if record.solver == "modflow6":
        return "MODFLOW 6"
    if record.solver == "boussinesq":
        return "Boussinesq"
    return record.solver or "solveur non renseigne"


def mesh_summary(record: SimulationRecord) -> str:
    title = (
        record.meta.mesh_summary
        or record.mesh_label
        or record.mesh_mode
        or "maillage non renseigne"
    )
    cell_count = (
        _row_value(record.release_distance, "catchment_cell_count")
        or _row_value(record.release_accumulation_distance, "catchment_cell_count")
        or _row_value(record.accumulation_distance, "catchment_cell_count")
    )
    detail = (
        f"{safe_html(_fmt_m(cell_count))} cellules de calcul"
        if cell_count
        else "nombre de cellules non disponible"
    )
    return f"{safe_html(title.replace('_', ' '))}; {detail}"


def configuration_cell(record: SimulationRecord) -> str:
    return (
        '<td class="config-cell">'
        f"<strong>{safe_html(record.meta.label)}</strong>"
        f'<span class="sub">{safe_html(solver_summary(record))}; '
        f"{mesh_summary(record)}</span>"
        "</td>"
    )


def source_row(record: SimulationRecord) -> dict[str, str]:
    if record.run_info.get("sim_id") and record.run_info.get("run_folder"):
        return record.run_info
    return (
        record.release_distance
        or record.release_accumulation_distance
        or record.accumulation_distance
        or record.run_info
        or {}
    )


def metric_bar(row: dict[str, str] | None, max_distance: float) -> str:
    if row is None:
        return ""
    value = row.get("bidirectional_distance_mean_m", "")
    try:
        width = max(4.0, min(100.0, 100.0 * float(value) / max_distance))
    except (TypeError, ValueError, ZeroDivisionError):
        width = 0.0
    return f'<div class="bar" style="width:{width:.1f}%"></div>'


def metric_grid(row: dict[str, str], max_distance: float) -> str:
    return f"""
<div class="metric-box">
  {metric_bar(row, max_distance)}
  <div class="metric-grid">
    <div><span>calc &rarr; obs moy.</span><strong>{safe_html(_fmt_m(row.get("sim_to_network_distance_mean_m", "")))} m</strong></div>
    <div><span>obs &rarr; calc moy.</span><strong>{safe_html(_fmt_m(row.get("network_to_sim_distance_mean_m", "")))} m</strong></div>
    <div><span>ratio</span><strong>{safe_html(_fmt_ratio(row.get("planar_distance_ratio", "")))}</strong></div>
    <div><span>moyenne sym.</span><strong>{safe_html(_fmt_m(row.get("bidirectional_distance_mean_m", "")))} m</strong></div>
  </div>
</div>
"""


def figure_path(
    figure_root: Path,
    record: SimulationRecord,
    variable: str,
) -> Path:
    return figure_root / record.meta.simulation_id / f"{variable}_log_intensity.png"


def figure_preview(
    page_path: Path,
    figure_root: Path,
    record: SimulationRecord,
    variable: str,
    label: str,
) -> str:
    path = figure_path(figure_root, record, variable)
    if not path.exists():
        return '<div class="figure-missing">figure non disponible</div>'
    rel = relative_path(page_path, path)
    title = f"{record.meta.label} - {label}"
    return f"""
<figure class="method-figure">
  <a href="{safe_html(rel)}" class="figure-link" data-lightbox-src="{safe_html(rel)}" data-lightbox-title="{safe_html(title)}" title="Cliquer pour agrandir">
    <img src="{safe_html(rel)}" alt="{safe_html(title)}" loading="lazy">
  </a>
  <figcaption>{safe_html(label)}</figcaption>
</figure>
"""


def method_cell(
    page_path: Path,
    figure_root: Path,
    record: SimulationRecord,
    *,
    row: dict[str, str] | None,
    variable: str,
    label: str,
    description: str,
    missing: str,
    max_distance: float,
) -> str:
    if row is None:
        return f"""
<td class="method-cell">
  <div class="method-title">{safe_html(label)}</div>
  <p>{safe_html(description)}</p>
  <div class="figure-missing">{safe_html(missing)}</div>
</td>
"""
    return f"""
<td class="method-cell">
  <div class="method-title">{safe_html(label)}</div>
  <p>{safe_html(description)}</p>
  {figure_preview(page_path, figure_root, record, variable, label)}
  {metric_grid(row, max_distance)}
</td>
"""


def comparison_table(
    records: list[SimulationRecord],
    *,
    page_path: Path,
    figure_root: Path,
    group: str,
    routed_distance_for: Callable[[SimulationRecord], dict[str, str] | None],
    all_distances: list[float],
) -> str:
    max_distance = max(all_distances or [1.0])
    rows = []
    for record in records:
        if record.meta.group != group:
            continue
        rows.append(
            "<tr>"
            f"{configuration_cell(record)}"
            + method_cell(
                page_path,
                figure_root,
                record,
                row=record.release_distance,
                variable="release_flux",
                label="Emergences calculees avant routage",
                description=(
                    "Mailles ou le modele calcule une sortie d'eau vers la surface: "
                    "drain + surface excess, avant accumulation aval."
                ),
                missing="metrique non disponible",
                max_distance=max_distance,
            )
            + method_cell(
                page_path,
                figure_root,
                record,
                row=routed_distance_for(record),
                variable="release_accumulation_flux",
                label="Emergences accumulees vers l'aval",
                description=(
                    "Les emergences sont routees vers l'aval sur le support numerique, "
                    "puis comparees au reseau observe."
                ),
                missing="non calcule pour cette configuration",
                max_distance=max_distance,
            )
            + "</tr>"
        )
    if not rows:
        rows.append(
            '<tr><td colspan="3" class="missing">Aucune simulation dans ce groupe.</td></tr>'
        )
    return f"""
<table class="comparison-table">
  <thead>
    <tr>
      <th>configuration calculee</th>
      <th>emergences calculees avant routage</th>
      <th>emergences accumulees vers l'aval</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""


def contract_section(config: CompactNetworkSynthesisConfig) -> str:
    if not config.contract_cards:
        return ""
    cards = "".join(
        f"<article><h3>{safe_html(card.title)}</h3><p>{card.body_html}</p></article>"
        for card in config.contract_cards
    )
    return f"""
<section>
  <h2>Contrat physique commun</h2>
  <div class="cards">{cards}</div>
</section>
"""


def context_section(page_path: Path, context_figure_path: Path) -> str:
    if not context_figure_path.exists():
        return ""
    rel = relative_path(page_path, context_figure_path)
    title = "Contexte topographique"
    return f"""
<section>
  <h2>Contexte spatial</h2>
  <p>Carte topographique du support de calcul, avec le reseau hydrographique observe en rouge et la limite du bassin versant.</p>
  <figure class="wide-figure context-figure">
    <a href="{safe_html(rel)}" class="figure-link" data-lightbox-src="{safe_html(rel)}" data-lightbox-title="{safe_html(title)}" title="Cliquer pour agrandir">
      <img src="{safe_html(rel)}" alt="{safe_html(title)}" loading="lazy">
    </a>
    <figcaption>{safe_html(title)}</figcaption>
  </figure>
</section>
"""


def recharge_section(
    page_path: Path,
    recharge_figure_path: Path,
    summary_text: str,
) -> str:
    if not recharge_figure_path.exists():
        return ""
    rel = relative_path(page_path, recharge_figure_path)
    title = "Recharge mensuelle imposee"
    return f"""
<section>
  <h2>Recharge imposee</h2>
  <p>{safe_html(summary_text)}. Cette chronique est commune aux configurations de ce benchmark.</p>
  <figure class="wide-figure">
    <a href="{safe_html(rel)}" class="figure-link" data-lightbox-src="{safe_html(rel)}" data-lightbox-title="{safe_html(title)}" title="Cliquer pour agrandir">
      <img src="{safe_html(rel)}" alt="{safe_html(title)}" loading="lazy">
    </a>
    <figcaption>{safe_html(title)}</figcaption>
  </figure>
</section>
"""


def group_section(
    records: list[SimulationRecord],
    section: GroupSection,
    *,
    page_path: Path,
    figure_root: Path,
    routed_distance_for: Callable[[SimulationRecord], dict[str, str] | None],
    all_distances: list[float],
) -> str:
    table = comparison_table(
        records,
        page_path=page_path,
        figure_root=figure_root,
        group=section.group_id,
        routed_distance_for=routed_distance_for,
        all_distances=all_distances,
    )
    return f"""
<section>
  <h2>{safe_html(section.title)}</h2>
  <p>{safe_html(section.intro)}</p>
  {table}
</section>
"""


def interpretation_section(config: CompactNetworkSynthesisConfig) -> str:
    if not config.interpretation_cards:
        return ""
    cards = "".join(
        f"<article><h3>{safe_html(card.title)}</h3><p>{card.body_html}</p></article>"
        for card in config.interpretation_cards
    )
    return f"""
<section>
  <h2>Lecture des ecarts regulier / irregulier</h2>
  <p>Les fortes differences viennent surtout du support geometrique utilise pour porter les sorties de nappe et pour mesurer les distances.</p>
  <div class="cards">{cards}</div>
</section>
"""


def metric_synthesis_section(
    page_path: Path,
    metric_synthesis_figure_path: Path,
) -> str:
    if not metric_synthesis_figure_path.exists():
        return ""
    rel = relative_path(page_path, metric_synthesis_figure_path)
    title = "Synthese des distances au reseau observe"
    return f"""
<section>
  <h2>Synthese des metriques</h2>
  <p>La figure compare, pour chaque configuration, les deux diagnostics de reseau avec la distance moyenne symetrique et le ratio directionnel.</p>
  <figure class="wide-figure synthesis-figure">
    <a href="{safe_html(rel)}" class="figure-link" data-lightbox-src="{safe_html(rel)}" data-lightbox-title="{safe_html(title)}" title="Cliquer pour agrandir">
      <img src="{safe_html(rel)}" alt="{safe_html(title)}" loading="lazy">
    </a>
    <figcaption>{safe_html(title)}</figcaption>
  </figure>
</section>
"""


def links_section(page_path: Path, comparison_root: Path) -> str:
    manifest = read_json_mapping(comparison_root / "comparison_manifest.json")
    report = comparison_root / "web" / "index.html"
    audit = comparison_root / "comparison_audit.md"
    report_item = (
        f'<a href="{safe_html(relative_path(page_path, report))}">Rapport HTML complet</a>'
        if report.exists()
        else "Rapport HTML complet non encore produit"
    )
    audit_item = (
        f'<a href="{safe_html(relative_path(page_path, audit))}">Audit de comparaison</a>'
        if audit.exists()
        else "Audit de comparaison non encore produit"
    )
    return f"""
<section>
  <h2>Sorties completes</h2>
  <p>Cette page est volontairement compacte. Les artefacts complets restent disponibles dans le dossier de comparaison.</p>
  <ul>
    <li>{report_item}</li>
    <li>{audit_item}</li>
    <li><code>{safe_html(str(comparison_root))}</code></li>
    <li>statut audit: <strong>{safe_html(manifest.get("audit_status", "non lance"))}</strong></li>
  </ul>
</section>
"""


def lightbox_markup() -> str:
    return """
<div class="lightbox" id="figure-lightbox" hidden>
  <button type="button" class="lightbox-close">Fermer</button>
  <img alt="">
  <p></p>
</div>
"""


def lightbox_script() -> str:
    return """
<script>
(() => {
  const lightbox = document.getElementById("figure-lightbox");
  if (!lightbox) return;
  const image = lightbox.querySelector("img");
  const caption = lightbox.querySelector("p");
  const closeButton = lightbox.querySelector("button");
  const close = () => {
    lightbox.hidden = true;
    image.removeAttribute("src");
    caption.textContent = "";
  };
  document.querySelectorAll("[data-lightbox-src]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      image.src = link.dataset.lightboxSrc;
      image.alt = link.dataset.lightboxTitle || "";
      caption.textContent = link.dataset.lightboxTitle || "";
      lightbox.hidden = false;
    });
  });
  closeButton.addEventListener("click", close);
  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !lightbox.hidden) close();
  });
})();
</script>
"""


def css() -> str:
    return """
:root {
  color-scheme: light;
  --text: #1f2933;
  --muted: #627080;
  --line: #d8dee6;
  --soft: #f5f7fa;
  --panel: #ffffff;
  --accent-soft: #d7edf1;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Arial, Helvetica, sans-serif;
  color: var(--text);
  background: #eef2f5;
}
main {
  max-width: 1320px;
  margin: 0 auto;
  padding: 28px;
}
h1 { margin: 0 0 8px; font-size: 30px; }
h2 { margin: 30px 0 10px; font-size: 21px; }
h3 { margin: 20px 0 8px; font-size: 15px; }
p { max-width: 980px; line-height: 1.45; color: var(--muted); }
a { color: #0f5f6f; }
section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin: 16px 0;
}
.cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
article {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  background: var(--soft);
}
article h3 { margin-top: 0; }
table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 14px;
}
.comparison-table th:nth-child(1) { width: 24%; }
.comparison-table th:nth-child(2),
.comparison-table th:nth-child(3) { width: 38%; }
th, td {
  border-bottom: 1px solid var(--line);
  padding: 10px 9px;
  text-align: left;
  vertical-align: top;
}
th {
  color: #33404d;
  background: var(--soft);
  font-weight: 700;
}
th span, .sub {
  display: block;
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
  margin-top: 3px;
}
.missing { color: var(--muted); background: #fafafa; }
.bar {
  height: 6px;
  border-radius: 999px;
  background: var(--accent-soft);
  margin: 0 0 6px;
}
.method-cell p {
  margin: 4px 0 9px;
  font-size: 12px;
  line-height: 1.35;
}
.method-title {
  font-weight: 700;
  color: #26313c;
}
figure {
  margin: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
img { display: block; width: 100%; height: auto; }
.figure-link {
  display: block;
  cursor: zoom-in;
}
figcaption {
  padding: 9px 11px;
  color: var(--muted);
  font-size: 13px;
}
.wide-figure { max-width: 720px; }
.context-figure { max-width: 860px; }
.figure-missing {
  color: var(--muted);
  background: repeating-linear-gradient(
    -45deg,
    #fafafa,
    #fafafa 8px,
    #f1f3f5 8px,
    #f1f3f5 16px
  );
  font-style: italic;
  text-align: center;
  vertical-align: middle;
  min-height: 140px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.metric-box {
  margin-top: 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  background: #fbfcfd;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.metric-grid span {
  display: block;
  color: var(--muted);
  font-size: 11px;
}
.metric-grid strong { font-size: 16px; }
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 10px;
  padding: 18px;
  background: rgba(15, 23, 32, 0.82);
}
.lightbox[hidden] { display: none; }
.lightbox img {
  max-width: min(1400px, 96vw);
  max-height: 84vh;
  width: auto;
  height: auto;
  align-self: center;
  justify-self: center;
  border-radius: 8px;
  background: #fff;
}
.lightbox p {
  justify-self: center;
  margin: 0;
  color: #fff;
}
.lightbox-close {
  justify-self: end;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 6px;
  padding: 7px 10px;
  color: #fff;
  background: rgba(255, 255, 255, 0.12);
  cursor: pointer;
}
@media (max-width: 900px) {
  main { padding: 14px; }
  .cards { grid-template-columns: 1fr; }
  table { display: block; overflow-x: auto; }
}
"""


def render_page(
    config: CompactNetworkSynthesisConfig,
    records: list[SimulationRecord],
    *,
    page_path: Path,
    figure_root: Path,
    comparison_root: Path,
    context_figure_path: Path,
    recharge_figure_path: Path,
    metric_synthesis_figure_path: Path,
    recharge_summary: str,
    routed_distance_for: Callable[[SimulationRecord], dict[str, str] | None],
    all_distances: list[float],
) -> str:
    if not any(record.release_distance or record.accumulation_distance for record in records):
        not_run = """
<section>
  <h2>Pas encore de sorties</h2>
  <p>Le benchmark n'a pas encore ete execute, ou les CSV de comparaison ne sont pas presents.</p>
</section>
"""
    else:
        not_run = ""
    groups = "".join(
        group_section(
            records,
            section,
            page_path=page_path,
            figure_root=figure_root,
            routed_distance_for=routed_distance_for,
            all_distances=all_distances,
        )
        for section in config.group_sections
    )
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_html(config.title)}</title>
  <style>{css()}</style>
</head>
<body>
<main>
  <h1>{safe_html(config.title)}</h1>
  <p>{safe_html(config.intro)}</p>
  {contract_section(config)}
  {context_section(page_path, context_figure_path)}
  {recharge_section(page_path, recharge_figure_path, recharge_summary)}
  {not_run}
  {groups}
  {interpretation_section(config)}
  {metric_synthesis_section(page_path, metric_synthesis_figure_path)}
  {links_section(page_path, comparison_root)}
</main>
{lightbox_markup()}
{lightbox_script()}
</body>
</html>
"""


__all__ = [
    "relative_path",
    "solver_summary",
    "mesh_summary",
    "configuration_cell",
    "source_row",
    "metric_bar",
    "metric_grid",
    "figure_path",
    "figure_preview",
    "method_cell",
    "comparison_table",
    "contract_section",
    "context_section",
    "recharge_section",
    "group_section",
    "interpretation_section",
    "metric_synthesis_section",
    "links_section",
    "lightbox_markup",
    "lightbox_script",
    "css",
    "render_page",
    "_first",
]
