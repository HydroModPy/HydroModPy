"""Annotated TOML view of the field registry, generated from the models only.

A section page reads like the file a user writes: one block per table, required keys
written, optional keys commented with their default, developer and expert keys folded,
one tab per shape of a union. No word on these pages is written outside the code.
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from pathlib import Path

import hmp_params as H
from docutils.parsers.rst import directives
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

logger = logging.getLogger(__name__)

BASE = "reference/parameters"
RELIABLE_UNITS = {"type", "metadata", "name"}


def esc(text) -> str:
    return html.escape(str(text), quote=True)


# ---------------------------------------------------------------- lines


def unit_of(n: dict) -> str | None:
    unit = n.get("unit")
    if not unit or n.get("unit_source") not in RELIABLE_UNITS:
        return None
    if unit == "-" and not n.get("numeric"):
        return None
    return unit


def value_for(n: dict) -> tuple[str, str, str | None]:
    """Value shown on the line, and why: req-ex, req, default, unset-ex, unset.

    Every value comes from the field: its default, or the first value of
    ``Field(examples=...)``. Nothing is read from an example project.
    """
    ex = (n.get("examples") or [None])[0]
    if n.get("required"):
        return (ex, "req-ex", ex) if ex else ("", "req", None)
    default = n.get("default")
    if default not in (None, "not set", "(computed)"):
        return default, "default", None
    if ex:
        return ex, "unset-ex", ex
    return "", "unset", None


def chips(n: dict, *, in_variant: bool) -> list[str]:
    out = []
    if n.get("required"):
        out.append('<span class="tc tc-req">required</span>')
    unit = unit_of(n)
    if unit:
        out.append(f'<span class="tc tc-unit">{esc(unit)}</span>')
    rng = H.range_text(n.get("range", {}))
    if rng:
        out.append(f'<span class="tc tc-range">{esc(rng)}</span>')
    if not in_variant and n.get("variants") and n.get("variant_field") and not n.get("is_tag"):
        host = H.node(n["path"].rsplit(".", 1)[0])
        shapes = {str(v["value"]) for v in host.get("variants_detail", [])}
        mine = [str(v) for v in n["variants"]]
        if set(mine) != shapes:
            vals = " | ".join(json.dumps(v) for v in mine)
            out.append(
                f'<span class="tc tc-when">only if {esc(n["variant_field"])} = {esc(vals)}</span>'
            )
    for w in n.get("when", []):
        vals = " | ".join(json.dumps(v) for v in w["values"])
        out.append(f'<span class="tc tc-when">only if {esc(w["field"])} = {esc(vals)}</span>')
    if n.get("calibrable"):
        tr = n["calibrable"].get("transform")
        out.append(
            f'<span class="tc tc-cal">calibrable{" · " + esc(tr) if tr and tr != "identity" else ""}</span>'
        )
    if n.get("profile") in ("dev", "expert"):
        out.append(f'<span class="tc tc-prof">{esc(n["profile"])}</span>')
    if n.get("stability") == "experimental":
        out.append('<span class="tc tc-exp">experimental</span>')
    if n.get("deprecated"):
        out.append('<span class="tc tc-exp">deprecated</span>')
    return out


def tline(
    builder,
    fromdoc: str,
    path: str,
    *,
    ids: set | None,
    in_variant: bool = False,
    chosen: str | None = None,
    chosen_doc: str = "",
) -> tuple[str, str]:
    """HTML of one key line, and its plain TOML text for the copy button."""
    n = H.node(path)
    name = n.get("name", path.rsplit(".", 1)[-1])
    if chosen is not None:
        value, kind, ex = json.dumps(chosen), "chosen", None
    else:
        value, kind, ex = value_for(n)
    commented = kind not in ("req", "req-ex", "chosen")
    if value:
        value_html = f'<span class="v">{esc(value)}</span>'
        plain_value = value
    else:
        value_html = f'<span class="ph">‹{esc(n.get("form") or "value")}›</span>'
        plain_value = f"<{n.get('form') or 'value'}>"
    code = (
        '<span class="cm"># </span>' if commented else ""
    ) + f'<span class="k">{esc(name)}</span><span class="eq"> = </span>{value_html}'
    summary = chosen_doc if chosen is not None else (n.get("summary") or "")
    if summary:
        note = f'<span class="tl-sum">{H.inline_md(summary, builder, fromdoc)}</span>'
    else:
        note = '<span class="tl-sum tl-gap">no description in the code</span>'
    bits = (
        chips(n, in_variant=in_variant)
        if chosen is None
        else ['<span class="tc tc-req">chosen shape</span>']
    )
    if kind in ("req-ex", "unset-ex") and ex:
        bits.append(
            '<span class="tc tc-ex" title="first value of Field(examples=...)">example value</span>'
        )
    adv = n.get("profile") in ("dev", "expert") and not n.get("required")
    anchor = H.anchor_of(path)
    id_attr = ""
    if ids is not None and anchor not in ids:
        ids.add(anchor)
        id_attr = f' id="{anchor}"'
    card = H.render_card(builder, fromdoc, path, n, {})
    cls = f"tl tl-{kind}" + (" tl-adv" if adv else "") + (" tl-cmt" if commented else "")
    line = (
        f'<details class="{cls}"{id_attr} data-path="{esc(path)}">'
        f'<summary><span class="tl-code">{code}</span><span class="tl-note">{note} {" ".join(bits)}</span></summary>'
        f"{card}</details>"
    )
    plain = ("# " if commented else "") + f"{name} = {plain_value}"
    return line, plain


def header_of(path: str) -> str:
    n = H.node(path)
    return f"[[{path}]]" if n.get("kind") == "array" else f"[{path}]"


def tblock(
    builder,
    fromdoc: str,
    table: str,
    *,
    variant: str | None = None,
    ids: set | None = None,
    only: list[str] | None = None,
    link_header: bool = False,
) -> str:
    n = H.node(table)
    leaves = (
        only if only is not None else [c for c in H.kids(table) if H.node(c).get("kind") == "leaf"]
    )
    disc = n.get("discriminator")
    tag_path = f"{table}.{disc}" if disc else None
    chosen_line = None
    if variant is not None:
        leaves = [
            p
            for p in leaves
            if not H.node(p).get("variants") or variant in [str(v) for v in H.node(p)["variants"]]
        ]
        leaves = [p for p in leaves if p != tag_path]
        doc = next(
            (v.get("doc", "") for v in n.get("variants_detail", []) if str(v["value"]) == variant),
            "",
        )
        if tag_path and tag_path in H.S["nodes"]:
            chosen_line = tline(
                builder, fromdoc, tag_path, ids=ids, in_variant=True, chosen=variant, chosen_doc=doc
            )
    req = [p for p in leaves if H.node(p).get("required")]
    opt = [
        p
        for p in leaves
        if not H.node(p).get("required") and H.node(p).get("profile", "user") == "user"
    ]
    adv = [
        p
        for p in leaves
        if not H.node(p).get("required") and H.node(p).get("profile", "user") != "user"
    ]
    rendered = []
    plain = [header_of(table)]
    if chosen_line:
        rendered.append(chosen_line[0])
        plain.append(chosen_line[1])
    for p in req + opt + adv:
        line, text = tline(builder, fromdoc, p, ids=ids, in_variant=variant is not None)
        rendered.append(line)
        if p not in adv:
            plain.append(text)
    head_target = H.uri(builder, fromdoc, table) if link_header else f"#{H.anchor_of(table)}"
    adv_btn = (
        f'<button class="tb-adv" type="button" data-n="{len(adv)}">show {len(adv)} dev/expert key{"s" if len(adv) > 1 else ""}</button>'
        if adv
        else ""
    )
    return (
        f'<div class="tb">'
        f'<div class="tb-bar"><a class="tb-h" href="{esc(head_target)}">{esc(header_of(table))}</a>'
        f'<span class="tb-actions">{adv_btn}<button class="tb-copy" type="button">copy</button></span></div>'
        f'<div class="tb-lines">{"".join(rendered)}</div>'
        f'<pre class="tb-src" hidden>{esc(chr(10).join(plain))}</pre>'
        f"</div>"
    )


def page_ids(env) -> set:
    return env.temp_data.setdefault("hmp_ids", set())


def search_text(n: dict) -> str:
    """Everything a reader may type to find a field: path, name, values, descriptions."""
    bits = [
        n.get("path", ""),
        n.get("name", ""),
        str(n.get("default") or ""),
        " ".join(str(v) for v in n.get("literal", [])),
        " ".join(f"{k} {v}" for k, v in (n.get("value_docs") or {}).items()),
        " ".join(n.get("examples") or []),
        str(n.get("unit") or ""),
        n.get("description", ""),
    ]
    return " ".join(b for b in bits if b)


class TBlockDirective(SphinxDirective):
    """One table as annotated TOML. With :variant:, the block of one shape of a union."""

    required_arguments = 1
    option_spec = {"variant": directives.unchanged}

    def run(self):
        from docutils import nodes

        path = self.arguments[0]
        if path not in H.S["nodes"]:
            logger.warning(f"[hmp] unknown table {path}", location=self.get_location())
            return []
        variant = self.options.get("variant")
        html_text = tblock(
            self.env.app.builder, self.env.docname, path, variant=variant, ids=page_ids(self.env)
        )
        leaves = [c for c in H.kids(path) if H.node(c).get("kind") == "leaf"]
        if variant:
            leaves = [
                p
                for p in leaves
                if not H.node(p).get("variants")
                or variant in [str(v) for v in H.node(p)["variants"]]
            ]
        hidden = nodes.paragraph(
            "", " ".join(search_text(H.node(p)) for p in leaves), classes=["hmp-search-text"]
        )
        return [H.raw(html_text), hidden]


class ParamsDirective(SphinxDirective):
    """Lines of the reference embedded in a guide, grouped under their table header."""

    has_content = True
    option_spec = {"flat": directives.flag, "advanced-title": directives.unchanged}

    def run(self):
        groups: dict[str, list[str]] = {}
        for line in self.content:
            line = line.strip()
            if not line:
                continue
            canon = H.resolve(line)
            if canon is None:
                logger.warning(f"[hmp] unknown TOML path {line}", location=self.get_location())
                continue
            n = H.node(canon)
            if n.get("kind") == "map" and H.kids(canon):
                canon = H.kids(canon)[0]
                n = H.node(canon)
            if n.get("kind") == "leaf":
                groups.setdefault(canon.rsplit(".", 1)[0], []).append(canon)
            else:
                groups.setdefault(canon, [])
        builder = self.env.app.builder
        parts = []
        for table, leaves in groups.items():
            if not leaves and not any(H.node(c).get("kind") == "leaf" for c in H.kids(table)):
                continue
            parts.append(
                tblock(
                    builder,
                    self.env.docname,
                    table,
                    only=leaves or None,
                    ids=None,
                    link_header=True,
                )
            )
        return [
            H.raw(
                f'<div class="hmp-embedded">{"".join(parts)}<p class="hmp-embed-note">Lines generated from the models, as in the reference. Open one for its card.</p></div>'
            )
        ]


# ---------------------------------------------------------------- connections


def ancestors(path: str) -> list[str]:
    parts = path.split(".")
    return [".".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]


def activations(path: str) -> list[str]:
    """List fields of an ancestor table whose description quotes the name of this table."""
    name = H.node(path).get("name", "")
    if not name or name.startswith("<"):
        return []
    pattern = re.compile(rf"['\"]{re.escape(name)}['\"]")
    out = []
    for anc in ancestors(path):
        for c in H.kids(anc):
            cn = H.node(c)
            if (
                cn.get("kind") == "leaf"
                and str(cn.get("form", "")).startswith("list of")
                and pattern.search(cn.get("description", ""))
            ):
                out.append(c)
    return out


def _table_names() -> Counter:
    if "table_names" not in H.S:
        H.S["table_names"] = Counter(
            n.get("name")
            for n in H.S["nodes"].values()
            if n.get("kind") not in (None, "leaf", "root")
        )
    return H.S["table_names"]


def same_name(path: str) -> list[str]:
    name = H.node(path).get("name", "")
    if not name or name.startswith("<") or not 2 <= _table_names()[name] <= 4:
        return []
    return [
        p
        for p, n in H.S["nodes"].items()
        if p != path
        and n.get("name") == name
        and n.get("kind") not in ("leaf", "root")
        and not p.startswith(path + ".")
        and not path.startswith(p + ".")
    ]


def choices_of(table: str) -> list[tuple[str, list]]:
    out = []
    for p in H.subtree(table):
        n = H.node(p)
        depth = p.count(".") - table.count(".")
        if (
            n.get("kind") == "leaf"
            and depth <= 2
            and len(n.get("literal", [])) >= 2
            and (n.get("is_tag") or n.get("name") in ("source", "kind", "type", "mode"))
        ):
            out.append((p, n["literal"]))
    return out[:3]


class LinksDirective(SphinxDirective):
    """What the code ties to this table: the list that switches it on, a table of the same
    name elsewhere, the tables the code names beside it."""

    required_arguments = 1

    def run(self):
        path = self.arguments[0]
        builder = self.env.app.builder
        doc = self.env.docname

        def ref(p: str, text: str | None = None) -> str:
            return f'<a class="hmp-toml-ref" href="{esc(H.uri(builder, doc, p))}"><code>{esc(text or p)}</code></a>'

        name = H.node(path).get("name", "")
        rows = []
        for leaf in activations(path):
            rows.append(f'<li><b>Read when</b> {ref(leaf)} lists <code>"{esc(name)}"</code>.</li>')
        for other in same_name(path):
            on = H.node(other)
            bits = [f"<b>Same name</b> {ref(other, header_of(other))}"]
            summ = on.get("summary") or on.get("doc")
            if summ:
                bits.append(H.inline_md(summ, builder, doc))
            for leaf in activations(other):
                bits.append(f'Read when {ref(leaf)} lists <code>"{esc(on.get("name"))}"</code>.')
            for leaf, values in choices_of(other):
                bits.append(
                    f"{ref(leaf, leaf.rsplit('.', 1)[-1])} = "
                    + " | ".join(f"<code>{esc(json.dumps(v))}</code>" for v in values)
                )
            rows.append("<li>" + " ".join(bits) + "</li>")
        mentions = list(H.node(path).get("co_mentions", []))
        for m in mentions[:5]:
            if m["other"] in same_name(path):
                continue
            title = esc(f"{m['func']}(): {m['text']}")
            rows.append(
                f"<li><b>Named with it in the code</b> {ref(m['other'])} "
                f'<span class="hmp-muted" title="{title}">{esc(m["file"])}:{m["line"]}</span></li>'
            )
        if not rows:
            return []
        return [
            H.raw(
                f'<div class="hmp-links"><div class="hmp-links-h">Connections found in the code</div><ul>{"".join(rows)}</ul></div>'
            )
        ]


# ---------------------------------------------------------------- explorer, quantities, sections


class ExplorerDirective(SphinxDirective):
    def run(self):
        builder = self.env.app.builder
        doc = self.env.docname

        def leaf_li(p: str) -> str:
            n = H.node(p)
            value, kind, _ = value_for(n)
            val = esc(value) if value else f"‹{esc(n.get('form') or '')}›"
            req = '<span class="tc tc-req">required</span>' if n.get("required") else ""
            unit = unit_of(n)
            unit_html = f'<span class="tc tc-unit">{esc(unit)}</span>' if unit else ""
            full = search_text(n)
            return (
                f'<li class="ex-leaf" data-profile="{esc(n.get("profile", "user"))}" data-path="{esc(p)}" data-text="{esc(full.lower())}" data-full="{esc(full)}">'
                f'<a href="{esc(H.uri(builder, doc, p))}"><code>{esc(n["name"])}</code></a>'
                f'<span class="ex-val"> = {val}</span> {req}{unit_html}'
                f'<span class="ex-sum">{H.inline_md(n.get("summary", ""), builder, doc)}</span></li>'
            )

        def table_li(p: str, depth: int) -> str:
            n = H.node(p)
            if n.get("kind") == "map" and H.kids(p):
                p = H.kids(p)[0]
                n = H.node(p)
            kids_ = H.kids(p)
            leaves = sorted((c for c in kids_ if H.node(c).get("kind") == "leaf"), key=H.sort_key)
            tables = [c for c in kids_ if H.node(c).get("kind") != "leaf"]
            count = H.leaf_count(p)
            text = esc(f"{p} {n.get('summary') or n.get('doc') or ''}".lower())
            inner = "".join(leaf_li(c) for c in leaves) + "".join(
                table_li(c, depth + 1) for c in tables
            )
            shapes = ""
            if n.get("variants_detail"):
                shapes = (
                    '<span class="tc tc-when">'
                    + esc(" | ".join(json.dumps(v["value"]) for v in n["variants_detail"]))
                    + "</span>"
                )
            return (
                f'<li class="ex-table" data-profile="{esc(n.get("profile", "user"))}" data-text="{text}"><details>'
                f'<summary><a href="{esc(H.uri(builder, doc, p))}"><code>{esc(header_of(p))}</code></a>'
                f' <span class="ex-count">{count}</span> {shapes}<span class="ex-sum">{H.inline_md(n.get("summary") or n.get("doc") or "", builder, doc)}</span></summary>'
                f"<ul>{inner}</ul></details></li>"
            )

        roots = H.S["meta"]["roots"]
        body = "".join(table_li(r, 0) for r in roots)
        return [
            H.raw(
                '<div class="hmp-explorer">'
                '<div class="ex-bar"><input type="search" id="ex-q" placeholder="Filter by key, path or word: snap, conductivity, recharge, outlet...">'
                '<label><input type="checkbox" id="ex-adv"> show dev/expert</label>'
                '<button type="button" id="ex-open">open all</button><button type="button" id="ex-close">close all</button>'
                '<span id="ex-count" class="hmp-muted"></span></div>'
                f'<ul class="ex-root">{body}</ul></div>'
            )
        ]


QUANTITIES = [
    ("Lengths, depths and distances", "metres", lambda n, u: u in ("m", "km")),
    ("Water depths and soil capacities", "millimetres", lambda n, u: u == "mm"),
    ("Durations", "days, seconds", lambda n, u: u in ("day", "s", "h")),
    ("Conductivities and fluxes", "m/s", lambda n, u: u == "m/s"),
    ("Storage", "1/m", lambda n, u: u == "1/m"),
    ("Discharges", "m3/s", lambda n, u: u == "m3/s"),
    ("Areas", "m2, km2", lambda n, u: u in ("m2", "km2")),
    ("Fractions and ratios", "dimensionless", lambda n, u: u in ("-", "%") and n.get("numeric")),
    ("Dates", "", lambda n, u: str(n.get("form", "")).startswith("date")),
    (
        "Files and folders",
        "",
        lambda n, u: (
            n.get("form") == "path" or n["name"].endswith(("_path", "_file", "_dir", "_folder"))
        ),
    ),
    ("Coordinate systems", "", lambda n, u: "crs" in n["name"]),
]


class QuantitiesDirective(SphinxDirective):
    def run(self):
        builder = self.env.app.builder
        doc = self.env.docname
        leaves = [
            (p, n)
            for p, n in H.S["nodes"].items()
            if n.get("kind") == "leaf" and n.get("profile") == "user"
        ]
        parts = ['<div class="hmp-quant">']
        nav = []
        for title, unit_label, test in QUANTITIES:
            hits = [(p, n) for p, n in leaves if test(n, unit_of(n))]
            if not hits:
                continue
            slug = title.lower().replace(",", "").replace(" ", "-")
            nav.append(
                f'<a href="#q-{slug}">{esc(title)} <span class="hmp-muted">({len(hits)})</span></a>'
            )
            rows = "".join(
                f'<tr><td><a href="{esc(H.uri(builder, doc, p))}"><code>{esc(p).replace(".", ".<wbr>")}</code></a></td>'
                f"<td>{esc(unit_of(n) or '')}</td><td>{'required' if n.get('required') else esc(n.get('default') or '')}</td>"
                f"<td>{H.inline_md(n.get('summary', ''), builder, doc)}</td></tr>"
                for p, n in sorted(hits)
            )
            parts.append(
                f'<h2 id="q-{slug}">{esc(title)}</h2>'
                + (f'<p class="hmp-muted">{esc(unit_label)}</p>' if unit_label else "")
                + f'<div class="hmp-matrix-wrap"><table class="hmp-qt"><thead><tr><th>Path</th><th>Unit</th><th>Default</th><th>What it is</th></tr></thead><tbody>{rows}</tbody></table></div>'
            )
        parts.append("</div>")
        return [H.raw('<p class="hmp-qnav">' + " · ".join(nav) + "</p>" + "".join(parts))]


class SectionsDirective(SphinxDirective):
    """Cards of the root sections, ordered by what a run needs."""

    def run(self):
        builder = self.env.app.builder
        doc = self.env.docname
        roots = H.S["meta"]["roots"]
        order = sorted(roots, key=lambda r: (0 if H.node(r).get("required") else 1, roots.index(r)))
        cards = []
        for r in order:
            n = H.node(r)
            leaves = [p for p in H.subtree(r) if H.node(p).get("kind") == "leaf"]
            user = sum(1 for p in leaves if H.node(p).get("profile") == "user")
            badges = []
            if n.get("required"):
                badges.append('<span class="tc tc-req">required</span>')
            if n.get("profile") != "user":
                badges.append(f'<span class="tc tc-prof">{esc(n.get("profile"))}</span>')
            target = H.doc_uri(builder, doc, H.a_doc(r))
            cards.append(
                H.card(
                    target,
                    header_of(r),
                    H.inline_md(n.get("summary") or n.get("doc") or "", builder, doc),
                    f"{user} user · {len(leaves) - user} dev/expert {' '.join(badges)}",
                )
            )
        return [H.raw(f'<div class="sec-grid">{"".join(cards)}</div>')]


# ---------------------------------------------------------------- pages


def variant_order(path: str) -> list[str]:
    n = H.node(path)
    disc = n.get("discriminator")
    vals = [str(v["value"]) for v in n.get("variants_detail", [])]
    tag = H.node(f"{path}.{disc}") if disc else {}
    default = str(tag.get("default") or "").strip('"')
    return sorted(vals, key=lambda v: (0 if v == default else 1, vals.index(v)))


def emit(path: str, level: int, lines: list[str], *, top: bool, here: str) -> None:
    n = H.node(path)
    anchors = [path]
    if n.get("kind") == "map" and H.kids(path):
        path = H.kids(path)[0]
        anchors.append(path)
        n = H.node(path)
    if not top:
        title = H.title_of(path) if H.node(path).get("kind") != "array" else f"`[[{path}]]`"
        if n.get("profile") != "user":
            title += f" {{bdg-secondary}}`{n.get('profile')}`"
        lines += ["", H.heading(level, title), ""]
    lines += ["```{hmp-anchor}"] + anchors + ["```", ""]
    if not top and (n.get("summary") or n.get("doc")):
        lines += [(n.get("doc") or n.get("summary")).replace("\n", " "), ""]
    if len(anchors) == 2:
        placeholder = anchors[1].rsplit(".", 1)[-1]
        lines += [
            f"One table per name you choose: `[{anchors[0]}.{placeholder}]`. The name is free text.",
            "",
        ]
    if n.get("kind") == "array":
        lines += [f"Repeat the table: one `[[{path}]]` block per item.", ""]
    if n.get("variants") and n.get("variant_field") and not top:
        vals = " | ".join(json.dumps(v) for v in n["variants"])
        lines += [f"Only with `{n['variant_field']} = {vals}`.", ""]
    lines += ["```{hmp-links} " + path, "```", ""]
    if n.get("known_keys"):
        lines += ["```{hmp-known-keys} " + path, ":variant: A", "```", ""]
    leaves = [c for c in H.kids(path) if H.node(c).get("kind") == "leaf"]
    if leaves:
        lines += ["```{hmp-index}"] + [f"single: {p}" for p in leaves] + ["```", ""]
    if n.get("variants_detail"):
        disc = n.get("discriminator") or "kind"
        lines += [
            f"`{disc}` selects the shape of this table. One tab per shape, the default first.",
            "",
        ]
        lines += ["::::{tab-set}", ""]
        for v in variant_order(path):
            lines += [
                f":::{{tab-item}} {json.dumps(v)}",
                "",
                "```{hmp-tblock} " + path,
                f":variant: {v}",
                "```",
                ":::",
                "",
            ]
        lines += ["::::", ""]
    elif leaves:
        lines += ["```{hmp-tblock} " + path, "```", ""]
    for c in sorted((c for c in H.kids(path) if H.node(c).get("kind") != "leaf"), key=H.sort_key):
        if H.a_doc(c) != here:
            continue
        emit(c, level + 1, lines, top=False, here=here)


def gen_pages(srcdir: Path) -> None:
    pages = H.S["split"]
    base = srcdir / BASE
    for root, docname in pages.items():
        rel = docname[len(BASE) + 1 :]
        lines = [
            "% AUTO-GENERATED by _ext/hmp_tview.py from the models. Do not edit.",
            "",
            H.heading(
                1, H.title_of(root) if H.node(root).get("kind") != "array" else f"`[[{root}]]`"
            ),
            "",
            "```{hmp-intro} " + root,
            "```",
            "",
        ]
        emit(root, 1, lines, top=True, here=docname)
        children = sorted(
            (
                c
                for c in pages
                if c != root
                and c.rsplit(".", 1)[0].replace(".<id>", "").replace(".<name>", "") == root
                and pages[c] != docname
            ),
            key=H.sort_key,
        )
        if children:
            lines += (
                [
                    "",
                    "## Tables on their own page",
                    "",
                    f"This table holds {H.leaf_count(root)} fields; above {H.SPLIT_THRESHOLD}, each sub-table gets its own page.",
                    "",
                    "```{hmp-sections-of} " + root,
                    "```",
                    "",
                    "```{toctree}",
                    ":hidden:",
                    "",
                ]
                + ["/" + pages[c] for c in children]
                + ["```", ""]
            )
        H.write_if_changed(base / (rel + ".md"), "\n".join(lines) + "\n")
    top_docs = [pages[r] for r in H.S["meta"]["roots"]]
    index = [
        "% AUTO-GENERATED by _ext/hmp_tview.py. Do not edit.",
        "",
        "# TOML parameters",
        "",
        "Every section of the configuration file, generated from the models. Each page reads like "
        "the file you write: one block per table, the keys you must write first, optional keys "
        "commented with their default, developer and expert keys behind a button, one tab per shape "
        "when a table has several. Click a line for its card.",
        "",
        "```{hmp-legend}",
        "```",
        "",
        "::::{grid} 1 1 3 3",
        ":gutter: 2",
        "",
        ":::{grid-item-card} The whole file as a tree",
        ":link: explorer",
        ":link-type: doc",
        "",
        "Every table and key, filterable. The fastest way to find a key.",
        ":::",
        "",
        ":::{grid-item-card} By what it measures",
        ":link: quantities",
        ":link-type: doc",
        "",
        "Lengths, durations, conductivities, dates, files: every user key grouped by its unit.",
        ":::",
        "",
        ":::{grid-item-card} The grammar of the file",
        ":link: grammar",
        ":link-type: doc",
        "",
        "Inheritance, quantities with units, dates, lists of tables.",
        ":::",
        "",
        "::::",
        "",
        "## Sections",
        "",
        "Required sections first, then the others in the order of the code.",
        "",
        "```{hmp-sections}",
        "```",
        "",
        "```{toctree}",
        ":hidden:",
        "",
        "explorer",
        "quantities",
        "grammar",
        "",
    ]
    index += ["/" + d for d in top_docs] + ["```", ""]
    H.write_if_changed(base / "index.md", "\n".join(index) + "\n")
    H.write_if_changed(
        base / "explorer.md",
        "% AUTO-GENERATED. Do not edit.\n\n# The whole file as a tree\n\n```{hmp-explorer}\n```\n",
    )
    H.write_if_changed(
        base / "quantities.md",
        "% AUTO-GENERATED. Do not edit.\n\n# Find a key by what it measures\n\nEvery user key whose unit or form the code declares, grouped by kind of quantity.\nA key with no declared unit does not appear here: the fix goes in its Pydantic field.\n\n```{hmp-quantities}\n```\n",
    )


class SectionsOfDirective(SphinxDirective):
    """Cards of the sub-tables of a split table."""

    required_arguments = 1

    def run(self):
        builder = self.env.app.builder
        doc = self.env.docname
        root = self.arguments[0]
        pages = H.S["split"]
        here = pages[root]
        children = [c for c in pages if c != root and c.startswith(root + ".") and pages[c] != here]
        direct = [
            c
            for c in children
            if not any(o != c and c.startswith(o + ".") and o in children for o in children)
        ]
        cards = []
        for c in sorted(direct, key=H.sort_key):
            n = H.node(c)
            leaves = [p for p in H.subtree(c) if H.node(p).get("kind") == "leaf"]
            user = sum(1 for p in leaves if H.node(p).get("profile") == "user")
            prof = (
                f'<span class="tc tc-prof">{esc(n.get("profile"))}</span>'
                if n.get("profile") != "user"
                else ""
            )
            cards.append(
                H.card(
                    H.doc_uri(builder, doc, pages[c]),
                    header_of(c),
                    H.inline_md(n.get("summary") or n.get("doc") or "", builder, doc),
                    f"{user} user · {len(leaves) - user} dev/expert {prof}",
                )
            )
        return [H.raw(f'<div class="sec-grid">{"".join(cards)}</div>')]


class LegendDirective(SphinxDirective):
    """A real small table rendered as a live legend of the conventions."""

    @staticmethod
    def pick() -> str:
        """First table, in the order of the code, that shows every kind of line."""
        for path, n in H.S["nodes"].items():
            if n.get("kind") not in ("table", "array") or n.get("variants_detail"):
                continue
            leaves = [H.node(c) for c in H.kids(path) if H.node(c).get("kind") == "leaf"]
            user = [x for x in leaves if x.get("profile") == "user"]
            req = [x for x in user if x.get("required")]
            opt = [x for x in user if not x.get("required")]
            adv = [x for x in leaves if x.get("profile") != "user"]
            if req and opt and adv and 3 <= len(user) <= 8:
                return path
        return H.S["meta"]["roots"][0]

    def run(self):
        builder = self.env.app.builder
        sample = self.pick()
        block = tblock(builder, self.env.docname, sample, ids=None, link_header=True)
        legend = (
            '<ul class="tl-legend">'
            '<li><span class="tl-key-req">written line</span> a key you must write; the value shown is an example the field declares, if any</li>'
            '<li><span class="tl-key-cmt"># commented line</span> optional: the value shown is the default</li>'
            '<li><span class="tl-key-ph">‹form›</span> no default: the accepted form of the value</li>'
            "<li>the button on the right shows the developer and expert keys, commented</li>"
            "</ul>"
        )
        return [H.raw(f'<div class="tl-legend-wrap">{block}{legend}</div>')]


def setup_tview(app) -> None:
    app.add_directive("hmp-tblock", TBlockDirective)
    app.add_directive("hmp-params", ParamsDirective, override=True)
    app.add_directive("hmp-explorer", ExplorerDirective)
    app.add_directive("hmp-quantities", QuantitiesDirective)
    app.add_directive("hmp-sections", SectionsDirective)
    app.add_directive("hmp-sections-of", SectionsOfDirective)
    app.add_directive("hmp-legend", LegendDirective)
    app.add_directive("hmp-links", LinksDirective)
