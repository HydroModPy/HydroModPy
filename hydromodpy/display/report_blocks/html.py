"""Static HTML renderer for reusable report blocks."""

from __future__ import annotations

import html
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hydromodpy.display.report_blocks.model import ReportBlock, ReportFigure, ReportTable


def write_report_page(
    *,
    output_path: Path,
    title: str,
    blocks: Iterable[ReportBlock],
    subtitle: str = "",
    current_level: str = "",
    level_links: dict[str, Path] | None = None,
) -> Path:
    """Write one standalone HTML page and return its path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_report_page(
            title=title,
            blocks=blocks,
            web_dir=output_path.parent,
            subtitle=subtitle,
            current_level=current_level,
            level_links=level_links,
        ),
        encoding="utf-8",
    )
    return output_path


def render_report_page(
    *,
    title: str,
    blocks: Iterable[ReportBlock],
    web_dir: Path,
    subtitle: str = "",
    current_level: str = "",
    level_links: dict[str, Path] | None = None,
) -> str:
    """Render one complete static HTML page."""
    block_html = "\n".join(
        _render_block(block, web_dir=web_dir) for block in blocks if block.is_applicable
    )
    subtitle_html = f'<p class="subtitle">{_safe(subtitle)}</p>' if subtitle else ""
    nav_html = _render_level_nav(
        web_dir=web_dir,
        current_level=current_level,
        level_links=level_links or {},
    )
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_safe(title)}</title>
  <style>
{_STYLE}
  </style>
</head>
<body>
<main>
  <header>
    <p class="eyebrow">Fichier HTML de simulation</p>
    <h1>{_safe(title)}</h1>
    {subtitle_html}
    {nav_html}
  </header>
  {block_html}
</main>
</body>
</html>
"""


def _render_block(block: ReportBlock, *, web_dir: Path) -> str:
    status_class = f"status-{block.status.replace('_', '-')}"
    lead = f"<p>{_safe(block.lead)}</p>" if block.lead else ""
    metrics = _render_metrics(block) if block.metrics else ""
    figures = _render_figures(block.figures, web_dir=web_dir) if block.figures else ""
    tables = "\n".join(_render_table(table) for table in block.tables)
    warnings = _render_warnings(block.warnings)
    return f"""<section class="report-block {status_class}">
  <div class="block-title-row">
    <div>
      <h2>{_safe(block.title)}</h2>
    </div>
    <span class="level-pill">{_safe(block.level)}</span>
  </div>
  {lead}
  {metrics}
  {figures}
  {tables}
  {warnings}
</section>"""


def _render_metrics(block: ReportBlock) -> str:
    items = []
    for metric in block.metrics:
        value = _safe(metric.value)
        unit = f" <span>{_safe(metric.unit)}</span>" if metric.unit else ""
        note = f"<small>{_safe(metric.note)}</small>" if metric.note else ""
        items.append(
            f"""<div class="metric">
  <span>{_safe(metric.label)}</span>
  <strong>{value}{unit}</strong>
  {note}
</div>"""
        )
    return f'<div class="metric-grid">{"".join(items)}</div>'


def _render_figures(figures: Iterable[ReportFigure], *, web_dir: Path) -> str:
    cards = []
    for figure in figures:
        if not figure.available or figure.path is None:
            continue
        href = _link_relative(web_dir, figure.path)
        caption = _figure_caption(figure)
        cards.append(
            f"""<figure>
  <a href="{_safe(href)}"><img src="{_safe(href)}" alt="{_safe(figure.title)}"></a>
  {caption}
</figure>"""
        )
    return f'<div class="figure-grid">{"".join(cards)}</div>' if cards else ""


def _figure_caption(figure: ReportFigure) -> str:
    if not figure.title and not figure.caption:
        return ""
    title = f"<strong>{_safe(figure.title)}</strong>" if figure.title else ""
    caption = f"<br><span>{_safe(figure.caption)}</span>" if figure.caption else ""
    return f"<figcaption>{title}{caption}</figcaption>"


def _render_level_nav(
    *,
    web_dir: Path,
    current_level: str,
    level_links: dict[str, Path],
) -> str:
    if not level_links:
        return ""
    labels = {
        "compact": "Compact",
        "standard": "Standard",
        "audit": "Audit",
    }
    buttons = []
    for level in ("compact", "standard", "audit"):
        path = level_links.get(level)
        if path is None:
            continue
        classes = "level-button is-active" if level == current_level else "level-button"
        aria_current = ' aria-current="page"' if level == current_level else ""
        buttons.append(
            f'<a class="{classes}" href="{_safe(_link_relative(web_dir, path))}"'
            f"{aria_current}>{_safe(labels.get(level, level))}</a>"
        )
    if not buttons:
        return ""
    return f"""<nav class="level-nav" id="report-level" aria-label="Niveau du rapport">
  <span>Niveau</span>
  <div class="level-buttons">{"".join(buttons)}</div>
</nav>"""


def _render_table(table: ReportTable) -> str:
    if not table.rows:
        body = f'<p class="muted">{_safe(table.empty_message)}</p>'
    else:
        header = "".join(f"<th>{_safe(label)}</th>" for _, label in table.columns)
        rows = []
        for row in table.rows:
            cells = "".join(
                f"<td>{_safe(_short(row.get(key, '')))}</td>" for key, _ in table.columns
            )
            rows.append(f"<tr>{cells}</tr>")
        body = f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    return f"""<div class="table-block">
  <h3>{_safe(table.title)}</h3>
  {body}
</div>"""


def _render_warnings(warnings: Iterable[str]) -> str:
    items = [f"<li>{_safe(item)}</li>" for item in warnings if str(item).strip()]
    if not items:
        return ""
    return f'<ul class="warning-list">{"".join(items)}</ul>'


def _safe(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _short(value: Any, *, limit: int = 120) -> str:
    text = str(value if value is not None else "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def _link_relative(web_dir: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(web_dir.resolve()).as_posix()
    except Exception:
        return os.path.relpath(Path(path).resolve(), web_dir.resolve()).replace("\\", "/")


_STYLE = """    :root {
      --ink: #162033;
      --muted: #64748b;
      --line: #d7dee8;
      --panel: #ffffff;
      --soft: #f4f7fa;
      --accent: #0f766e;
      --warn: #9a3412;
      --missing: #f8e5dc;
    }
    * { box-sizing: border-box; }
    html {
      font-size: 125%;
    }
    body {
      margin: 0;
      background: #f7f8fa;
      color: var(--ink);
      font-family: "Aptos", "Segoe UI", sans-serif;
      font-size: 1rem;
      line-height: 1.45;
    }
    main { max-width: 1500px; margin: 0 auto; padding: 30px 20px 58px; }
    header { padding-bottom: 18px; border-bottom: 1px solid var(--line); }
    h1, h2, h3, p { margin-top: 0; }
    h1 { margin-bottom: 8px; font-size: 2.1rem; letter-spacing: 0; }
    h2 { margin-bottom: 0; font-size: 1.35rem; letter-spacing: 0; }
    h3 { margin-bottom: 10px; font-size: 1rem; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .eyebrow, .block-id {
      color: var(--muted);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 6px;
    }
    .subtitle, .muted { color: var(--muted); }
    .level-nav {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      margin-top: 12px;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }
    .level-nav span {
      color: var(--muted);
      font-size: 0.86rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .level-buttons {
      display: inline-flex;
      gap: 4px;
    }
    .level-button {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 10px;
      background: #fff;
      color: var(--ink);
      font-size: 0.9rem;
      font-weight: 700;
    }
    .level-button:hover {
      text-decoration: none;
      border-color: var(--accent);
    }
    .level-button.is-active {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    .report-block {
      margin-top: 20px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }
    .report-block.status-not-applicable { background: #fbfcfd; }
    .block-title-row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 12px;
    }
    .level-pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 14px 0;
    }
    .metric {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 11px 12px;
      background: var(--soft);
    }
    .metric > span {
      display: block;
      color: var(--muted);
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      margin-bottom: 4px;
    }
    .metric strong { display: block; overflow-wrap: anywhere; font-size: 1.02rem; }
    .metric small { display: block; margin-top: 4px; color: var(--muted); }
    .figure-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin: 14px 0;
    }
    figure {
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fff;
    }
    figure img { display: block; width: 100%; border-radius: 6px; background: var(--soft); }
    figcaption { margin-top: 9px; color: var(--muted); font-size: 0.94rem; }
    .figure-placeholder {
      display: grid;
      min-height: 190px;
      place-items: center;
      border-radius: 6px;
      background: var(--missing);
      color: var(--warn);
      font-weight: 700;
    }
    .table-block { margin-top: 14px; }
    table { width: 100%; border-collapse: collapse; border: 1px solid var(--line); }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 0.94rem;
    }
    th {
      background: #edf4f2;
      color: #24433f;
      font-size: 0.78rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .warning-list {
      margin: 14px 0 0;
      padding-left: 22px;
      color: var(--warn);
      font-weight: 650;
    }
    @media (max-width: 880px) {
      main { padding: 18px 12px 42px; }
      .metric-grid, .figure-grid { grid-template-columns: 1fr; }
      .block-title-row { display: block; }
      .level-pill { display: inline-block; margin-top: 10px; }
    }"""
