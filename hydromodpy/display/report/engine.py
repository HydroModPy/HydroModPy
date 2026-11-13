"""One report engine: blocks in, static HTML pages and ``report.json`` out.

A block holds items. Each item carries the first detail level that shows it, so
one declaration gives the compact, standard and audit pages and the page with a
level switch per block. The engine knows no run, no session and no phrase: the
caller gives it blocks and the text it shows.
"""

from __future__ import annotations

import html
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

Level = Literal["compact", "standard", "audit"]
LEVELS: tuple[Level, ...] = ("compact", "standard", "audit")
REPORT_SCHEMA = "hydromodpy.report.v1"
_RANK = {name: rank for rank, name in enumerate(LEVELS)}
_TITLE = {"compact": "Compact", "standard": "Standard", "audit": "Audit", "by_block": "By block"}
_CELL_LIMIT = 120
WORDS: dict[str, str] = {
    "eyebrow": "HydroModPy report",
    "contents": "Contents",
    "figure_missing": "Required figure missing",
}
"""The words of the page frame, in English; a caller gives them in another language."""


@dataclass(frozen=True, slots=True)
class Metric:
    """One labelled value, with an optional unit."""

    label: str
    value: Any
    unit: str = ""


@dataclass(frozen=True, slots=True)
class Picture:
    """One figure. ``path`` is ``None`` or a missing file when it was not drawn."""

    id: str
    title: str
    path: Path | None
    caption: str = ""
    required: bool = False

    @property
    def ok(self) -> bool:
        """Return whether the file exists."""
        return self.path is not None and Path(self.path).is_file()


@dataclass(frozen=True, slots=True)
class Table:
    """A table of rows. ``columns`` pairs a row key with its heading."""

    id: str
    title: str
    columns: tuple[tuple[str, str], ...]
    rows: tuple[Mapping[str, Any], ...]
    empty: str = "No rows."


@dataclass(frozen=True, slots=True)
class Link:
    """A link to a file of the run, relative to the page, or to a URL."""

    label: str
    path: Path | str
    kind: str = ""


@dataclass(frozen=True, slots=True)
class Prose:
    """Paragraphs of plain text."""

    paragraphs: tuple[str, ...]


Item = Metric | Picture | Table | Link | Prose | str
"""A ``str`` item is a warning line."""


@dataclass(frozen=True, slots=True)
class Block:
    """A titled group of items, each with the first level that shows it."""

    id: str
    title: str
    lead: str = ""
    min_level: Level = "compact"
    items: tuple[tuple[Level, Item], ...] = ()


def pairs_table(id: str, title: str, pairs: Sequence[tuple[Any, Any]]) -> Table:
    """Return a two-column table of ``(item, value)`` rows."""
    rows = tuple({"k": key, "v": value} for key, value in pairs)
    return Table(id, title, (("k", "Item"), ("v", "Value")), rows)


def items_at(block: Block, level: Level) -> list[Item] | None:
    """Return the items a block shows at ``level``, or ``None`` when it starts higher."""
    if _RANK[level] < _RANK[block.min_level]:
        return None
    return [item for first, item in block.items if _RANK[level] >= _RANK[first]]


def write_pages(
    out: Path,
    *,
    title: str,
    subtitle: str,
    blocks: Sequence[Block],
    levels: bool = True,
    lang: str = "en",
    label: str = "",
    rendered: date,
    preset: str = "",
    words: Mapping[str, str] | None = None,
    reasons: Mapping[str, str] | None = None,
) -> Path:
    """Write the pages of a report under ``out`` and return its ``index.html``.

    ``levels=True`` writes ``index.html`` (standard level) and
    ``review/{compact,standard,audit,by_block}/index.html``. ``levels=False``
    writes ``index.html`` alone. The figures are copied under ``figures/`` and
    ``report.json`` lists each figure with its file, or ``null`` when it is
    missing. ``missing`` maps each required figure that is missing, and each figure named in
    ``reasons``, to its reason, else to a plain statement. ``words`` replaces the
    words of the page frame (:data:`WORDS`). The engine removes only the figures
    it copied on a former call, never a file someone else put in ``figures/``.
    """
    out = Path(out)
    pictures = [item for block in blocks for _, item in block.items if isinstance(item, Picture)]
    copied = _copy_pictures(out / "figures", pictures, _written_before(out))
    head = _Head(title, subtitle, lang, label, rendered, {**WORDS, **(words or {})})
    index = out / "index.html"
    pages: dict[str, Path] = {}
    if levels:
        pages = {name: out / "review" / name / "index.html" for name in (*LEVELS, "by_block")}
        for name, path in pages.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            text = _page(
                head,
                blocks,
                "standard" if name == "by_block" else name,
                path.parent,
                pages,
                copied,
                name,
            )
            path.write_text(text, encoding="utf-8")
    out.mkdir(parents=True, exist_ok=True)
    index.write_text(
        _page(head, blocks, "standard", out, pages, copied, "standard"), encoding="utf-8"
    )
    _write_report_json(out, pictures, copied, head, preset, reasons or {})
    return index


@dataclass(frozen=True, slots=True)
class _Head:
    title: str
    subtitle: str
    lang: str
    label: str
    rendered: date
    words: Mapping[str, str]


def _written_before(out: Path) -> list[Path]:
    """Return the figures a former call copied, as its ``report.json`` lists them."""
    try:
        payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # No former report, or one that does not read: nothing of ours to remove.
        return []
    names = payload.get("copied", []) if isinstance(payload, dict) else []
    return [out / "figures" / Path(str(name)).name for name in names]


def _copy_pictures(
    figdir: Path, pictures: Sequence[Picture], former: Sequence[Path] = ()
) -> dict[str, Path]:
    """Copy each existing figure under ``figdir``; a name taken by another file gets a prefix.

    A figure already in ``figdir`` stays where it is. The copies of a former call
    (``former``) are removed first, and no other file of ``figdir`` is touched.
    """
    for path in former:
        path.unlink(missing_ok=True)
    figdir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, Path] = {}
    for picture in pictures:
        if not picture.ok or str(picture.path) in copied:
            continue
        source = Path(picture.path)
        if source.resolve().parent == figdir.resolve():
            copied[str(source)] = source
            continue
        target = figdir / source.name
        number = 1
        while target.exists():
            target = figdir / f"{source.parent.parent.name}_{number}_{source.name}"
            number += 1
        shutil.copy2(source, target)
        copied[str(source)] = target
    return copied


def _write_report_json(
    out: Path,
    pictures: Sequence[Picture],
    copied: Mapping[str, Path],
    head: _Head,
    preset: str,
    reasons: Mapping[str, str],
) -> None:
    written = sorted({t.name for s, t in copied.items() if Path(s).resolve() != t.resolve()})
    figures = {
        p.id: {
            "title": p.title,
            "file": copied[str(p.path)].name if p.ok else None,
            "required": p.required,
        }
        for p in pictures
    }
    payload = {
        "schema": REPORT_SCHEMA,
        "preset": preset,
        "lang": head.lang,
        "label": head.label,
        "rendered": head.rendered.isoformat(),
        "figures": figures,
        "missing": {
            p.id: reasons.get(p.id, "the figure was not drawn")
            for p in sorted(pictures, key=lambda p: p.id)
            if not p.ok and (p.required or p.id in reasons)
        },
        "copied": written,
    }
    (out / "report.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _anchor(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "block"


def _rel(target: Path | str, here: Path) -> str:
    if "://" in str(target):
        return str(target)
    return os.path.relpath(target, here).replace("\\", "/")


def _metrics_html(metrics: Sequence[Metric]) -> str:
    cells = "".join(
        f'<div class="metric"><span>{_esc(m.label)}</span><strong>{_esc(m.value)}'
        f"{f' <span>{_esc(m.unit)}</span>' if m.unit else ''}</strong></div>"
        for m in metrics
    )
    return f'<div class="metric-grid">{cells}</div>'


def _pictures_html(
    pictures: Sequence[Picture], here: Path, copied: Mapping[str, Path], missing: str
) -> str:
    cards = []
    for p in pictures:
        if p.ok:
            href = _esc(_rel(copied[str(p.path)], here))
            caption = f"<strong>{_esc(p.title)}</strong>"
            caption += f"<br><span>{_esc(p.caption)}</span>" if p.caption else ""
            cards.append(
                f'<figure><a href="{href}"><img src="{href}" alt="{_esc(p.title)}"></a>'
                f"<figcaption>{caption}</figcaption></figure>"
            )
        elif p.required:
            cards.append(
                f'<figure class="missing"><div class="ph">{_esc(missing)}</div>'
                f"<figcaption><strong>{_esc(p.title)}</strong></figcaption></figure>"
            )
    return f'<div class="figure-grid">{"".join(cards)}</div>' if cards else ""


def _table_html(table: Table) -> str:
    if table.rows:
        head = "".join(f"<th>{_esc(heading)}</th>" for _, heading in table.columns)
        body = "".join(
            "<tr>"
            + "".join(
                f"<td>{_esc(str(row.get(key, ''))[:_CELL_LIMIT])}</td>" for key, _ in table.columns
            )
            + "</tr>"
            for row in table.rows
        )
        inner = f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    else:
        inner = f'<p class="muted">{_esc(table.empty)}</p>'
    heading = f"<h3>{_esc(table.title)}</h3>" if table.title else ""
    return f'<div class="table-block">{heading}{inner}</div>'


def _items_html(
    items: Sequence[Item],
    here: Path,
    copied: Mapping[str, Path],
    missing: str = WORDS["figure_missing"],
) -> str:
    out = []
    for kind, render in (
        (Prose, lambda xs: "".join(f"<p>{_esc(t)}</p>" for x in xs for t in x.paragraphs)),
        (Metric, _metrics_html),
        (Picture, lambda xs: _pictures_html(xs, here, copied, missing)),
        (Table, lambda xs: "".join(_table_html(t) for t in xs)),
        (
            Link,
            lambda xs: (
                '<ul class="links">'
                + "".join(
                    f'<li><span>{_esc(x.kind)}</span><a href="{_esc(_rel(x.path, here))}">{_esc(x.label)}</a></li>'
                    for x in xs
                )
                + "</ul>"
            ),
        ),
        (
            str,
            lambda xs: '<ul class="warn">' + "".join(f"<li>{_esc(w)}</li>" for w in xs) + "</ul>",
        ),
    ):
        group = [item for item in items if isinstance(item, kind)]
        if group:
            out.append(render(group))
    return "\n".join(part for part in out if part)


def _block_html(
    block: Block,
    level: Level,
    here: Path,
    copied: Mapping[str, Path],
    anchor: str = "",
    *,
    words: Mapping[str, str] = WORDS,
    pill: bool = True,
) -> str:
    items = items_at(block, level)
    if items is None:
        body = f"<p>Block available from the {_esc(block.min_level)} level.</p>"
        status = '<span class="pill">Empty</span>'
    else:
        lead = f"<p>{_esc(block.lead)}</p>" if block.lead else ""
        body = lead + _items_html(items, here, copied, words["figure_missing"])
        status = ""
    level_pill = f'<span class="pill">{level}</span>' if pill else ""
    return (
        f'<section class="block" id="{anchor or _anchor(block.id)}"><div class="title-row">'
        f"<h2>{_esc(block.title)}</h2><div>{status}{level_pill}</div></div>{body}</section>"
    )


def _nav(here: Path, current: str, pages: Mapping[str, Path]) -> str:
    if not pages:
        return ""
    links = "".join(
        f'<a class="btn{" on" if name == current else ""}" href="{_esc(_rel(path, here))}">{_TITLE[name]}</a>'
        for name, path in pages.items()
    )
    return f'<nav class="levels"><span>Level</span>{links}</nav>'


def _body(
    blocks: Sequence[Block],
    level: Level,
    here: Path,
    copied: Mapping[str, Path],
    by_block: bool,
    words: Mapping[str, str] = WORDS,
    pill: bool = True,
) -> str:
    if not by_block:
        return "".join(
            _block_html(b, level, here, copied, words=words, pill=pill)
            for b in blocks
            if items_at(b, level) is not None
        )
    groups = []
    for b in blocks:
        tabs = "".join(
            f'<button type="button" data-level="{lv}"{" class=on" if lv == "standard" else ""}>{_TITLE[lv]}</button>'
            for lv in LEVELS
        )
        views = "".join(
            f'<div class="variant" data-level="{lv}"{"" if lv == "standard" else " hidden"}>'
            f"{_block_html(b, lv, here, copied, f'{_anchor(b.id)}-{lv}', words=words)}</div>"
            for lv in LEVELS
        )
        groups.append(
            f'<div class="group" id="{_anchor(b.id)}"><div class="switch"><span>Block level</span>'
            f"{tabs}</div>{views}</div>"
        )
    return "".join(groups)


def _page(
    head: _Head,
    blocks: Sequence[Block],
    level: Level,
    here: Path,
    pages: Mapping[str, Path],
    copied: Mapping[str, Path],
    current: str,
) -> str:
    by_block = current == "by_block"
    shown = [b for b in blocks if by_block or items_at(b, level) is not None]
    toc = "".join(f'<a href="#{_anchor(b.id)}">{_esc(b.title)}</a>' for b in shown)
    subtitle = head.subtitle if not pages else f"{head.subtitle} ({_TITLE[current].lower()} view)"
    stamp = " · ".join(part for part in (head.label, head.rendered.isoformat()) if part)
    return (
        f'<!doctype html><html lang="{_esc(head.lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(head.title)}</title><style>{_STYLE}</style></head><body><main><header>"
        f'<p class="eyebrow">{_esc(head.words["eyebrow"])} · {_esc(stamp)}</p><h1>{_esc(head.title)}</h1>'
        f'<p class="muted">{_esc(subtitle)}</p>{_nav(here, current, pages)}'
        f'<nav class="toc"><span>{_esc(head.words["contents"])}</span>{toc}</nav></header>'
        f"{_body(blocks, level, here, copied, by_block, head.words, bool(pages))}</main>{_SCRIPT if by_block else ''}</body></html>\n"
    )


_STYLE = """
:root{--bg:#f6f8fa;--card:#fff;--ink:#17202a;--muted:#5f6b7a;--line:#d8dee6;--accent:#0b6e99}
@media (prefers-color-scheme:dark){:root{--bg:#10151b;--card:#18202a;--ink:#e6ebf0;--muted:#9aa7b5;--line:#2c3744;--accent:#6cb6e0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:1500px;margin:0 auto;padding:30px 20px 58px}
header{padding-bottom:18px;border-bottom:1px solid var(--line)}
h1{margin:0 0 8px;font-size:2.1rem}
h2{margin:0;font-size:1.35rem}
h3{margin:0 0 10px;font-size:1rem}
a{color:var(--accent);text-decoration:none}
.eyebrow{margin:0 0 6px;color:var(--muted);text-transform:uppercase;font-size:.78rem;letter-spacing:.06em}
.muted{color:var(--muted)}
.levels,.toc,.switch{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}
.levels span,.toc span,.switch span{color:var(--muted);font-weight:600}
.btn,.toc a,.switch button{border:1px solid var(--line);border-radius:6px;padding:4px 10px;background:var(--card);color:var(--ink);font:inherit;cursor:pointer}
.btn.on,.switch button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.block{margin-top:20px;padding:18px;border:1px solid var(--line);border-radius:8px;background:var(--card)}
.title-row{display:flex;justify-content:space-between;gap:12px;margin-bottom:12px}
.pill{border:1px solid var(--line);border-radius:99px;padding:2px 9px;font-size:.78rem;color:var(--muted);margin-left:6px}
.metric-grid,.figure-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin:12px 0}
.figure-grid{grid-template-columns:repeat(auto-fit,minmax(420px,1fr))}
.metric{padding:10px;border:1px solid var(--line);border-radius:6px}
.metric>span{display:block;color:var(--muted);font-size:.85rem}
.metric strong{overflow-wrap:anywhere}
figure{margin:0;padding:10px;border:1px solid var(--line);border-radius:8px}
figure img{display:block;width:100%;border-radius:6px}
figcaption{margin-top:8px;color:var(--muted)}
.ph{padding:40px;text-align:center;border:1px dashed var(--line)}
.table-block{margin-top:14px}
table{width:100%;border-collapse:collapse;border:1px solid var(--line)}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:var(--bg)}
.links{list-style:none;padding:0}
.links li{padding:5px 0;border-bottom:1px solid var(--line)}
.links span{display:inline-block;min-width:60px;color:var(--muted)}
.warn{color:#9a5b00}
@media (max-width:880px){main{padding:18px 12px}.metric-grid,.figure-grid{grid-template-columns:1fr}}
"""

_SCRIPT = """<script>
document.querySelectorAll(".group").forEach(function(g){
  function pick(lv){g.querySelectorAll(".variant").forEach(function(v){v.hidden=v.dataset.level!==lv});
    g.querySelectorAll(".switch button").forEach(function(b){b.classList.toggle("on",b.dataset.level===lv)});
    try{localStorage.setItem("hmp:block-level:"+g.id,lv)}catch(e){}}
  var saved=null;try{saved=localStorage.getItem("hmp:block-level:"+g.id)}catch(e){}
  if(saved)pick(saved);
  g.querySelectorAll(".switch button").forEach(function(b){b.addEventListener("click",function(){pick(b.dataset.level)})});
});
</script>"""
