"""Render one Markdown report to a standalone HTML document.

The generated HTML is intended for local consultation in a browser:

- embedded CSS only, no external assets,
- sticky table of contents,
- responsive tables,
- print-friendly layout.
"""

from __future__ import annotations

import argparse
import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import mistune


HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
HTML_HEADING_PATTERN = re.compile(r"<h([1-6])>(.*?)</h\1>", re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class Heading:
    level: int
    text: str
    anchor: str


def _strip_markdown_markup(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"_([^_]+)_", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    return cleaned.strip()


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "section"


def extract_headings(markdown_text: str) -> list[Heading]:
    headings: list[Heading] = []
    used: dict[str, int] = {}
    in_fence = False
    for raw_line in markdown_text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_PATTERN.match(raw_line)
        if not match:
            continue
        level = len(match.group(1))
        text = _strip_markdown_markup(match.group(2))
        base_anchor = _slugify(text)
        count = used.get(base_anchor, 0)
        used[base_anchor] = count + 1
        anchor = base_anchor if count == 0 else f"{base_anchor}-{count + 1}"
        headings.append(Heading(level=level, text=text, anchor=anchor))
    return headings


def _inject_heading_ids(content_html: str, headings: list[Heading]) -> str:
    heading_iter = iter(headings)

    def _replace(match: re.Match[str]) -> str:
        try:
            heading = next(heading_iter)
        except StopIteration:
            return match.group(0)
        level = match.group(1)
        inner_html = match.group(2)
        return f'<h{level} id="{html.escape(heading.anchor, quote=True)}">{inner_html}</h{level}>'

    return HTML_HEADING_PATTERN.sub(_replace, content_html)


def _wrap_tables(content_html: str) -> str:
    return re.sub(
        r"(<table>.*?</table>)",
        r'<div class="table-wrap">\1</div>',
        content_html,
        flags=re.DOTALL,
    )


def _build_toc(headings: list[Heading]) -> str:
    items: list[str] = []
    for heading in headings:
        if heading.level == 1:
            continue
        item_class = f"toc-item toc-h{heading.level}"
        items.append(
            f'<a class="{item_class}" href="#{html.escape(heading.anchor, quote=True)}">{html.escape(heading.text)}</a>'
        )
    return "\n".join(items)


def _render_template(
    *,
    title: str,
    source_path: Path,
    headings: list[Heading],
    content_html: str,
) -> str:
    page_title = html.escape(title)
    source_text = html.escape(str(source_path))
    generated_at = html.escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    toc_html = _build_toc(headings)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <style>
    :root {{
      --page-bg: #efe8dc;
      --paper: #fbf8f2;
      --ink: #1f2a35;
      --muted: #5a6874;
      --line: #d9cfbf;
      --accent: #1d6f6b;
      --accent-soft: #dcefea;
      --accent-strong: #114b48;
      --warm: #9a6a18;
      --shadow: 0 18px 42px rgba(40, 34, 22, 0.12);
      --radius: 18px;
      --code-bg: #f0ece4;
    }}

    * {{
      box-sizing: border-box;
    }}

    html {{
      scroll-behavior: smooth;
    }}

    body {{
      margin: 0;
      font-family: "Segoe UI Variable", "Segoe UI", "Aptos", system-ui, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(29, 111, 107, 0.12), transparent 24rem),
        radial-gradient(circle at top right, rgba(154, 106, 24, 0.10), transparent 20rem),
        linear-gradient(180deg, #f4eee3 0%, var(--page-bg) 100%);
    }}

    a {{
      color: var(--accent-strong);
    }}

    .layout {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 28px 24px 48px;
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      gap: 28px;
      align-items: start;
    }}

    .sidebar {{
      position: sticky;
      top: 18px;
      background: rgba(251, 248, 242, 0.82);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(217, 207, 191, 0.85);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 22px 20px;
    }}

    .eyebrow {{
      display: inline-block;
      margin-bottom: 12px;
      padding: 6px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent-strong);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}

    .sidebar h1 {{
      margin: 0 0 10px;
      font-family: "Palatino Linotype", "Book Antiqua", Georgia, serif;
      font-size: 28px;
      line-height: 1.12;
      color: #14222f;
    }}

    .meta {{
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }}

    .toc-title {{
      margin: 20px 0 10px;
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: var(--warm);
    }}

    .toc {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}

    .toc-item {{
      display: block;
      text-decoration: none;
      color: var(--ink);
      border-radius: 10px;
      padding: 8px 10px;
      transition: background-color 120ms ease, color 120ms ease, transform 120ms ease;
      font-size: 14px;
      line-height: 1.35;
    }}

    .toc-item:hover {{
      background: var(--accent-soft);
      color: var(--accent-strong);
      transform: translateX(2px);
    }}

    .toc-h2 {{
      font-weight: 700;
    }}

    .toc-h3 {{
      padding-left: 22px;
      color: #33404b;
      font-size: 13px;
    }}

    .toc-h4, .toc-h5, .toc-h6 {{
      padding-left: 34px;
      color: #53606b;
      font-size: 12px;
    }}

    .content {{
      background: var(--paper);
      border: 1px solid rgba(217, 207, 191, 0.88);
      border-radius: 26px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}

    .content-header {{
      padding: 26px 34px 16px;
      border-bottom: 1px solid rgba(217, 207, 191, 0.8);
      background:
        linear-gradient(180deg, rgba(29, 111, 107, 0.06), rgba(29, 111, 107, 0.00)),
        linear-gradient(90deg, rgba(255, 255, 255, 0.70), rgba(255, 255, 255, 0.10));
    }}

    .content-header h2 {{
      margin: 0 0 8px;
      font-family: "Palatino Linotype", "Book Antiqua", Georgia, serif;
      font-size: 32px;
      line-height: 1.1;
      color: #172532;
    }}

    .content-header p {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }}

    article {{
      padding: 8px 34px 38px;
      font-size: 15px;
      line-height: 1.72;
    }}

    article h1 {{
      display: none;
    }}

    article h2 {{
      margin-top: 34px;
      margin-bottom: 10px;
      padding-top: 8px;
      font-family: "Palatino Linotype", "Book Antiqua", Georgia, serif;
      font-size: 28px;
      line-height: 1.2;
      color: #173242;
      border-top: 1px solid rgba(217, 207, 191, 0.85);
    }}

    article h3 {{
      margin-top: 28px;
      margin-bottom: 8px;
      font-size: 20px;
      line-height: 1.25;
      color: #1d4956;
    }}

    article h4,
    article h5,
    article h6 {{
      margin-top: 22px;
      margin-bottom: 8px;
      font-size: 16px;
      line-height: 1.3;
      color: #234d4a;
    }}

    article p,
    article ul,
    article ol,
    article blockquote {{
      margin-top: 10px;
      margin-bottom: 10px;
    }}

    article ul,
    article ol {{
      padding-left: 24px;
    }}

    article li {{
      margin: 4px 0;
    }}

    article code {{
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 0.92em;
      background: var(--code-bg);
      padding: 0.14rem 0.34rem;
      border-radius: 6px;
      color: #153349;
    }}

    article pre {{
      margin: 14px 0;
      padding: 16px 18px;
      background: #1e2833;
      color: #eef3f7;
      border-radius: 14px;
      overflow-x: auto;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
    }}

    article pre code {{
      background: transparent;
      color: inherit;
      padding: 0;
    }}

    article blockquote {{
      padding: 12px 16px;
      border-left: 4px solid var(--accent);
      background: rgba(29, 111, 107, 0.07);
      border-radius: 0 12px 12px 0;
      color: #274350;
    }}

    article img {{
      display: block;
      width: min(100%, 1100px);
      margin: 18px auto 10px;
      border: 1px solid rgba(217, 207, 191, 0.92);
      border-radius: 20px;
      background: #fffdf9;
      box-shadow: 0 12px 26px rgba(40, 34, 22, 0.08);
    }}

    article figure {{
      margin: 18px 0 22px;
    }}

    .figure-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      margin: 18px 0 24px;
    }}

    .figure-card {{
      margin: 0;
      padding: 16px;
      border: 1px solid rgba(217, 207, 191, 0.92);
      border-radius: 20px;
      background:
        linear-gradient(180deg, rgba(29, 111, 107, 0.04), rgba(29, 111, 107, 0)),
        #fffdf9;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.36);
    }}

    .figure-card-wide {{
      grid-column: 1 / -1;
    }}

    .figure-card svg {{
      display: block;
      width: 100%;
      height: auto;
      border-radius: 14px;
      background: #fffdf9;
    }}

    .figure-card figcaption {{
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }}

    .report-note {{
      margin: 18px 0;
      padding: 16px 18px;
      border: 1px solid rgba(29, 111, 107, 0.18);
      border-radius: 16px;
      background: linear-gradient(90deg, rgba(29, 111, 107, 0.09), rgba(29, 111, 107, 0.03));
    }}

    .report-note p {{
      margin: 0;
    }}

    .table-wrap {{
      margin: 18px 0;
      border: 1px solid rgba(217, 207, 191, 0.92);
      border-radius: 16px;
      overflow-x: auto;
      background: #fffdf9;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 720px;
    }}

    th,
    td {{
      padding: 12px 14px;
      border-bottom: 1px solid rgba(217, 207, 191, 0.75);
      vertical-align: top;
      text-align: left;
    }}

    thead th {{
      position: sticky;
      top: 0;
      background: #efe9dc;
      color: #20303f;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}

    tbody tr:nth-child(even) {{
      background: rgba(239, 233, 220, 0.36);
    }}

    tbody tr:hover {{
      background: rgba(29, 111, 107, 0.08);
    }}

    hr {{
      border: 0;
      border-top: 1px solid rgba(217, 207, 191, 0.92);
      margin: 28px 0;
    }}

    @media (max-width: 1180px) {{
      .layout {{
        grid-template-columns: 1fr;
      }}

      .sidebar {{
        position: static;
      }}

      .toc {{
        max-height: 320px;
        overflow: auto;
      }}
    }}

    @media (max-width: 720px) {{
      .layout {{
        padding: 16px 14px 28px;
        gap: 16px;
      }}

      .content-header,
      article {{
        padding-left: 18px;
        padding-right: 18px;
      }}

      .content-header h2 {{
        font-size: 26px;
      }}

      article h2 {{
        font-size: 24px;
      }}
    }}

    @media (max-width: 900px) {{
      .figure-grid {{
        grid-template-columns: 1fr;
      }}

      .figure-card-wide {{
        grid-column: auto;
      }}
    }}

    @media print {{
      body {{
        background: #ffffff;
      }}

      .layout {{
        max-width: none;
        padding: 0;
        display: block;
      }}

      .sidebar {{
        display: none;
      }}

      .content {{
        border: 0;
        box-shadow: none;
      }}

      .content-header {{
        padding-top: 0;
      }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <div class="eyebrow">Rapport HTML</div>
      <h1>{page_title}</h1>
      <p class="meta">
        Source : <code>{source_text}</code><br>
        Genere le : <code>{generated_at}</code>
      </p>
      <div class="toc-title">Sommaire</div>
      <nav class="toc">
        {toc_html}
      </nav>
    </aside>
    <main class="content">
      <header class="content-header">
        <h2>{page_title}</h2>
        <p>Version HTML autonome pour consultation locale, avec sommaire lateral, tableaux lisibles, figures explicatives et mise en page adaptee au navigateur.</p>
      </header>
      <article>
        {content_html}
      </article>
    </main>
  </div>
</body>
</html>
"""


def render_markdown_to_html(
    markdown_path: Path, output_path: Path, *, title: str | None = None
) -> None:
    markdown_text = markdown_path.read_text(encoding="utf-8")
    headings = extract_headings(markdown_text)
    renderer = mistune.create_markdown(plugins=["table", "strikethrough"])
    content_html = renderer(markdown_text)
    content_html = _inject_heading_ids(content_html, headings)
    content_html = _wrap_tables(content_html)
    page_title = title or (headings[0].text if headings else markdown_path.stem)
    html_text = _render_template(
        title=page_title,
        source_path=markdown_path,
        headings=headings,
        content_html=content_html,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8", newline="\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render one Markdown report to standalone HTML.")
    parser.add_argument("markdown_path", type=Path, help="Input Markdown file.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output HTML path. Defaults to the input path with a .html suffix.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional HTML page title override.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    markdown_path = Path(args.markdown_path).expanduser().resolve()
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output is not None
        else markdown_path.with_suffix(".html")
    )
    render_markdown_to_html(markdown_path, output_path, title=args.title)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
