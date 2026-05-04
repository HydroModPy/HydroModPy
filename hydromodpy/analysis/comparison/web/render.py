"""Renderer for static simulation-comparison web reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from hydromodpy.analysis.comparison.web.context import load_comparison_web_context
from hydromodpy.analysis.comparison.web.html_utils import safe
from hydromodpy.analysis.comparison.web.sections import (
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
    title = ctx.manifest.get("comparison_id", "Comparison report")
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
      background: linear-gradient(135deg, #edf7f4 0%, #f7f1e6 42%, #eef3fb 100%);
      color: var(--ink);
      font-family: "Aptos", "Segoe UI", sans-serif;
      line-height: 1.48;
    }
    main { max-width: 1180px; margin: 0 auto; padding: 30px 22px 60px; }
    header {
      padding: 28px;
      border: 1px solid rgba(22, 32, 51, 0.12);
      border-radius: 26px;
      background: rgba(255, 255, 255, 0.78);
      box-shadow: 0 18px 60px rgba(22, 32, 51, 0.11);
      backdrop-filter: blur(6px);
    }
    h1 { margin: 0 0 8px; font-size: clamp(2rem, 4vw, 4rem); letter-spacing: -0.05em; }
    h2 { margin: 0 0 14px; font-size: 1.35rem; letter-spacing: -0.02em; }
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
      background: rgba(255, 255, 255, 0.86);
      border: 1px solid rgba(22, 32, 51, 0.11);
      border-radius: 18px; padding: 16px;
      box-shadow: 0 10px 28px rgba(22, 32, 51, 0.07);
    }
    .fact span { display: block; color: var(--muted); font-size: 0.82rem; }
    .fact strong { display: block; margin-top: 4px; font-size: 1.08rem; }
    .figure-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    figure { margin: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 12px; }
    figure img { width: 100%; display: block; border-radius: 12px; background: var(--soft); }
    figcaption { margin-top: 9px; color: var(--muted); font-size: 0.9rem; }
    table { width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 14px; overflow: hidden; }
    th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; font-size: 0.9rem; }
    th { background: #edf4f2; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }
    code { background: rgba(15, 118, 110, 0.1); padding: 2px 5px; border-radius: 5px; }
    .warning { color: var(--warn); font-weight: 700; }
    @media (max-width: 880px) {
      .grid, .facts, .figure-grid { grid-template-columns: 1fr; }
      main { padding: 18px 12px 42px; }
    }"""


__all__ = ("write_comparison_web_report",)
