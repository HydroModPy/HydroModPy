"""Catalog pages of the reference: solvers, figures and data sources.

The catalogs come from ``_data/catalogs.json``, written by ``tools/docs/catalogs.py``
from the registries of the code. A wrong row is fixed in the code: the solver
registry, the figure class and its ``FigureSpec``, or ``hydromodpy.schema.sources``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import hmp_params as H
from docutils.parsers.rst import directives
from sphinx.util.docutils import SphinxDirective

DATA: dict = {}
SRCDIR: list[Path] = []

# Where another job renders one preview image per figure, named after the figure.
THUMB_DIR = "_static/figures/catalog"
THUMB_SUFFIXES = (".webp", ".png")
REPO_ROOT = Path(__file__).resolve().parents[3]


def figure_subjects() -> dict[str, str]:
    """Return the subject of each figure that does not draw a run, from the figure table."""
    from hydromodpy.display.figure_table import SUBJECTS

    return dict(SUBJECTS)


def load(srcdir: Path) -> None:
    DATA.clear()
    SRCDIR[:] = [srcdir]
    path = srcdir / "_data" / "catalogs.json"
    if path.exists():
        DATA.update(json.loads(path.read_text()))


def esc(text) -> str:
    return H.esc(text)


def code_list(items: list[str]) -> str:
    return (
        ", ".join(f"<code>{esc(i)}</code>" for i in items)
        if items
        else '<span class="hmp-muted">-</span>'
    )


def missing(name: str):
    return [H.raw(f'<p class="hmp-gap">No catalog data ({esc(name)}): run tools/docs/data.py.</p>')]


def source_path(dotted: str) -> str | None:
    """The file of a dotted class path, relative to the repository, when it exists."""
    parts = dotted.split(".")
    for end in range(len(parts), 0, -1):
        base = "/".join(parts[:end])
        for candidate in (f"{base}.py", f"{base}/__init__.py"):
            if (REPO_ROOT / candidate).is_file():
                return candidate
    return None


def code_link(dotted: str) -> str:
    """A class path as code, linked to its file on GitHub at the built commit."""
    import hmp_api

    rel = source_path(dotted)
    if rel is None:
        return f"<code>{esc(dotted)}</code>"
    return f'<a href="{esc(hmp_api.source_url(rel))}"><code>{esc(dotted)}</code></a>'


def toml_link(builder, doc: str, path: str, label: str | None = None) -> str:
    return (
        f'<a class="hmp-toml-ref" href="{esc(H.uri(builder, doc, path))}">'
        f"<code>{esc(label or path)}</code></a>"
    )


# ---------------------------------------------------------------- solvers


class SolversDirective(SphinxDirective):
    """Every backend the solver registry serves, with the attributes it declares."""

    def run(self):
        rows = DATA.get("solvers")
        if not rows:
            return missing("solvers")
        builder, doc = H.current_builder(), self.env.docname
        body = []
        for r in rows:
            meshes = (
                code_list(r["accepted_meshes"])
                if r["accepted_meshes"]
                else '<span class="hmp-muted">the mesh of its flow</span>'
            )
            declares = (
                f"<div>category <code>{esc(r['category'])}</code></div>"
                f"<div>grid on <code>{esc(r['geometry'])}</code></div>"
                f"<div>meshes {meshes}</div>"
            )
            if r["reads"]:
                declares += f"<div>reads {code_list(r['reads'])}</div>"
            writes = (
                '<div class="hmp-chips">'
                + " ".join(f'<span class="hmp-chip">{esc(name)}</span>' for name in r["writes"])
                + "</div>"
            )
            supports = (
                '<div class="hmp-chips">'
                + " ".join(f'<span class="hmp-chip">{esc(name)}</span>' for name in r["supports"])
                + "</div>"
                if r["supports"]
                else '<span class="hmp-muted">-</span>'
            )
            sel = [f'type = "{r["process"]}"', f'solvers = ["{r["solver"]}"]']
            select = (
                f"{toml_link(builder, doc, 'simulation.process', '[[simulation.process]]')}"
                f'<pre class="hmp-sel">{esc(chr(10).join(sel))}</pre>'
            )
            if r["backend_key"]:
                select += (
                    f"{toml_link(builder, doc, 'solver.backend.backend', '[solver]')}"
                    f'<pre class="hmp-sel">backend = {{ backend = "{esc(r["solver"])}" }}</pre>'
                )
            if r.get("executable"):
                exe = (
                    f"<code>{esc(r['executable'])}</code>"
                    f'<div class="hmp-muted hmp-cat-sum"><code>hmp install-binaries --subset {esc(r["executable"])}</code></div>'
                )
            else:
                exe = '<span class="hmp-muted">none, it ships with HydroModPy</span>'
            req = (
                ", ".join(f"<code>{esc(p)}/{esc(s)}</code>" for p, s in r["requires"])
                or '<span class="hmp-muted">-</span>'
            )
            body.append(
                f"<tr><td><code>{esc(r['process'])}</code></td>"
                f"<td><code>{esc(r['solver'])}</code></td>"
                f"<td>{declares}</td><td>{writes}</td><td>{supports}</td>"
                f"<td>{select}</td><td>{exe}</td><td>{req}</td>"
                f"<td>{'yes' if r['extractor'] else 'no'}</td></tr>"
            )
        return [
            H.raw(
                '<div class="hmp-matrix-wrap"><table class="hmp-cat hmp-solvers"><thead><tr><th>Process</th><th>Solver</th>'
                "<th>Declares</th><th>Writes</th><th>Supports</th><th>Select it with</th>"
                "<th>Executable</th><th>Needs a run of</th>"
                "<th>Results read back</th></tr></thead>"
                f"<tbody>{''.join(body)}</tbody></table></div>"
            )
        ]


# ---------------------------------------------------------------- figures


def thumbnail(doc: str, name: str):
    """URL, width and height of the preview image of a figure, or None when there is none."""
    root = SRCDIR[0] if SRCDIR else None
    if root is None:
        return None
    for suffix in THUMB_SUFFIXES:
        path = root / THUMB_DIR / f"{name}{suffix}"
        if path.is_file():
            size = (0, 0)
            try:
                from PIL import Image

                with Image.open(path) as img:
                    size = img.size
            except Exception:
                pass
            depth = doc.count("/")
            return "../" * depth + f"{THUMB_DIR}/{name}{suffix}", size[0], size[1]
    return None


def img_tag(thumb, cls: str) -> str:
    url, w, h = thumb
    dims = f' width="{w}" height="{h}"' if w and h else ""
    return f'<img class="{cls}" src="{esc(url)}"{dims} loading="lazy" alt="">'


def options_table(r: dict, builder, doc: str) -> str:
    rows = []
    for o in r["option_details"]:
        text = o["doc"]
        if o["name"] == "figsize":
            text = f"{text} For this figure: `{tuple(r['default_figsize'])}`."
        if o.get("python_only"):
            text = f"{text} Python only: `Run.figure` takes it, a TOML file cannot write it."
        typ = f"<code>{esc(o['type'])}</code>" if o["type"] else ""
        default = f"<code>{esc(o['default'])}</code>" if o["default"] is not None else ""
        unit = f"<code>{esc(o['unit'])}</code>" if o.get("unit") else ""
        what = H.inline_md(text, builder, doc) if text else '<span class="hmp-muted">-</span>'
        rows.append(
            f"<tr><td><code>{esc(o['name'])}</code></td><td>{typ}</td><td>{default}</td>"
            f"<td>{unit}</td><td>{what}</td></tr>"
        )
    if not rows:
        return '<span class="hmp-muted">none</span>'
    return (
        '<div class="hmp-matrix-wrap"><table class="api-t hmp-opts"><thead><tr><th>Option</th><th>Type</th>'
        "<th>Default</th><th>Unit</th><th>What it does</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


class FiguresDirective(SphinxDirective):
    """Every registered figure, by kind, with what it reads and the options it takes."""

    def run(self):
        rows = DATA.get("figures")
        if not rows:
            return missing("figures")
        builder, doc = H.current_builder(), self.env.docname
        by_kind: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_kind[r["kind"]].append(r)
        figures_uri = H.uri(builder, doc, "display.figures")
        overrides_uri = H.uri(builder, doc, "display.overrides")
        subjects = figure_subjects()
        kinds = sorted(by_kind)
        chips = "".join(
            f'<button type="button" class="hmp-chip hmp-chip-btn" data-kind="{esc(k)}" aria-pressed="false">'
            f'{esc(k.capitalize())} <span class="hmp-muted">{len(by_kind[k])}</span></button>'
            for k in kinds
        )
        parts = [
            f'<p class="hmp-cat-count">{len(rows)} figures. A run draws the ones named in '
            f'<a class="hmp-toml-ref" href="{esc(figures_uri)}"><code>display.figures</code></a>; '
            f'<a class="hmp-toml-ref" href="{esc(overrides_uri)}"><code>display.overrides</code></a> '
            "sets their options. <code>hmp show &lt;run&gt; --figure &lt;name&gt;</code> draws one figure of a stored run.</p>",
            '<div class="hmp-cat-bar" role="search">'
            '<input type="search" class="hmp-filter" data-cards="hmp-figs" '
            'placeholder="Filter by name, title, field or option" aria-label="Filter the figures">'
            f'<span class="hmp-chips" role="group" aria-label="Filter by kind">{chips}</span>'
            f'<span class="hmp-cat-shown" aria-live="polite" data-total="{len(rows)}"></span></div>',
            '<div id="hmp-figs">',
        ]
        for kind in kinds:
            parts.append(
                f'<section class="hmp-fig-kind" data-kind="{esc(kind)}"><h2 id="figkind-{esc(kind)}">{esc(kind.capitalize())}</h2>'
            )
            for r in by_kind[kind]:
                reads = []
                if r["required_fields"]:
                    reads.append("fields " + code_list(r["required_fields"]))
                if r["optional_fields"]:
                    reads.append("if present " + code_list(r["optional_fields"]))
                if r["required_tables"]:
                    reads.append("tables " + code_list(r["required_tables"]))
                subject = subjects.get(r["name"], "run")
                facts = [
                    f"<li><b>Subject</b> <code>{esc(subject)}</code></li>",
                    f"<li><b>Reads</b> {'; '.join(reads) or '<span class=hmp-muted>nothing fixed</span>'}</li>",
                ]
                if r["availability_rule"]:
                    facts.append(
                        f"<li><b>Drawn when</b> {H.inline_md(r['availability_rule'], builder, doc)}</li>"
                    )
                elif r["own_availability_rule"]:
                    facts.append(
                        "<li><b>Drawn when</b> its own rule says the run can feed it.</li>"
                    )
                if r["former_names"]:
                    facts.append(f"<li><b>Former names</b> {code_list(r['former_names'])}</li>")
                facts.append(f"<li><b>In the code</b> {code_link(r['source'])}</li>")
                thumb = thumbnail(doc, r["name"])
                small = img_tag(thumb, "hmp-fig-thumb") if thumb else ""
                big = f"<p>{img_tag(thumb, 'hmp-fig-img')}</p>" if thumb else ""
                haystack = " ".join(
                    [
                        r["name"],
                        r["title"],
                        r["kind"],
                        subject,
                        r["summary"],
                        *r["required_fields"],
                        *r["optional_fields"],
                        *r["required_tables"],
                        *r["options"],
                        *r["former_names"],
                    ]
                )
                parts.append(
                    f'<details class="hmp-val hmp-fig" id="fig-{esc(r["name"])}" data-kind="{esc(kind)}" '
                    f'data-text="{esc(haystack.lower())}"><summary>{small}'
                    f'<span class="hmp-cat-title"><code>{esc(r["name"])}</code></span> {esc(r["title"])}</summary>'
                    f'<div class="hmp-val-body">{big}<p>{H.inline_md(r["summary"], builder, doc)}</p>'
                    f'<ul class="hmp-facts">{"".join(facts)}</ul>'
                    f'<div class="hmp-val-h">Options</div>{options_table(r, builder, doc)}</div></details>'
                )
            parts.append("</section>")
        parts.append("</div>")
        return [H.raw("".join(parts))]


# ---------------------------------------------------------------- data sources


def licence_html(s: dict) -> str:
    spdx = s.get("licence")
    if not spdx or spdx == "LicenseRef-undetermined":
        return '<span class="hmp-chip hmp-chip-warn">licence not determined</span>'
    url = s.get("licence_url") or (
        None if spdx.startswith("LicenseRef") else f"https://spdx.org/licenses/{spdx}.html"
    )
    text = f'<a href="{esc(url)}">{esc(spdx)}</a>' if url else esc(spdx)
    bits = [f"licence {text}"]
    if s.get("confidence"):
        bits.append(f'<span class="hmp-chip">{esc(s["confidence"])}</span>')
    if s.get("share_alike"):
        bits.append('<span class="hmp-chip">share-alike</span>')
    return " ".join(bits)


def pretty(value) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{esc(k)}: {pretty(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(pretty(v) for v in value)
    return esc(value)


def details_html(s: dict) -> str:
    """Every remaining field the source registry carries, for a source."""
    items = []
    if s.get("attribution"):
        items.append(f"<li><b>Attribution</b> {esc(s['attribution'])}</li>")
    if s.get("downloads"):
        items.append(f"<li><b>Hosts contacted</b> {code_list(s['downloads'])}</li>")
    for key, value in (s.get("extra") or {}).items():
        items.append(f"<li><b>{esc(key.replace('_', ' ').capitalize())}</b> {pretty(value)}</li>")
    if s.get("basis"):
        items.append(f"<li><b>Why this licence</b> {esc(s['basis'])}</li>")
    if not items:
        return ""
    return (
        '<details class="hmp-src-more"><summary>Details</summary>'
        f'<ul class="hmp-facts">{"".join(items)}</ul></details>'
    )


class DataSourcesDirective(SphinxDirective):
    """Every data variable, the sources its ``source`` key accepts, or the same by provider."""

    option_spec = {"view": directives.unchanged}

    def run(self):
        rows = DATA.get("data_sources")
        if not rows:
            return missing("data sources")
        if self.options.get("view") == "provider":
            return self.by_provider()
        return self.by_section(rows)

    def by_section(self, rows):
        builder, doc = H.current_builder(), self.env.docname
        body = []
        for r in rows:
            section = toml_link(builder, doc, r["section"], f"[{r['section']}]")
            items = []
            for s in r["sources"]:
                if s["value"] == "custom":
                    items.append("<li><code>custom</code>: a file of the project</li>")
                    continue
                bits = []
                if s.get("downloads"):
                    bits.append(
                        "downloads from "
                        + ", ".join(f"<code>{esc(h)}</code>" for h in s["downloads"])
                    )
                elif s.get("known"):
                    bits.append("built or read locally")
                if s.get("payload_kind"):
                    bits.append(f"serves <code>{esc(s['payload_kind'])}</code>")
                if s.get("publisher"):
                    bits.append(esc(s["publisher"]))
                if s.get("known"):
                    bits.append(licence_html(s))
                doc_txt = (
                    f'<div class="hmp-muted">{H.inline_md(s["doc"], builder, doc)}</div>'
                    if s["doc"]
                    else ""
                )
                items.append(
                    f"<li><code>{esc(s['value'])}</code>: {' · '.join(bits)}{doc_txt}{details_html(s)}</li>"
                )
            note = (
                '<div class="hmp-muted hmp-cat-sum">The key takes the name of any source '
                "registered with the data-source port; the list shows the registered ones.</div>"
                if r["free_text"]
                else ""
            )
            body.append(f"<tr><td>{section}</td><td><ul>{''.join(items)}</ul>{note}</td></tr>")
        return [
            H.raw(
                '<div class="hmp-cat-bar"><input type="search" class="hmp-filter" data-rows="hmp-src-section" '
                'placeholder="Filter by section, source or publisher" aria-label="Filter the data sections"></div>'
                '<table id="hmp-src-section" class="hmp-cat"><thead><tr><th>Section</th>'
                "<th>Accepted values of <code>source</code></th></tr></thead>"
                f"<tbody>{''.join(body)}</tbody></table>"
            )
        ]

    def by_provider(self):
        providers = DATA.get("providers")
        if not providers:
            return missing("providers")
        builder, doc = H.current_builder(), self.env.docname
        parts = [
            '<div class="hmp-cat-bar"><input type="search" class="hmp-filter" data-cards="hmp-providers" '
            'placeholder="Filter by publisher, source or section" aria-label="Filter the publishers"></div>',
            '<div id="hmp-providers">',
        ]
        for group in providers:
            rows = []
            for s in group["sources"]:
                feeds = (
                    " ".join(toml_link(builder, doc, f, f"[{f}]") for f in s["feeds"])
                    or '<span class="hmp-muted">no section lists it</span>'
                )
                rows.append(
                    f"<tr><td><code>{esc(s['slug'])}</code></td><td>{feeds}</td>"
                    f"<td>{licence_html(s)}</td><td>{details_html(s)}</td></tr>"
                )
            haystack = " ".join(
                [group["publisher"]]
                + [s["slug"] for s in group["sources"]]
                + [f for s in group["sources"] for f in s["feeds"]]
            )
            parts.append(
                f'<section class="hmp-provider" data-text="{esc(haystack.lower())}"><h3>{esc(group["publisher"])}</h3>'
                '<div class="hmp-matrix-wrap"><table class="api-t"><thead><tr><th>Source</th><th>Feeds</th>'
                "<th>Licence</th><th>More</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table></div></section>"
            )
        parts.append("</div>")
        return [H.raw("".join(parts))]


class OutputsDirective(SphinxDirective):
    """The field arrays or the time series a run stores, from the results registry."""

    required_arguments = 1

    def run(self):
        kind = self.arguments[0]
        if kind not in ("fields", "series"):
            raise self.error(f"hmp-outputs takes 'fields' or 'series', not {kind!r}")
        rows = DATA.get("outputs", {}).get(kind)
        if not rows:
            return missing("outputs")
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[r.get("group", "")].append(r)
        head = (
            "<thead><tr><th>Name</th><th>Path in the store</th><th>Unit</th>"
            "<th>Dimensions</th><th>What it holds</th></tr></thead>"
        )
        parts = []
        for group, items in groups.items():
            if kind == "fields":
                parts.append(f"<h3>{esc(group) if group else 'Top level'}</h3>")
            body = "".join(
                f"<tr><td><code>{esc(r['name'])}</code></td><td><code>{esc(r['path'])}</code></td>"
                f"<td><code>{esc(r['unit'])}</code></td><td>{esc(r['dimensions'])}</td>"
                f"<td>{esc(r['long_name'])}</td></tr>"
                for r in items
            )
            parts.append(f'<table class="api-t">{head}<tbody>{body}</tbody></table>')
        return [H.raw("".join(parts))]


# ---------------------------------------------------------------- figure requests


def html_table(head: list[str], rows: list[list[str]]) -> str:
    """A table whose cells are already HTML."""
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return (
        f'<div class="hmp-matrix-wrap"><table class="api-t"><thead><tr>{th}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def code(text) -> str:
    return f"<code>{esc(text)}</code>" if text not in ("", None) else ""


def request_fields(data: dict, builder, doc: str) -> list[str]:
    parts = []
    for key, title in (
        ("figure", "Fields of a figure"),
        ("panel", "Fields of a panel"),
        ("preset_panel", "Field a panel of a preset adds"),
    ):
        rows = [
            [
                code(r["name"]),
                code(r["type"]),
                code(r["default"]),
                H.inline_md(r["description"], builder, doc) if r["description"] else "",
                code_list(r["accepted"]) if r["accepted"] else "",
            ]
            for r in data["fields"][key]
        ]
        parts.append(f"<h3>{esc(title)}</h3>")
        parts.append(html_table(["Field", "Type", "Default", "What it does", "Accepted"], rows))
    return parts


def request_frames(data: dict) -> list[str]:
    rows = [
        [
            code(r["name"]),
            esc(r["summary"]) or '<span class="hmp-muted">not drawn yet</span>',
            code_list(r["shapes"]),
            code_list(r["overlays"]),
        ]
        for r in data["frames"]
    ]
    return [html_table(["Frame", "What it draws", "Shapes it takes", "Overlays by default"], rows)]


def request_vocabularies(data: dict) -> list[str]:
    rows = []
    for group in data["vocabularies"]:
        values = " ".join(
            f"{code(v['value'])}"
            + (f" {esc(v['note'])}" if v["note"] else "")
            + ("" if v["ready"] else ' <span class="hmp-muted">(not drawn yet)</span>')
            for v in group["values"]
        )
        rows.append([esc(group["name"]), values])
    return [html_table(["Closed value", "Accepted"], rows)]


def request_quantities(data: dict) -> list[str]:
    head = ["Quantity", "Stored in", "Shown in", "Sign", "Scale", "Log", "Layers", "Running sum"]
    rows = [
        [
            code(r["name"]),
            code(r["stored_unit"]),
            code(r["display_unit"]),
            esc(r["sign"]),
            esc(r["scale"]),
            "yes" if r["log"] else "",
            esc(r["layers"]),
            code(r["cumulates_to"]),
        ]
        for r in data["quantities"]
    ]
    return [html_table(head, rows)]


def request_variables(data: dict) -> list[str]:
    parts = []
    for group in data["variables"]:
        rows = [
            [
                code(r["name"]),
                esc(r["label"]),
                code(r["unit"]),
                code(r["quantity"]),
                code(r["frame"]),
            ]
            for r in group["rows"]
        ]
        parts.append(f"<h3>{esc(group['registry'])}</h3>")
        parts.append(html_table(["Name", "Label", "Unit", "Quantity", "Natural frame"], rows))
    return parts


def request_presets(data: dict) -> list[str]:
    rows = []
    for r in data["presets"]:
        panels = "".join(
            f"<li>{code(p['frame'])} "
            + ", ".join(f"{esc(k)} = {code(v)}" for k, v in p["written"].items())
            + (f"<div>Holes {code_list(p['holes'])}</div>" if p["holes"] else "")
            + "</li>"
            for p in r["panels"]
        )
        rows.append([code(r["name"]), esc(r["width"]), f"<ol>{panels}</ol>"])
    return [html_table(["Preset", "Width", "Panels it expands to"], rows)]


def request_specials(data: dict) -> list[str]:
    rows = [
        [
            code(r["name"]),
            code(r["subject"]),
            esc(r["width"]),
            code_list(r["keywords"]),
            code_list(r["reads"]),
            esc(r["summary"]),
        ]
        for r in data["specials"]
    ]
    head = ["Special figure", "Subject", "Width", "Takes", "Reads", "What it draws"]
    return [html_table(head, rows)]


def request_overlays(data: dict, builder, doc: str) -> list[str]:
    rows = [
        [
            code(r["name"]),
            code_list(r["reads"]),
            code_list(r["default_in"]),
            H.inline_md(r["summary"], builder, doc) if r["summary"] else "",
        ]
        for r in data["overlays"]
    ]
    return [html_table(["Overlay", "Reads the field", "On by default in", "What it draws"], rows)]


class FigureRequestsDirective(SphinxDirective):
    """One table of the figure request reference, read from the code of the request path."""

    required_arguments = 1
    SECTIONS = (
        "fields",
        "frames",
        "vocabularies",
        "quantities",
        "variables",
        "presets",
        "specials",
        "overlays",
    )

    def run(self):
        section = self.arguments[0]
        if section not in self.SECTIONS:
            raise self.error(f"hmp-figure-requests takes one of {', '.join(self.SECTIONS)}")
        data = DATA.get("figure_requests")
        if not data:
            return missing("figure requests")
        builder, doc = H.current_builder(), self.env.docname
        write = globals()[f"request_{section}"]
        if section in ("fields", "overlays"):
            parts = write(data, builder, doc)
        else:
            parts = write(data)
        return [H.raw("".join(parts))]


def setup_catalogs(app) -> None:
    app.connect("builder-inited", lambda a: load(Path(a.srcdir)))
    app.add_directive("hmp-solvers", SolversDirective)
    app.add_directive("hmp-figures", FiguresDirective)
    app.add_directive("hmp-data-sources", DataSourcesDirective)
    app.add_directive("hmp-outputs", OutputsDirective)
    app.add_directive("hmp-figure-requests", FigureRequestsDirective)
