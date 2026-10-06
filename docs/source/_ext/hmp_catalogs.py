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
from sphinx.util.docutils import SphinxDirective

DATA: dict = {}


def load(srcdir: Path) -> None:
    DATA.clear()
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


class SolversDirective(SphinxDirective):
    """Every (process, solver) pair the solver registry knows."""

    def run(self):
        rows = DATA.get("solvers")
        if not rows:
            return missing("solvers")
        body = []
        for r in rows:
            caps = "".join(f'<span class="tc">{esc(c)}</span>' for c in r["capabilities"])
            req = (
                ", ".join(f"<code>{esc(p)}/{esc(s)}</code>" for p, s in r["requires"])
                or '<span class="hmp-muted">-</span>'
            )
            body.append(
                f"<tr><td><code>{esc(r['process'])}</code></td><td><code>{esc(r['solver'])}</code>"
                f'<div class="hmp-muted hmp-cat-sum">{H.inline_md(r["summary"], self.env.app.builder, self.env.docname)}</div></td>'
                f"<td>{caps}</td><td>{req}</td><td>{'yes' if r['extractor'] else 'no'}</td></tr>"
            )
        return [
            H.raw(
                '<table class="hmp-cat"><thead><tr><th>Process</th><th>Solver</th><th>Capabilities</th>'
                "<th>Needs a run of</th><th>Results read back</th></tr></thead>"
                f"<tbody>{''.join(body)}</tbody></table>"
            )
        ]


class FiguresDirective(SphinxDirective):
    """Every registered figure, by kind, with what it reads and the options it takes."""

    def run(self):
        rows = DATA.get("figures")
        if not rows:
            return missing("figures")
        builder, doc = self.env.app.builder, self.env.docname
        by_kind: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_kind[r["kind"]].append(r)
        figures_uri = H.uri(builder, doc, "display.figures")
        overrides_uri = H.uri(builder, doc, "display.overrides")
        parts = [
            f'<p class="hmp-cat-count">{len(rows)} figures. A run draws the ones named in '
            f'<a class="hmp-toml-ref" href="{esc(figures_uri)}"><code>display.figures</code></a>; '
            f'<a class="hmp-toml-ref" href="{esc(overrides_uri)}"><code>display.overrides</code></a> '
            "sets their options. <code>hmp viz show &lt;run&gt; &lt;name&gt;</code> draws one figure of a stored run.</p>"
        ]
        for kind in sorted(by_kind):
            parts.append(f'<h2 id="figkind-{esc(kind)}">{esc(kind.capitalize())}</h2>')
            for r in by_kind[kind]:
                reads = []
                if r["required_fields"]:
                    reads.append("fields " + code_list(r["required_fields"]))
                if r["optional_fields"]:
                    reads.append("if present " + code_list(r["optional_fields"]))
                if r["required_tables"]:
                    reads.append("tables " + code_list(r["required_tables"]))
                facts = [
                    f"<li><b>Reads</b> {'; '.join(reads) or '<span class=hmp-muted>nothing fixed</span>'}</li>"
                ]
                if r["required_solvers"]:
                    facts.append(f"<li><b>Only with</b> {code_list(r['required_solvers'])}</li>")
                facts.append(f"<li><b>Options</b> {code_list(r['options'])}</li>")
                if r["former_names"]:
                    facts.append(f"<li><b>Former names</b> {code_list(r['former_names'])}</li>")
                if r["own_availability_rule"]:
                    facts.append("<li>Declares its own rule for when it can be drawn.</li>")
                facts.append(f"<li><b>In the code</b> <code>{esc(r['source'])}</code></li>")
                parts.append(
                    f'<details class="hmp-val" id="fig-{esc(r["name"])}"><summary>'
                    f'<span class="hmp-val-title"><code>{esc(r["name"])}</code></span> {esc(r["title"])}</summary>'
                    f'<div class="hmp-val-body"><p>{H.inline_md(r["summary"], builder, doc)}</p>'
                    f'<ul class="hmp-facts">{"".join(facts)}</ul></div></details>'
                )
        return [H.raw("".join(parts))]


class DataSourcesDirective(SphinxDirective):
    """Every data variable, the sources its ``source`` key accepts, and who publishes them."""

    def run(self):
        rows = DATA.get("data_sources")
        if not rows:
            return missing("data sources")
        builder, doc = self.env.app.builder, self.env.docname
        body = []
        for r in rows:
            section = f'<a class="hmp-toml-ref" href="{esc(H.uri(builder, doc, r["section"]))}"><code>[{esc(r["section"])}]</code></a>'
            items = []
            for s in r["sources"]:
                if s["value"] == "custom":
                    items.append("<li><code>custom</code>: a file of the project</li>")
                    continue
                if s["downloads"]:
                    where = "downloads from " + ", ".join(
                        f"<code>{esc(h)}</code>" for h in s["downloads"]
                    )
                else:
                    where = "built or read locally"
                bits = [where]
                if s.get("payload_kind"):
                    bits.append(f"serves <code>{esc(s['payload_kind'])}</code>")
                if s["publisher"]:
                    bits.append(esc(s["publisher"]))
                if s["licence"] and s["licence"] != "LicenseRef-undetermined":
                    lic = esc(s["licence"])
                    if s["licence_url"]:
                        lic = f'<a href="{esc(s["licence_url"])}">{lic}</a>'
                    bits.append("licence " + lic)
                else:
                    bits.append("licence not determined")
                doc_txt = f" {H.inline_md(s['doc'], builder, doc)}" if s["doc"] else ""
                items.append(
                    f"<li><code>{esc(s['value'])}</code>: {' · '.join(bits)}{doc_txt}</li>"
                )
            note = (
                f'<div class="hmp-muted hmp-cat-sum">{H.inline_md(r["description"], builder, doc)}</div>'
                if r["free_text"]
                else ""
            )
            sources = f"<ul>{''.join(items)}</ul>{note}"
            body.append(f"<tr><td>{section}</td><td>{sources}</td></tr>")
        return [
            H.raw(
                '<table class="hmp-cat"><thead><tr><th>Section</th><th>Accepted values of <code>source</code></th></tr></thead>'
                f"<tbody>{''.join(body)}</tbody></table>"
            )
        ]


def setup_catalogs(app) -> None:
    app.connect("builder-inited", lambda a: load(Path(a.srcdir)))
    app.add_directive("hmp-solvers", SolversDirective)
    app.add_directive("hmp-figures", FiguresDirective)
    app.add_directive("hmp-data-sources", DataSourcesDirective)
