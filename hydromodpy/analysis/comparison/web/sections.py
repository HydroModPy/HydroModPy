"""Modular sections for static comparison web reports."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.analysis.comparison.web.context import ComparisonWebContext
from hydromodpy.analysis.comparison.web.html_utils import (
    link_relative,
    render_links,
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
        ReportSection("metrics", "Metriques principales", 50, _render_metrics),
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
      <span class="pill">Figures: {safe(len(ctx.figure_items))}</span>
    </div>
  </header>
"""


def render_facts(ctx: ComparisonWebContext) -> str:
    """Render compact counters used as a quick sanity check."""
    return f"""
  <section class="facts">
    <div class="fact"><span>Simulations</span><strong>{safe(len(ctx.simulations))}</strong></div>
    <div class="fact"><span>Figures</span><strong>{safe(len(ctx.figure_items))}</strong></div>
    <div class="fact"><span>Lignes budget</span><strong>{safe(len(ctx.budget_rows))}</strong></div>
    <div class="fact"><span>Metriques</span><strong>{safe(len(ctx.metrics_rows))}</strong></div>
  </section>
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
    mf6 = _mapping(payload.get("modflow6"))
    mf6_runtime = _mapping(mf6.get("runtime"))
    mf6_sgrid = _mapping(_mapping(mf6.get("sgrid")).get("vertical"))
    bouss_method = _boussinesq_method_text(flow)
    hydraulic_rows = [
        ("Regime hydraulique", _format_value(flow.get("flow_regime"), default="transient")),
        ("Recharge transitoire", _recharge_text(flow)),
        ("Conditions initiales", _initial_condition_text(flow)),
        ("Conditions aux limites", _boundary_condition_text(flow)),
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
      <h3>Configuration hydraulique commune</h3>
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
      {_render_table(ctx.simulations, [("id", "id"), ("solver", "solver"), ("mesh_mode", "mesh"), ("status", "status"), ("wall_time_seconds", "runtime s")], empty="Aucune simulation dans le manifeste.")}
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


def _render_metrics(ctx: ComparisonWebContext) -> str:
    rows = _format_metric_rows(ctx.metrics_rows[:24])
    return f"""
  <section>
    <h2>Metriques principales</h2>
    <p class="muted">Les ecarts de charge restent donnes en metres, puis normalises par l'amplitude de la grandeur de reference pour l'observable concerne: amplitude spatiale pour une carte, amplitude temporelle pour une chronique. Cette normalisation donne directement un ordre de grandeur en pourcentage.</p>
    {_render_table(rows, [("simulation_id", "simulation"), ("observable_label", "observable"), ("n_pairs", "n"), ("mae", "ecart moy m"), ("rmse", "RMSE m"), ("normalization_scale", "echelle ref m"), ("mae_normalized_percent", "ecart moy %")], empty="Aucune metrique.")}
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
        caption = _figure_caption(item)
        blocks.append(
            "<figure>"
            f'<a href="{safe(link_relative(ctx.web_dir, path))}">'
            f'<img src="{safe(link_relative(ctx.web_dir, path))}" alt="{safe(title)}">'
            "</a>"
            f"<figcaption>{safe(caption)}"
            + (f'<br><span class="muted">{safe(title)}'
               + (f" - {safe(kind)}" if kind else "")
               + "</span>")
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
            f"plan incline, altitude de base {_format_value(topography.get('base_elevation'), default='80')} m, denivele lateral {_format_value(topography.get('right_to_left_amplitude'), default='20')} m",
        ),
        (
            "Epaisseur",
            f"substratum a epaisseur constante {_format_value(depth_model.get('thickness'), default='80 m')}",
        ),
        (
            "Conductivite K",
            _format_mapping_values(k_values, default="heterogene: ouest 1e-5, centre 8e-5, est 3e-5 m/s"),
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
        f"{labels.get(str(key), str(key))}: {_format_value(raw)}"
        for key, raw in value.items()
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
        if (
            str(flow.get("runtime_backend", "")).strip().lower() == "petsc"
            and str(flow.get("surface_interaction_model", "")).strip().lower()
            == "ts_vi_obstacle"
        ):
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


def _boundary_condition_text(flow: Mapping[str, Any]) -> str:
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
        suffix = f", conductance {value}" if value else ""
        return f"pas de charge laterale imposee; drainage de surface actif sur le toit{suffix}"
    if not active:
        return "aucune condition limite active, hors recharge"
    return ", ".join(active)


def _boussinesq_method_text(flow: Mapping[str, Any]) -> str:
    backend = str(flow.get("runtime_backend", "") or "").strip().lower()
    surface = str(flow.get("surface_interaction_model", "") or "").strip().lower()
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


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value if value is not None else "")
    if not math.isfinite(number):
        return ""
    if abs(number) >= 1000 or (abs(number) > 0 and abs(number) < 0.01):
        return f"{number:.2e}"
    if abs(number) >= 100:
        return f"{number:.0f}"
    if abs(number) >= 10:
        return f"{number:.1f}"
    return f"{number:.3g}"


def _observable_label(name: str) -> str:
    labels = {
        "head_map_initial": "champ de charge initial",
        "head_map_wet_year1": "champ de charge apres la premiere saison humide",
        "head_map_drought_year2": "champ de charge en fin de periode seche",
        "head_map_extreme_recharge": "champ de charge pendant le pic de recharge",
        "head_map_last": "champ de charge final",
        "head_west_low_k_series": "chronique de charge dans la zone ouest peu conductrice",
        "head_west_interface_series": "chronique de charge pres de l'interface ouest/centre",
        "head_central_high_k_series": "chronique de charge dans le couloir central conducteur",
        "head_east_interface_series": "chronique de charge pres de l'interface centre/est",
        "head_east_medium_k_series": "chronique de charge dans la zone est intermediaire",
    }
    return labels.get(name, name.replace("_", " "))


def _figure_caption(item: Mapping[str, Any]) -> str:
    observable = str(item.get("observable", ""))
    kind = str(item.get("kind", ""))
    if observable == "case_configuration":
        return "Contexte du cas: geometrie, zones K, recharge et points d'extraction."
    if "triptych" in kind or "head_map" in observable:
        return _observable_label(observable) + ": reference, candidat et ecart."
    if kind == "timeseries" or observable.endswith("_series"):
        return _observable_label(observable) + ": comparaison temporelle MF6 / Boussinesq."
    if observable == "storage_change_total_m3_s":
        return "Stockage global: variation instantanee du volume stocke dans l'aquifere."
    if observable == "total_inputs_outputs_m3_s":
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
    "render_facts",
    "render_header",
    "render_sections",
)
