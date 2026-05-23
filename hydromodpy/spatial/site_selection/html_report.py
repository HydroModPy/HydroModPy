"""Static HTML report for site-selection outputs."""

from __future__ import annotations

import base64
import csv
import html
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.spatial.site_selection.figures import render_site_selection_map
from hydromodpy.spatial.site_selection.manifest import (
    load_selection_manifest,
    manifest_output_path,
    validate_selection_manifest,
)

REPORT_DIR_NAME = "review"
REPORT_HTML_NAME = "index.html"


def render_site_selection_html_report(
    manifest_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    """Render a compact static HTML review page from a selection manifest."""

    manifest_file = Path(manifest_path).expanduser().resolve()
    validation_errors = validate_selection_manifest(
        manifest_file,
        skip_output_keys=("site_selection_report_html", "site_selection_map_png"),
    )
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    manifest = load_selection_manifest(manifest_file)
    output_root = Path(str(manifest.get("output_root") or manifest_file.parent)).resolve()
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else output_root / REPORT_DIR_NAME / REPORT_HTML_NAME
    )
    destination.parent.mkdir(parents=True, exist_ok=True)

    selected = _read_csv(manifest_output_path(manifest, "selected_sites_csv", manifest_path=manifest_file))
    rejected = _read_csv(manifest_output_path(manifest, "rejected_sites_csv", manifest_path=manifest_file))
    decisions = _read_jsonl(
        manifest_output_path(manifest, "selection_decisions_jsonl", manifest_path=manifest_file)
    )
    components = _read_jsonl(
        manifest_output_path(manifest, "criteria_components_jsonl", manifest_path=manifest_file)
    )
    evidence = _read_jsonl(
        manifest_output_path(manifest, "observation_evidence_jsonl", manifest_path=manifest_file)
    )
    map_path = render_site_selection_map(manifest_file)

    payload = _render_html(
        manifest=manifest,
        manifest_path=manifest_file,
        map_path=map_path,
        output_path=destination,
        output_root=output_root,
        selected=selected,
        rejected=rejected,
        decisions=decisions,
        components=components,
        evidence=evidence,
    )
    destination.write_text(payload, encoding="utf-8")
    return destination


def _render_html(
    *,
    manifest: Mapping[str, Any],
    manifest_path: Path,
    map_path: Path,
    output_path: Path,
    output_root: Path,
    selected: list[dict[str, str]],
    rejected: list[dict[str, str]],
    decisions: list[dict[str, Any]],
    components: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> str:
    selection_id = str(manifest.get("selection_id", "site_selection"))
    counts = _mapping(manifest.get("counts"))
    strategy = _mapping(manifest.get("strategy"))
    territory = _mapping(manifest.get("territory"))
    criteria = _mapping(manifest.get("criteria"))
    dem = _mapping(manifest.get("dem"))
    flow_products = _mapping(manifest.get("flow_products"))
    outputs = _mapping(manifest.get("outputs"))
    map_context = _mapping(manifest.get("map_context"))
    context_layers = _sequence(map_context.get("layers"))
    output_dir = output_path.parent

    decision_by_site = {str(row.get("site_id", "")): row for row in decisions}
    selected_rows = [_site_row(row, decision_by_site.get(row.get("site_id", ""))) for row in selected]
    rejected_rows = [_rejected_row(row, decision_by_site.get(row.get("site_id", ""))) for row in rejected]

    component_counts: dict[str, int] = {}
    component_family_counts: dict[str, int] = {}
    for component in components:
        key = str(component.get("criterion_id") or "unknown")
        component_counts[key] = component_counts.get(key, 0) + 1
        family = str(component.get("criterion_family") or "unknown")
        component_family_counts[family] = component_family_counts.get(family, 0) + 1

    output_links = "\n".join(
        f"<li><a href=\"{_href(output_root / path, output_dir)}\">"
        f"<code>{_e(label)}</code></a></li>"
        for label, path in sorted(outputs.items())
        if path
    )
    map_href = _href(map_path, output_dir)
    map_src = _image_src(map_path, output_dir)

    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(selection_id)} - Site Selection</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #5b6777;
      --line: #d8dee8;
      --bg: #f6f8fb;
      --band: #ffffff;
      --accent: #0f766e;
      --warn: #a16207;
      --bad: #b91c1c;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 18px;
      line-height: 1.55;
    }}
    header, main {{ max-width: 1320px; margin: 0 auto; padding: 30px; }}
    header {{ padding-top: 36px; }}
    h1 {{ margin: 0 0 10px; font-size: 36px; font-weight: 650; }}
    h2 {{ margin: 0 0 16px; font-size: 25px; font-weight: 650; }}
    p {{ margin: 0 0 14px; }}
    section {{
      background: var(--band);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin: 0 0 18px;
    }}
    .muted {{ color: var(--muted); }}
    .explain {{
      border-left: 4px solid var(--accent);
      padding: 2px 0 2px 16px;
      margin: 0 0 18px;
      color: #263445;
    }}
    .explain p:last-child {{ margin-bottom: 0; }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 14px;
      margin-top: 22px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px;
      background: #fbfcfe;
    }}
    .metric strong {{ display: block; font-size: 30px; margin-bottom: 2px; }}
    dl {{
      display: grid;
      grid-template-columns: minmax(160px, 260px) 1fr;
      gap: 8px 18px;
      margin: 0;
    }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 11px 12px; text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; background: #f8fafc; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.92em; }}
    .table-wrap {{ overflow-x: auto; }}
    .ok {{ color: var(--accent); font-weight: 600; }}
    .warn {{ color: var(--warn); font-weight: 600; }}
    .bad {{ color: var(--bad); font-weight: 600; }}
    .map-figure {{
      margin: 0;
    }}
    .map-figure img {{
      display: block;
      width: 100%;
      height: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
    }}
    .map-figure figcaption {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 16px;
    }}
    ul {{ margin: 0; padding-left: 20px; }}
  </style>
</head>
<body>
  <header>
    <p class="muted">Rapport HTML v0 - selection de sites HydroModPy</p>
    <h1>{_e(selection_id)}</h1>
    <p class="muted">{_e(str(manifest.get("created_at_utc", "")))}</p>
    <div class="summary">
      {_metric("Sites retenus", counts.get("selected", 0), "ok")}
      {_metric("Sites rejetes", counts.get("rejected", 0), "bad")}
      {_metric("Decisions", counts.get("decisions", 0), "")}
      {_metric("Criteres traces", counts.get("criteria_components", 0), "")}
    </div>
  </header>
  <main>
    <section>
      <h2>Strategie</h2>
      <div class="explain">
        <p>{_e(_principle_explanation(strategy, criteria))}</p>
        <p>{_e(_dem_explanation(dem, flow_products))}</p>
      </div>
      <dl>
        <dt>Principe</dt><dd><code>{_e(strategy.get("principle"))}</code></dd>
        <dt>Profil</dt><dd><code>{_e(strategy.get("profile"))}</code></dd>
        <dt>Mode candidats</dt><dd><code>{_e(strategy.get("candidate_mode"))}</code></dd>
        <dt>Observation principale</dt><dd><code>{_e(strategy.get("primary_observation_type"))}</code></dd>
        <dt>Territoire</dt><dd>{_e(_territory_label(territory))}</dd>
        <dt>Ruleset</dt><dd><code>{_e(criteria.get("ruleset"))}</code></dd>
        <dt>Contexte cartographique</dt><dd>{_e(_context_layer_summary(context_layers))}</dd>
      </dl>
    </section>

    <section>
      <h2>Carte de controle</h2>
      <figure class="map-figure">
        <a href="{map_href}" target="_blank" rel="noopener">
          <img src="{map_src}" alt="Carte de controle de la selection de sites">
        </a>
        <figcaption>Cliquer sur la figure pour l'ouvrir en pleine resolution. Fond DEM regional, contours des bassins, exutoires retenus/rejetes et stations d'observation associees.</figcaption>
      </figure>
    </section>

    <section>
      <h2>Sites retenus</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Site</th><th>Region</th><th>Surface km2</th><th>Score</th><th>Decision</th><th>Avertissements</th></tr></thead>
          <tbody>{''.join(selected_rows) or _empty_row(6)}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>Sites rejetes</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Site</th><th>Surface km2</th><th>Statut</th><th>Etape</th><th>Raison</th><th>Flags bloquants</th></tr></thead>
          <tbody>{''.join(rejected_rows) or _empty_row(6)}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>Criteres et evidences</h2>
      <dl>
        <dt>Criteres</dt><dd>{_e(_component_summary(component_counts))}</dd>
        <dt>Familles auditees</dt><dd>{_e(_component_summary(component_family_counts))}</dd>
        <dt>Observations tracees</dt><dd>{len(evidence)}</dd>
        <dt>Rejets bloquants</dt><dd>{_e(counts.get("blocking_rejections", 0))}</dd>
        <dt>Avertissements</dt><dd>{_e(counts.get("warnings", 0))}</dd>
      </dl>
    </section>

    <section>
      <h2>Artefacts</h2>
      <ul>
        <li><a href="{_href(manifest_path, output_dir)}"><code>{_e(manifest_path.name)}</code></a></li>
        {output_links}
      </ul>
    </section>
  </main>
</body>
</html>
"""


def _site_row(row: Mapping[str, str], decision: Mapping[str, Any] | None) -> str:
    decision = decision or {}
    return (
        "<tr>"
        f"<td><code>{_e(row.get('site_id'))}</code></td>"
        f"<td>{_e(row.get('region_id'))}</td>"
        f"<td>{_e(row.get('area_km2'))}</td>"
        f"<td>{_e(_format_score(decision.get('rank_score')))}</td>"
        f"<td class=\"ok\">{_e(decision.get('decision_reason') or 'selected')}</td>"
        f"<td class=\"warn\">{_e(_join_flags(decision.get('warning_flags')))}</td>"
        "</tr>"
    )


def _rejected_row(row: Mapping[str, str], decision: Mapping[str, Any] | None) -> str:
    decision = decision or {}
    return (
        "<tr>"
        f"<td><code>{_e(row.get('site_id'))}</code></td>"
        f"<td>{_e(row.get('area_km2'))}</td>"
        f"<td>{_e(row.get('status'))}</td>"
        f"<td>{_e(decision.get('decision_stage'))}</td>"
        f"<td class=\"bad\">{_e(decision.get('decision_reason') or row.get('failure_reason'))}</td>"
        f"<td class=\"bad\">{_e(_join_flags(decision.get('blocking_flags')))}</td>"
        "</tr>"
    )


def _read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return []


def _metric(label: str, value: object, css_class: str) -> str:
    cls = f" {css_class}" if css_class else ""
    return f"<div class=\"metric\"><strong class=\"{cls.strip()}\">{_e(value)}</strong>{_e(label)}</div>"


def _territory_label(territory: Mapping[str, Any]) -> str:
    parts = [str(territory.get("mode") or "")]
    if territory.get("regions"):
        parts.append(", ".join(str(item) for item in territory["regions"]))
    if territory.get("departments"):
        parts.append(", ".join(str(item) for item in territory["departments"]))
    if territory.get("bbox"):
        parts.append(str(territory["bbox"]))
    return " - ".join(part for part in parts if part)


def _component_summary(counts: Mapping[str, int]) -> str:
    if not counts:
        return "aucun critere trace"
    return ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))


def _principle_explanation(
    strategy: Mapping[str, Any],
    criteria: Mapping[str, Any],
) -> str:
    principle = str(strategy.get("principle") or "")
    candidate_mode = str(strategy.get("candidate_mode") or "")
    observation_type = str(strategy.get("primary_observation_type") or "")
    area = _mapping(criteria.get("area"))
    area_rule = _area_rule_label(area)
    if principle == "observation_led" or candidate_mode == "station_outlets":
        return (
            "La selection est pilotee par les observations: les stations de jaugeage "
            "fournissent d'abord les exutoires candidats. Les bassins sont ensuite "
            "delimites depuis ces exutoires et filtres par les criteres declares "
            f"(station principale: {observation_type or 'non precisee'}; {area_rule}). "
            "Cette logique evite de choisir un bassin seulement parce que sa surface "
            "convient: il doit aussi correspondre a un point d'observation exploitable."
        )
    return (
        "La selection croise directement les criteres spatiaux et physiques declares "
        f"({area_rule}). Les observations ne sont alors pas forcement le premier filtre; "
        "elles peuvent servir de bonus, de diagnostic ou de contrainte selon le profil."
    )


def _area_rule_label(area: Mapping[str, Any]) -> str:
    mode = str(area.get("mode") or "report_only")
    mode_label = {
        "hard_reject": "exigee",
        "warning": "controlee en avertissement",
        "score": "scoree",
        "stratify": "utilisee pour stratifier",
        "report_only": "rapportee",
    }.get(mode, mode)
    ranges = _area_ranges_label(area.get("ranges"))
    if ranges:
        return f"surface {mode_label} dans les plages {ranges}"
    minimum = area.get("hard_min_area_km2")
    maximum = area.get("hard_max_area_km2")
    if minimum is not None and maximum is not None:
        return f"surface {mode_label} entre {minimum} et {maximum} km2"
    if minimum is not None:
        return f"surface {mode_label} >= {minimum} km2"
    if maximum is not None:
        return f"surface {mode_label} <= {maximum} km2"
    preferred = area.get("preferred_area_km2")
    if preferred is not None:
        return f"surface {mode_label} autour de {preferred} km2"
    return f"surface {mode_label}"


def _area_ranges_label(value: object) -> str:
    if not isinstance(value, list):
        return ""
    labels: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        minimum = item.get("min_area_km2")
        maximum = item.get("max_area_km2")
        if minimum is None or maximum is None:
            continue
        label = str(item.get("label") or item.get("range_id") or "").strip()
        bounds = f"{minimum}-{maximum} km2"
        labels.append(f"{label} ({bounds})" if label else bounds)
    return "; ".join(labels)


def _dem_explanation(
    dem: Mapping[str, Any],
    flow_products: Mapping[str, Any],
) -> str:
    request_extent = str(dem.get("request_extent") or "")
    map_extent = str(dem.get("map_background_extent") or "")
    has_map_dem = bool(flow_products.get("map_dem_path"))
    if has_map_dem and request_extent == "outlets" and map_extent == "territory":
        return (
            "Le calcul hydrologique utilise un DEM limite aux exutoires pour rester "
            "raisonnable en temps de calcul, tandis que la carte recharge un DEM "
            "regional pour donner le contexte visuel complet."
        )
    if has_map_dem:
        return "La carte utilise un DEM de fond dedie au controle visuel des bassins."
    return "La carte utilise les artefacts spatiaux disponibles dans le manifeste."


def _context_layer_summary(layers: list[Any]) -> str:
    if not layers:
        return "aucune"
    labels = []
    for layer in layers:
        if isinstance(layer, Mapping):
            labels.append(f"{layer.get('name', '')} ({layer.get('role', 'other')})")
        else:
            labels.append(str(layer))
    return ", ".join(label for label in labels if label)


def _format_score(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def _join_flags(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=True)


def _empty_row(columns: int) -> str:
    return f"<tr><td colspan=\"{columns}\" class=\"muted\">Aucune ligne.</td></tr>"


def _href(path: Path, html_dir: Path) -> str:
    return html.escape(os.path.relpath(path.resolve(), html_dir.resolve()).replace(os.sep, "/"))


def _image_src(path: Path, html_dir: Path) -> str:
    """Embed small PNG maps so IDE/browser previews keep the figure visible."""

    max_inline_bytes = 5_000_000
    if path.is_file() and path.suffix.lower() == ".png" and path.stat().st_size <= max_inline_bytes:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    return _href(path, html_dir)


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value))


__all__ = [
    "REPORT_DIR_NAME",
    "REPORT_HTML_NAME",
    "render_site_selection_html_report",
]
