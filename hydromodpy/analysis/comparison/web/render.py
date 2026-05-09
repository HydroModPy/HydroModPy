"""Renderer for static simulation-comparison web reports."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.web.context import load_comparison_web_context
from hydromodpy.analysis.comparison.web.html_utils import safe
from hydromodpy.analysis.comparison.web.sections import (
    report_title,
    render_facts,
    render_header,
    render_sections,
)


def write_comparison_web_report(
    *,
    comparison_root: Path,
    manifest: Mapping[str, Any] | None = None,
    output_path: Path | None = None,
) -> Path:
    """Write a browser-readable overview page for one comparison output folder."""
    ctx = load_comparison_web_context(
        comparison_root=comparison_root,
        manifest=manifest,
        output_path=output_path,
    )
    ctx.web_dir.mkdir(parents=True, exist_ok=True)
    ctx.output_path.write_text(_render_page(ctx), encoding="utf-8")
    return ctx.output_path


def _render_page(ctx: Any) -> str:
    title = report_title(ctx)
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe(title)}</title>
  <style>
{_STYLE}
  </style>
</head>
<body>
<main>
{render_header(ctx)}
{render_facts(ctx)}
{render_sections(ctx)}
</main>
</body>
</html>
"""


_STYLE = """    :root {
      --ink: #162033;
      --muted: #617086;
      --line: #d8e0ea;
      --panel: #ffffff;
      --soft: #eef4f8;
      --accent: #0f766e;
      --warn: #b45309;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: #f7f8fa;
      color: var(--ink);
      font-family: "Aptos", "Segoe UI", sans-serif;
      line-height: 1.48;
    }
    main { max-width: 1180px; margin: 0 auto; padding: 30px 22px 60px; }
    header {
      padding: 0 0 18px;
      border-bottom: 1px solid var(--line);
    }
    h1 { margin: 0 0 8px; font-size: 2rem; letter-spacing: 0; }
    h2 { margin: 0 0 14px; font-size: 1.25rem; letter-spacing: 0; }
    h3 { margin: 0 0 8px; font-size: 1.0rem; }
    p { margin: 0 0 10px; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .muted { color: var(--muted); }
    .pillrow { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
    .pill {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 10px; border-radius: 999px;
      background: #e4f1ef; color: #0f4f49; font-weight: 650; font-size: 0.88rem;
    }
    section { margin-top: 22px; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
    .card, .fact {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px; padding: 16px;
    }
    .info-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px 14px;
      margin: 14px 0 12px;
    }
    .info-grid > div {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      background: #fbfcfd;
    }
    .kv-label {
      display: block;
      color: var(--muted);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 3px;
    }
    .info-grid strong { font-size: 0.94rem; font-weight: 600; }
    .fact span { display: block; color: var(--muted); font-size: 0.82rem; }
    .fact strong { display: block; margin-top: 4px; font-size: 1.08rem; }
    .figure-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .figure-grid.compact { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .context-figure-grid { grid-template-columns: 1fr; }
    .context-figure-grid figure { padding: 14px; }
    .figure-category { margin-top: 14px; }
    .figure-category h3 { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
    figure { margin: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
    figure img { width: 100%; display: block; border-radius: 6px; background: var(--soft); }
    figcaption { margin-top: 9px; color: var(--muted); font-size: 0.9rem; }
    table { width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 8px; overflow: hidden; }
    th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; font-size: 0.9rem; }
    th { background: #edf4f2; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }
    code { background: rgba(15, 118, 110, 0.1); padding: 2px 5px; border-radius: 5px; }
    .warning { color: var(--warn); font-weight: 700; }
    @media (max-width: 880px) {
      .grid, .facts, .figure-grid, .figure-grid.compact, .info-grid { grid-template-columns: 1fr; }
      main { padding: 18px 12px 42px; }
    }"""


__all__ = ("write_comparison_web_report",)
