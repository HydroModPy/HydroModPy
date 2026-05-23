"""Static HTML report for site-selection planning manifests."""

from __future__ import annotations

import html
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PLAN_REPORT_DIR_NAME = "review"
PLAN_REPORT_HTML_NAME = "index.html"


def render_site_selection_plan_html_report(
    plan_manifest_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    """Render a static HTML review page from a plan-only manifest."""

    manifest_file = Path(plan_manifest_path).expanduser().resolve()
    plan = json.loads(manifest_file.read_text(encoding="utf-8"))
    output_root = Path(str(plan.get("output_root") or manifest_file.parent)).expanduser()
    if not output_root.is_absolute():
        output_root = (manifest_file.parent / output_root).resolve()
    else:
        output_root = output_root.resolve()

    destination = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else output_root / PLAN_REPORT_DIR_NAME / PLAN_REPORT_HTML_NAME
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        _render_plan_html(
            plan=plan,
            manifest_path=manifest_file,
            output_path=destination,
            output_root=output_root,
        ),
        encoding="utf-8",
    )
    return destination


def _render_plan_html(
    *,
    plan: Mapping[str, Any],
    manifest_path: Path,
    output_path: Path,
    output_root: Path,
) -> str:
    selection_id = str(plan.get("selection_id") or "site_selection_plan")
    strategy = _mapping(plan.get("strategy"))
    territory = _mapping(plan.get("territory"))
    dem = _mapping(plan.get("dem"))
    input_cfg = _mapping(plan.get("input"))
    hydrology = _mapping(plan.get("hydrology"))
    criteria = _mapping(plan.get("criteria"))
    map_context = _mapping(plan.get("map_context"))
    context_layers = _sequence(map_context.get("layers"))
    planned_outputs = _sequence(plan.get("planned_outputs"))
    output_dir = output_path.parent

    planned_output_items = "\n".join(
        f"<li><code>{_e(item)}</code></li>" for item in planned_outputs
    )
    criteria_rows = "\n".join(
        _kv_row(label, criteria.get(key))
        for label, key in (
            ("Ruleset", "ruleset"),
            ("Hard reject", "hard_reject"),
            ("Warning", "warning"),
            ("Soft score", "soft_score"),
            ("Report only", "report_only"),
            ("Surface", "area_mode"),
            ("Plages surface", "area_ranges"),
            ("Hydrometrie", "flow_station_mode"),
            ("Piezometrie", "piezometer_mode"),
            ("Geologie", "geology_mode"),
        )
    )

    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(selection_id)} - Site Selection Plan</title>
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
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 15px;
      line-height: 1.45;
    }}
    header, main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    header {{ padding-top: 32px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; font-weight: 650; }}
    h2 {{ margin: 0 0 14px; font-size: 19px; font-weight: 650; }}
    section {{
      background: var(--band);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin: 0 0 18px;
    }}
    .muted {{ color: var(--muted); }}
    .notice {{
      border-left: 4px solid var(--warn);
      background: #fff8eb;
      padding: 12px 14px;
      margin-top: 18px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 10px;
      margin-top: 18px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: #fbfcfe;
    }}
    .metric strong {{ display: block; font-size: 22px; margin-bottom: 2px; }}
    dl {{
      display: grid;
      grid-template-columns: minmax(170px, 280px) 1fr;
      gap: 8px 18px;
      margin: 0;
    }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px 10px; text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; background: #f8fafc; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.92em; }}
    ul {{ margin: 0; padding-left: 20px; }}
  </style>
</head>
<body>
  <header>
    <p class="muted">Rapport HTML de plan - site selection HydroModPy</p>
    <h1>{_e(selection_id)}</h1>
    <p class="muted">Ce rapport decrit la strategie configuree avant execution spatiale.</p>
    <div class="notice">
      Aucun site n'est retenu ou rejete dans ce rapport: le mode courant est
      <code>{_e(input_cfg.get("mode") or "plan_only")}</code>.
    </div>
    <div class="summary">
      {_metric("Principe", strategy.get("principle"))}
      {_metric("Profil", strategy.get("profile") or "-")}
      {_metric("Mode candidats", strategy.get("candidate_mode") or "-")}
      {_metric("Sorties prevues", len(planned_outputs))}
    </div>
  </header>
  <main>
    <section>
      <h2>Strategie</h2>
      <dl>
        <dt>Observation principale</dt><dd><code>{_e(strategy.get("primary_observation_type"))}</code></dd>
        <dt>Axes principaux</dt><dd>{_e(_format_value(strategy.get("primary_axes")))}</dd>
        <dt>Territoire</dt><dd>{_e(_territory_label(territory))}</dd>
        <dt>Racine de sortie</dt><dd><code>{_e(output_root)}</code></dd>
        <dt>Couches contexte</dt><dd>{_e(_context_layer_summary(context_layers))}</dd>
      </dl>
    </section>

    <section>
      <h2>Donnees et calculs prevus</h2>
      <dl>
        <dt>Source DEM</dt><dd><code>{_e(dem.get("source"))}</code></dd>
        <dt>Chemin DEM</dt><dd><code>{_e(dem.get("path"))}</code></dd>
        <dt>Resolution DEM</dt><dd>{_e(dem.get("resolution_m"))} m</dd>
        <dt>Politique cache</dt><dd><code>{_e(dem.get("cache_policy"))}</code></dd>
        <dt>Methode hydrologique</dt><dd><code>{_e(hydrology.get("method"))}</code></dd>
        <dt>Algorithme d'ecoulement</dt><dd><code>{_e(hydrology.get("flow_algorithm"))}</code></dd>
        <dt>Conditionnement DEM</dt><dd><code>{_e(hydrology.get("dem_correction_type"))}</code></dd>
      </dl>
    </section>

    <section>
      <h2>Criteres</h2>
      <table>
        <thead><tr><th>Element</th><th>Configuration</th></tr></thead>
        <tbody>{criteria_rows}</tbody>
      </table>
    </section>

    <section>
      <h2>Sorties prevues</h2>
      <ul>{planned_output_items or "<li>Aucune sortie prevue.</li>"}</ul>
    </section>

    <section>
      <h2>Artefacts disponibles</h2>
      <ul>
        <li><a href="{_href(manifest_path, output_dir)}"><code>{_e(manifest_path.name)}</code></a></li>
      </ul>
    </section>
  </main>
</body>
</html>
"""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _metric(label: str, value: object) -> str:
    return f"<div class=\"metric\"><strong>{_e(value)}</strong>{_e(label)}</div>"


def _kv_row(label: str, value: object) -> str:
    return f"<tr><td>{_e(label)}</td><td><code>{_e(_format_value(value))}</code></td></tr>"


def _territory_label(territory: Mapping[str, Any]) -> str:
    parts = [str(territory.get("mode") or "")]
    if territory.get("regions"):
        parts.append(", ".join(str(item) for item in territory["regions"]))
    if territory.get("departments"):
        parts.append(", ".join(str(item) for item in territory["departments"]))
    if territory.get("bbox"):
        parts.append(str(territory["bbox"]))
    return " - ".join(part for part in parts if part)


def _format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value)


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


def _href(path: Path, html_dir: Path) -> str:
    return html.escape(os.path.relpath(path.resolve(), html_dir.resolve()).replace(os.sep, "/"))


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value))


__all__ = [
    "PLAN_REPORT_DIR_NAME",
    "PLAN_REPORT_HTML_NAME",
    "render_site_selection_plan_html_report",
]
