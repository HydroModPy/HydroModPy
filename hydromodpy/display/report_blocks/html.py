"""Static HTML renderer for reusable report blocks."""

from __future__ import annotations

import base64
import html
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.display.report_blocks.model import (
    ReportBlock,
    ReportFigure,
    ReportLink,
    ReportTable,
)


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
        _without_trailing_whitespace(
            render_report_page(
                title=title,
                blocks=blocks,
                web_dir=output_path.parent,
                subtitle=subtitle,
                current_level=current_level,
                level_links=level_links,
            )
        ),
        encoding="utf-8",
    )
    return output_path


def write_report_page_with_block_variants(
    *,
    output_path: Path,
    title: str,
    block_variants: Mapping[str, Mapping[str, ReportBlock]]
    | Sequence[tuple[str, Mapping[str, ReportBlock]]],
    subtitle: str = "",
    current_level: str = "by_block",
    default_level: str = "standard",
    level_links: dict[str, Path] | None = None,
) -> Path:
    """Write one page where each block can choose its own detail level."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _without_trailing_whitespace(
            render_report_page_with_block_variants(
                title=title,
                block_variants=block_variants,
                web_dir=output_path.parent,
                subtitle=subtitle,
                current_level=current_level,
                default_level=default_level,
                level_links=level_links,
            )
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
    block_list = tuple(block for block in blocks if block.is_applicable)
    block_html = "\n".join(_render_block(block, web_dir=web_dir) for block in block_list)
    subtitle_html = f'<p class="subtitle">{_safe_text(subtitle)}</p>' if subtitle else ""
    nav_html = _render_level_nav(
        web_dir=web_dir,
        current_level=current_level,
        level_links=level_links or {},
    )
    toc_html = _render_toc(block_list)
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_safe_text(title)}</title>
  <style>
{_STYLE}
  </style>
</head>
<body>
<main>
  <header>
    <p class="eyebrow">Fichier HTML de simulation</p>
    <h1>{_safe_text(title)}</h1>
    {subtitle_html}
    {nav_html}
    {toc_html}
  </header>
  {block_html}
</main>
</body>
</html>
"""


def render_report_page_with_block_variants(
    *,
    title: str,
    block_variants: Mapping[str, Mapping[str, ReportBlock]]
    | Sequence[tuple[str, Mapping[str, ReportBlock]]],
    web_dir: Path,
    subtitle: str = "",
    current_level: str = "by_block",
    default_level: str = "standard",
    level_links: dict[str, Path] | None = None,
) -> str:
    """Render one static HTML page with per-block level controls."""
    groups = _normalize_block_variants(block_variants)
    visible_blocks = tuple(_default_variant(variants, default_level) for _, variants in groups)
    body_html = "\n".join(
        _render_block_variant_group(
            block_id=block_id,
            variants=variants,
            web_dir=web_dir,
            default_level=default_level,
        )
        for block_id, variants in groups
    )
    subtitle_html = f'<p class="subtitle">{_safe_text(subtitle)}</p>' if subtitle else ""
    nav_html = _render_level_nav(
        web_dir=web_dir,
        current_level=current_level,
        level_links=level_links or {},
    )
    toc_html = _render_toc(visible_blocks)
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_safe_text(title)}</title>
  <style>
{_STYLE}
  </style>
</head>
<body>
<main>
  <header>
    <p class="eyebrow">Fichier HTML de simulation</p>
    <h1>{_safe_text(title)}</h1>
    {subtitle_html}
    {nav_html}
    {toc_html}
  </header>
  {body_html}
</main>
{_BLOCK_LEVEL_SCRIPT}
</body>
</html>
"""


def _render_block(block: ReportBlock, *, web_dir: Path) -> str:
    return _render_block_with_anchor(block, web_dir=web_dir, anchor=_anchor_id(block.block_id))


def _render_block_with_anchor(block: ReportBlock, *, web_dir: Path, anchor: str) -> str:
    status_class = f"status-{block.status.replace('_', '-')}"
    lead = f"<p>{_safe(block.lead)}</p>" if block.lead else ""
    metrics = _render_metrics(block) if block.metrics else ""
    figures = _render_figures(block.figures, web_dir=web_dir) if block.figures else ""
    tables = "\n".join(_render_table(table) for table in block.tables)
    links = _render_links(block.links, web_dir=web_dir) if block.links else ""
    warnings = _render_warnings(block.warnings)
    status = _render_status(block.status)
    return f"""<section class="report-block {status_class}" id="{_safe(anchor)}">
  <div class="block-title-row">
    <div>
      <h2>{_safe_text(block.title)}</h2>
    </div>
    <div class="block-pills">
      {status}
      <span class="level-pill">{_safe(block.level)}</span>
    </div>
  </div>
  {lead}
  {metrics}
  {figures}
  {tables}
  {links}
  {warnings}
</section>"""


def _normalize_block_variants(
    block_variants: Mapping[str, Mapping[str, ReportBlock]]
    | Sequence[tuple[str, Mapping[str, ReportBlock]]],
) -> tuple[tuple[str, dict[str, ReportBlock]], ...]:
    raw_items = block_variants.items() if isinstance(block_variants, Mapping) else block_variants
    groups: list[tuple[str, dict[str, ReportBlock]]] = []
    for block_id, variants in raw_items:
        applicable = {str(level): block for level, block in variants.items() if block.is_applicable}
        if applicable:
            groups.append((str(block_id), applicable))
    return tuple(groups)


def _default_variant(variants: Mapping[str, ReportBlock], default_level: str) -> ReportBlock:
    if default_level in variants:
        return variants[default_level]
    for level in ("standard", "compact", "audit"):
        if level in variants:
            return variants[level]
    return next(iter(variants.values()))


def _render_block_variant_group(
    *,
    block_id: str,
    variants: Mapping[str, ReportBlock],
    web_dir: Path,
    default_level: str,
) -> str:
    anchor = _anchor_id(block_id)
    levels = tuple(level for level in ("compact", "standard", "audit") if level in variants)
    if not levels:
        return ""
    initial = default_level if default_level in variants else levels[0]
    buttons = "".join(
        _render_block_level_button(level=level, active=level == initial) for level in levels
    )
    rendered_variants = []
    for level in levels:
        hidden = "" if level == initial else " hidden"
        rendered = _render_block_with_anchor(
            variants[level],
            web_dir=web_dir,
            anchor=f"{anchor}-{_anchor_id(level)}",
        )
        rendered_variants.append(
            f'<div class="block-variant" data-block-level="{_safe(level)}"{hidden}>{rendered}</div>'
        )
    return f"""<div class="block-variant-group" id="{_safe(anchor)}" data-block-group="{_safe(anchor)}" data-default-level="{_safe(initial)}">
  <div class="block-level-switch" role="group" aria-label="Niveau du bloc {_safe(variants[initial].title)}">
    <span>Niveau du bloc</span>
    <div class="block-level-buttons">{buttons}</div>
  </div>
  {"".join(rendered_variants)}
</div>"""


def _render_block_level_button(*, level: str, active: bool) -> str:
    labels = {
        "compact": "Compact",
        "standard": "Standard",
        "audit": "Audit",
    }
    active_class = " is-active" if active else ""
    aria_pressed = "true" if active else "false"
    return (
        f'<button type="button" class="block-level-button{active_class}" '
        f'data-target-level="{_safe(level)}" aria-pressed="{aria_pressed}">'
        f"{_safe_text(labels.get(level, level))}</button>"
    )


def _render_metrics(block: ReportBlock) -> str:
    items = []
    for metric in block.metrics:
        value = _safe_text(metric.value)
        unit = f" <span>{_safe_text(metric.unit)}</span>" if metric.unit else ""
        note = f"<small>{_safe_text(metric.note)}</small>" if metric.note else ""
        items.append(
            f"""<div class="metric">
  <span>{_safe_text(metric.label)}</span>
  <strong>{value}{unit}</strong>
  {note}
</div>"""
        )
    return f'<div class="metric-grid">{"".join(items)}</div>'


def _render_figures(figures: Iterable[ReportFigure], *, web_dir: Path) -> str:
    cards = []
    for figure in figures:
        if not figure.available or figure.path is None:
            if not figure.required:
                continue
            cards.append(_render_missing_figure(figure))
        else:
            href = _link_relative(web_dir, figure.path)
            src = _figure_src(figure, web_dir=web_dir)
            caption = _figure_caption(figure)
            cards.append(
                f"""<figure>
  <a href="{_safe(href)}"><img src="{_safe(src)}" alt="{_safe(figure.title)}"></a>
  {caption}
</figure>"""
            )
    return f'<div class="figure-grid">{"".join(cards)}</div>' if cards else ""


def _render_missing_figure(figure: ReportFigure) -> str:
    caption = _figure_caption(figure)
    path_hint = ""
    if figure.path is not None:
        path_hint = f"<small>{_safe(figure.path)}</small>"
    return f"""<figure class="missing-figure">
  <div class="figure-placeholder">Figure requise manquante</div>
  {caption}
  {path_hint}
</figure>"""


def _figure_caption(figure: ReportFigure) -> str:
    if not figure.title and not figure.caption:
        return ""
    title = f"<strong>{_safe_text(figure.title)}</strong>" if figure.title else ""
    caption = f"<br><span>{_safe_text(figure.caption)}</span>" if figure.caption else ""
    return f"<figcaption>{title}{caption}</figcaption>"


def _figure_src(figure: ReportFigure, *, web_dir: Path) -> str:
    if figure.embed and figure.path is not None and figure.path.is_file():
        data_uri = _image_data_uri(figure.path)
        if data_uri:
            return data_uri
    if figure.path is None:
        return ""
    return _link_relative(web_dir, figure.path)


def _image_data_uri(path: Path, *, max_inline_bytes: int = 5_000_000) -> str:
    if path.suffix.lower() != ".png":
        return ""
    try:
        if path.stat().st_size > max_inline_bytes:
            return ""
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:image/png;base64,{encoded}"


def _render_toc(blocks: tuple[ReportBlock, ...]) -> str:
    items = [
        f'<a href="#{_safe(_anchor_id(block.block_id))}">{_safe_text(block.title)}</a>'
        for block in blocks
        if block.title
    ]
    if len(items) < 2:
        return ""
    return f"""<nav class="block-toc" aria-label="Sommaire du rapport">
  <span>Sommaire</span>
  <div>{"".join(items)}</div>
</nav>"""


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
        "by_block": "Par bloc",
    }
    buttons = []
    ordered_levels = ("compact", "standard", "audit", "by_block")
    extras = tuple(level for level in level_links if level not in ordered_levels)
    for level in ordered_levels + extras:
        path = level_links.get(level)
        if path is None:
            continue
        classes = "level-button is-active" if level == current_level else "level-button"
        aria_current = ' aria-current="page"' if level == current_level else ""
        buttons.append(
            f'<a class="{classes}" href="{_safe(_link_relative(web_dir, path))}"'
            f"{aria_current}>{_safe_text(labels.get(level, level))}</a>"
        )
    if not buttons:
        return ""
    return f"""<nav class="level-nav" id="report-level" aria-label="Niveau du rapport">
  <span>Niveau</span>
  <div class="level-buttons">{"".join(buttons)}</div>
</nav>"""


def _render_status(status: str) -> str:
    labels = {
        "available": "",
        "partial": "Partiel",
        "empty": "Vide",
        "not_applicable": "Non applicable",
    }
    label = labels.get(status, status.replace("_", " "))
    if not label:
        return ""
    return f'<span class="status-pill">{_safe_text(label)}</span>'


def _render_table(table: ReportTable) -> str:
    if not table.rows:
        body = f'<p class="muted">{_safe(table.empty_message)}</p>'
    else:
        header = "".join(f"<th>{_safe_text(label)}</th>" for _, label in table.columns)
        rows = []
        for row in table.rows:
            cells = "".join(
                f"<td>{_safe_text(_short(row.get(key, '')))}</td>" for key, _ in table.columns
            )
            rows.append(f"<tr>{cells}</tr>")
        body = f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    return f"""<div class="table-block">
  <h3>{_safe_text(table.title)}</h3>
  {body}
</div>"""


def _render_links(links: Iterable[ReportLink], *, web_dir: Path) -> str:
    items = []
    for link in links:
        href = _link_href(web_dir, link.path)
        kind = f"<span>{_safe_text(link.kind)}</span>" if link.kind else ""
        note = f"<small>{_safe_text(link.note)}</small>" if link.note else ""
        items.append(
            f"""<li>
  {kind}
  <a href="{_safe(href)}">{_safe_text(link.label)}</a>
  {note}
</li>"""
        )
    if not items:
        return ""
    return f'<ul class="artifact-links">{"".join(items)}</ul>'


def _render_warnings(warnings: Iterable[str]) -> str:
    items = [f"<li>{_safe_text(item)}</li>" for item in warnings if str(item).strip()]
    if not items:
        return ""
    return f'<ul class="warning-list">{"".join(items)}</ul>'


def _safe(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _safe_text(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def _anchor_id(value: str) -> str:
    text = str(value).strip().lower().replace("_", "-")
    out = []
    last_dash = False
    for char in text:
        keep = char.isascii() and char.isalnum()
        if keep:
            out.append(char)
            last_dash = False
        elif not last_dash:
            out.append("-")
            last_dash = True
    anchor = "".join(out).strip("-")
    return anchor or "block"


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


def _link_href(web_dir: Path, path: Path | str) -> str:
    text = str(path)
    if "://" in text or text.startswith("#"):
        return text
    return _link_relative(web_dir, Path(path))


def _without_trailing_whitespace(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


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
    .block-variant-group {
      margin-top: 20px;
    }
    .block-level-switch {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }
    .block-level-switch span {
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .block-level-buttons {
      display: inline-flex;
      gap: 4px;
    }
    .block-level-button {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 10px;
      background: #fff;
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      font-size: 0.9rem;
      font-weight: 700;
    }
    .block-level-button:hover {
      border-color: var(--accent);
    }
    .block-level-button.is-active {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    .block-variant .report-block {
      margin-top: 0;
    }
    .block-toc {
      display: grid;
      gap: 8px;
      margin-top: 14px;
      padding: 10px 0 0;
    }
    .block-toc span {
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .block-toc div {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .block-toc a {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 9px;
      background: var(--panel);
      color: var(--ink);
      font-size: 0.88rem;
      font-weight: 650;
    }
    .block-toc a:hover {
      border-color: var(--accent);
      text-decoration: none;
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
    .block-pills {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      justify-content: flex-end;
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
    .status-pill {
      border: 1px solid var(--warn);
      border-radius: 999px;
      padding: 5px 10px;
      color: var(--warn);
      background: #fff7ed;
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
    .artifact-links {
      display: grid;
      gap: 8px;
      margin: 14px 0 0;
      padding-left: 20px;
    }
    .artifact-links li {
      padding-left: 2px;
    }
    .artifact-links span {
      display: inline-block;
      min-width: 92px;
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .artifact-links small {
      display: block;
      margin-top: 2px;
      color: var(--muted);
    }
    @media (max-width: 880px) {
      main { padding: 18px 12px 42px; }
      .metric-grid, .figure-grid { grid-template-columns: 1fr; }
      .block-title-row { display: block; }
      .block-level-switch { display: grid; }
      .level-pill { display: inline-block; margin-top: 10px; }
    }"""


_BLOCK_LEVEL_SCRIPT = """<script>
(function () {
  var storagePrefix = "hydromodpy:block-level:";
  function selectLevel(group, level) {
    var hasLevel = false;
    group.querySelectorAll(".block-variant").forEach(function (variant) {
      var active = variant.getAttribute("data-block-level") === level;
      if (active) {
        hasLevel = true;
      }
      variant.hidden = !active;
    });
    if (!hasLevel) {
      return;
    }
    group.querySelectorAll(".block-level-button").forEach(function (button) {
      var active = button.getAttribute("data-target-level") === level;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    try {
      window.localStorage.setItem(storagePrefix + group.id, level);
    } catch (error) {}
  }
  document.querySelectorAll("[data-block-group]").forEach(function (group) {
    var defaultLevel = group.getAttribute("data-default-level") || "standard";
    var saved = null;
    try {
      saved = window.localStorage.getItem(storagePrefix + group.id);
    } catch (error) {}
    selectLevel(group, saved || defaultLevel);
    group.querySelectorAll(".block-level-button").forEach(function (button) {
      button.addEventListener("click", function () {
        selectLevel(group, button.getAttribute("data-target-level"));
      });
    });
  });
})();
</script>"""
