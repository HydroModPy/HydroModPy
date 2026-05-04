"""Small static HTML report for materialized comparison outputs."""

from __future__ import annotations

import csv
import html
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def write_comparison_web_report(
    *,
    comparison_root: Path,
    manifest: Mapping[str, Any] | None = None,
    output_path: Path | None = None,
) -> Path:
    """Write a browser-readable overview page for one comparison output folder."""
    root = Path(comparison_root).expanduser().resolve()
    payload = dict(manifest or _load_json(root / "comparison_manifest.json"))
    web_dir = root / "web"
    out = output_path or (web_dir / "index.html")
    web_dir.mkdir(parents=True, exist_ok=True)

    metrics_rows = _load_csv(root / "comparison_metrics.csv")
    budget_rows = _load_csv(root / "budget_timeseries_wide.csv")
    audit = _load_json(root / "comparison_audit.json")
    figure_items = _figure_items(root=root, manifest=payload)
    key_figures = _select_key_figures(figure_items)

    simulations = payload.get("simulations", [])
    if not isinstance(simulations, list):
        simulations = []
    data_links = _data_links(root)
    comparable_budget_rows = [
        row
        for row in budget_rows
        if str(row.get("component", "")) == "comparable_outflow_total_m3_s"
    ]

    html_text = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_safe(payload.get("comparison_id", "Comparison report"))}</title>
  <style>
    :root {{
      --ink: #162033;
      --muted: #617086;
      --line: #d8e0ea;
      --panel: #ffffff;
      --soft: #eef4f8;
      --accent: #0f766e;
      --warn: #b45309;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: linear-gradient(135deg, #edf7f4 0%, #f7f1e6 42%, #eef3fb 100%);
      color: var(--ink);
      font-family: "Aptos", "Segoe UI", sans-serif;
      line-height: 1.48;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 30px 22px 60px; }}
    header {{
      padding: 28px;
      border: 1px solid rgba(22, 32, 51, 0.12);
      border-radius: 26px;
      background: rgba(255, 255, 255, 0.78);
      box-shadow: 0 18px 60px rgba(22, 32, 51, 0.11);
      backdrop-filter: blur(6px);
    }}
    h1 {{ margin: 0 0 8px; font-size: clamp(2rem, 4vw, 4rem); letter-spacing: -0.05em; }}
    h2 {{ margin: 0 0 14px; font-size: 1.35rem; letter-spacing: -0.02em; }}
    h3 {{ margin: 0 0 8px; font-size: 1.0rem; }}
    p {{ margin: 0 0 10px; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .muted {{ color: var(--muted); }}
    .pillrow {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }}
    .pill {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 10px; border-radius: 999px;
      background: #e4f1ef; color: #0f4f49; font-weight: 650; font-size: 0.88rem;
    }}
    section {{ margin-top: 22px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    .facts {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }}
    .card, .fact {{
      background: rgba(255, 255, 255, 0.86);
      border: 1px solid rgba(22, 32, 51, 0.11);
      border-radius: 18px; padding: 16px;
      box-shadow: 0 10px 28px rgba(22, 32, 51, 0.07);
    }}
    .fact span {{ display: block; color: var(--muted); font-size: 0.82rem; }}
    .fact strong {{ display: block; margin-top: 4px; font-size: 1.08rem; }}
    .figure-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    figure {{ margin: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 12px; }}
    figure img {{ width: 100%; display: block; border-radius: 12px; background: var(--soft); }}
    figcaption {{ margin-top: 9px; color: var(--muted); font-size: 0.9rem; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 14px; overflow: hidden; }}
    th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; font-size: 0.9rem; }}
    th {{ background: #edf4f2; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    code {{ background: rgba(15, 118, 110, 0.1); padding: 2px 5px; border-radius: 5px; }}
    .warning {{ color: var(--warn); font-weight: 700; }}
    @media (max-width: 880px) {{ .grid, .facts, .figure-grid {{ grid-template-columns: 1fr; }} main {{ padding: 18px 12px 42px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <p class="muted">Rapport HTML standard genere depuis les sorties de comparaison.</p>
    <h1>{_safe(payload.get("comparison_id", "Comparison report"))}</h1>
    <p>Lecture rapide des simulations, metriques, figures et flux comparables. Cette page ne relance aucun solveur.</p>
    <div class="pillrow">
      <span class="pill">Audit: {_safe(payload.get("audit_status", audit.get("status", "")))}</span>
      <span class="pill">Reference: {_safe(payload.get("reference_simulation", ""))}</span>
      <span class="pill">Figures: {_safe(len(figure_items))}</span>
      <span class="pill">Web root: {_safe(_relative(root, web_dir))}</span>
    </div>
  </header>

  <section class="facts">
    <div class="fact"><span>Simulations</span><strong>{_safe(len(simulations))}</strong></div>
    <div class="fact"><span>Metriques</span><strong>{_safe(len(metrics_rows))}</strong></div>
    <div class="fact"><span>Lignes budget</span><strong>{_safe(len(budget_rows))}</strong></div>
    <div class="fact"><span>Flux comparable</span><strong>{_safe(len(comparable_budget_rows))}</strong></div>
  </section>

  <section class="grid">
    <div class="card">
      <h2>Principe de lecture</h2>
      <p>Les sorties natives restent visibles. Pour comparer les flux entre solveurs, utiliser <code>comparable_outflow_total_m3_s</code>.</p>
      <p>Definition: <code>drainage_total_m3_s + surface_excess_total_m3_s</code>. Une composante absente vaut zero.</p>
      <p class="muted">Cela evite de comparer directement un drain MF6 a un excedent de surface Boussinesq, qui ne portent pas exactement la meme semantique.</p>
    </div>
    <div class="card">
      <h2>Audit format</h2>
      {_audit_block(audit)}
    </div>
  </section>

  <section>
    <h2>Figures cles</h2>
    <div class="figure-grid">
      {_render_figures(root=root, web_dir=web_dir, figures=key_figures)}
    </div>
  </section>

  <section class="grid">
    <div class="card">
      <h2>Simulations</h2>
      {_render_table(simulations, [("id", "id"), ("solver", "solver"), ("mesh_mode", "mesh"), ("status", "status"), ("wall_time_seconds", "runtime s")], empty="Aucune simulation dans le manifeste.")}
    </div>
    <div class="card">
      <h2>Fichiers</h2>
      {_render_links(root=root, web_dir=web_dir, links=data_links)}
    </div>
  </section>

  <section>
    <h2>Flux sortant comparable</h2>
    {_render_table(comparable_budget_rows[:16], [("time_label", "temps"), ("period_index", "periode"), ("value__mf6_ref", "mf6_ref"), ("value__bouss_candidate", "bouss_candidate")], empty="Aucune ligne comparable_outflow_total_m3_s trouvee.")}
  </section>

  <section>
    <h2>Metriques principales</h2>
    {_render_table(metrics_rows[:24], [("simulation_id", "simulation"), ("observable", "observable"), ("n_pairs", "n"), ("mae", "mae"), ("rmse", "rmse"), ("max_abs_error", "max abs")], empty="Aucune metrique.")}
  </section>
</main>
</body>
</html>
"""
    out.write_text(html_text, encoding="utf-8")
    return out


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _safe(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _relative(root: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def _link_relative(web_dir: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(web_dir.resolve()).as_posix()
    except Exception:
        try:
            import os

            return os.path.relpath(Path(path).resolve(), web_dir.resolve()).replace(
                "\\", "/"
            )
        except Exception:
            return str(path)


def _figure_items(*, root: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    raw_items = manifest.get("comparison_figures", [])
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, Mapping) and str(item.get("path", "")):
                path = Path(str(item["path"]))
                if not path.is_absolute():
                    path = root / path
                if path.is_file():
                    payload = dict(item)
                    payload["path"] = str(path)
                    items.append(payload)
    known = {str(Path(str(item.get("path", ""))).resolve()) for item in items}
    figure_root = root / "comparison_figures"
    if figure_root.is_dir():
        for path in sorted(figure_root.glob("*.png")):
            key = str(path.resolve())
            if key not in known:
                items.append(
                    {"kind": "figure", "observable": path.stem, "path": str(path)}
                )
    return items


def _select_key_figures(
    figures: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    priority = (
        "case_configuration.png",
        "comparable_outflow_dashboard.png",
        "flux_overview.png",
        "head_points_dashboard.png",
        "head_map_after_first_month__triptych",
        "head_map_wet_period__triptych",
        "head_map_dry_period__triptych",
        "head_map_last__triptych",
        "mf6_ref__budget_diagnostics.png",
        "bouss_candidate__budget_diagnostics.png",
        "execution_time_comparison.png",
    )

    def score(item: Mapping[str, Any]) -> tuple[int, str]:
        name = Path(str(item.get("path", ""))).name
        for index, token in enumerate(priority):
            if token in name:
                return (index, name)
        return (len(priority), name)

    return sorted(list(figures), key=score)[:18]


def _render_figures(
    *,
    root: Path,
    web_dir: Path,
    figures: Iterable[Mapping[str, Any]],
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
            f'<a href="{_safe(_link_relative(web_dir, path))}">'
            f'<img src="{_safe(_link_relative(web_dir, path))}" alt="{_safe(title)}">'
            "</a>"
            f"<figcaption>{_safe(title)}"
            + (f" - {_safe(kind)}" if kind else "")
            + "</figcaption></figure>"
        )
    if not blocks:
        return '<p class="muted">Aucune figure PNG disponible.</p>'
    return "\n".join(blocks)


def _render_table(
    rows: Iterable[Mapping[str, Any]],
    columns: list[tuple[str, str]],
    *,
    empty: str,
) -> str:
    materialized = list(rows)
    if not materialized:
        return f'<p class="muted">{_safe(empty)}</p>'
    header = "".join(f"<th>{_safe(label)}</th>" for _, label in columns)
    body_rows: list[str] = []
    for row in materialized:
        cells = "".join(
            f"<td>{_safe(_short(row.get(key, '')))}</td>" for key, _ in columns
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _render_links(
    *,
    root: Path,
    web_dir: Path,
    links: Iterable[Path],
) -> str:
    blocks = []
    for path in links:
        if not path.exists():
            continue
        blocks.append(
            f'<p><a href="{_safe(_link_relative(web_dir, path))}">'
            f"{_safe(_relative(root, path))}</a></p>"
        )
    return "\n".join(blocks) if blocks else '<p class="muted">Aucun fichier cle.</p>'


def _data_links(root: Path) -> list[Path]:
    names = (
        "comparison_report.md",
        "comparison_audit.md",
        "comparison_manifest.json",
        "comparison_metrics.csv",
        "comparison_differences.csv",
        "observables.csv",
        "budget_timeseries_wide.csv",
        "budget_timeseries_long.csv",
        "timeseries_wide.csv",
        "timeseries_long.csv",
    )
    return [root / name for name in names]


def _audit_block(audit: Mapping[str, Any]) -> str:
    status = str(audit.get("status", ""))
    issues = audit.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    klass = "warning" if status == "warn" else ""
    lines = [
        f'<p>Status: <strong class="{klass}">{_safe(status or "unknown")}</strong></p>'
    ]
    lines.append(f"<p>Issues: <strong>{_safe(len(issues))}</strong></p>")
    for issue in issues[:5]:
        if isinstance(issue, Mapping):
            message = issue.get("message", issue.get("description", issue))
        else:
            message = issue
        lines.append(f'<p class="muted">- {_safe(_short(message, limit=170))}</p>')
    return "\n".join(lines)


def _short(value: Any, *, limit: int = 80) -> str:
    text = str(value if value is not None else "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


__all__ = ("write_comparison_web_report",)
