"""TOML parameter cards and the ``{toml}`` role, rendered from the field registry.

The registry is computed from the Pydantic models by ``tools/docs/field_registry.py``
and written to ``_data/`` at builder-inited, with the API index, the test index and
the TOML changelog. Nothing about a field is written by hand: a wrong card is fixed
in the model.
"""

from __future__ import annotations

import html
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.application import Sphinx
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

logger = logging.getLogger(__name__)

S: dict[str, Any] = {}

SPLIT_THRESHOLD = 120
PROFILE_RANK = {"user": 0, "dev": 1, "expert": 2}
HEADER = re.compile(r"^(\s*)(\[\[?)\s*([^\]]+?)\s*(\]\]?)(\s*#.*)?$")
KEYLINE = re.compile(r"^(\s*)([A-Za-z0-9_\-\.\"]+)(\s*=\s*)(.*)$")


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def anchor_of(path: str) -> str:
    return "p-" + re.sub(r"[^a-z0-9_]+", "-", path.lower().replace("<", "").replace(">", "")).strip(
        "-"
    )


# ---------------------------------------------------------------- data


def load_state(app: Sphinx) -> None:
    data = Path(app.srcdir) / "_data"
    reg = json.loads((data / "registry.json").read_text())
    S["meta"] = reg["meta"]
    S["nodes"] = reg["nodes"]
    S["fo"] = {}
    for name in ("gates", "changelog"):
        p = data / f"{name}.json"
        S[name] = json.loads(p.read_text()) if p.exists() else {}
    S["example_dir"] = Path(app.config.hmp_example_dir)
    S["split"] = split_plan()
    S["home"] = home_plan()


def node(path: str) -> dict[str, Any]:
    return S["nodes"].get(path, {})


def kids(path: str) -> list[str]:
    return node(path).get("children", [])


def subtree(path: str) -> list[str]:
    out = [path]
    for c in kids(path):
        out.extend(subtree(c))
    return out


def leaf_count(path: str) -> int:
    return sum(1 for p in subtree(path) if node(p).get("kind") == "leaf")


def split_plan() -> dict[str, str]:
    """Page root path -> docname. A table above the threshold gets
    one page per child table, down to two levels below the root."""
    pages: dict[str, str] = {}

    def visit(path: str, docname: str, depth: int) -> None:
        tables = [c for c in kids(path) if node(c).get("kind") != "leaf"]
        if leaf_count(path) > SPLIT_THRESHOLD and depth < 3 and tables:
            pages[path] = f"{docname}/index"
            for t in tables:
                visit(
                    t,
                    f"{docname}/{t.rsplit('.', 1)[1].replace('<', '').replace('>', '')}",
                    depth + 1,
                )
        else:
            pages[path] = docname

    for root in S["meta"]["roots"]:
        visit(root, f"reference/parameters/{root}", 1)
    return pages


def a_doc(path: str) -> str:
    best = ""
    for root in S["split"]:
        if (path == root or path.startswith(root + ".")) and len(root) > len(best):
            best = root
    return S["split"][best]


def home_plan() -> dict[str, str]:
    """Path -> the page that holds its card."""
    return {p: a_doc(p) for p in S["nodes"] if p}


def resolve(concrete: str) -> str | None:
    concrete = concrete.strip()
    if concrete in S["nodes"]:
        return concrete
    current = ""
    for seg in concrete.split("."):
        seg = seg.strip('"')
        for suffix in ("__append", "__delete"):
            if seg.endswith(suffix):
                seg = seg[: -len(suffix)]
        cands = kids(current)
        nxt = f"{current}.{seg}" if current else seg
        if nxt in cands:
            current = nxt
            continue
        if node(current).get("kind") == "map" and cands:
            current = cands[0]
            continue
        return None
    return current or None


def uri(builder, fromdoc: str, path: str, *, prefer_a: bool = False) -> str:
    target = a_doc(path) if prefer_a else S["home"].get(path)
    if not target:
        return "#"
    rel = "" if target == fromdoc else builder.get_relative_uri(fromdoc, target)
    return f"{rel}#{anchor_of(path)}"


def doc_uri(builder, fromdoc: str, todoc: str) -> str:
    return "" if todoc == fromdoc else builder.get_relative_uri(fromdoc, todoc)


# ---------------------------------------------------------------- formatting


def fmt_num(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def range_text(rng: dict[str, Any]) -> str:
    lo = rng.get("ge", rng.get("gt"))
    hi = rng.get("le", rng.get("lt"))
    lo_op = ">=" if "ge" in rng else ">"
    hi_op = "<=" if "le" in rng else "<"
    if lo is not None and hi is not None:
        lo_b = "[" if "ge" in rng else "]"
        hi_b = "]" if "le" in rng else "["
        return f"{lo_b}{fmt_num(lo)}, {fmt_num(hi)}{hi_b}"
    if lo is not None:
        return f"{lo_op} {fmt_num(lo)}"
    if hi is not None:
        return f"{hi_op} {fmt_num(hi)}"
    parts = []
    if "min_length" in rng:
        parts.append(f"at least {rng['min_length']} item(s)")
    if "max_length" in rng:
        parts.append(f"at most {rng['max_length']} item(s)")
    return ", ".join(parts)


def table_form(n: dict[str, Any]) -> str:
    kind = n.get("kind")
    if kind == "array":
        return "[[array of tables]]"
    if kind == "map":
        return "{ name = table }"
    if kind == "union":
        return "[table] (one of several shapes)"
    return "[table]"


def origin(text: str, written: bool) -> str:
    return f'<span data-origin="{"written" if written else "auto"}">{text}</span>'


def when_text(n: dict[str, Any], fo: dict[str, Any]) -> tuple[str, bool]:
    if fo.get("when"):
        return esc(fo["when"]), True
    parts = []
    host = node(n.get("path", "").rsplit(".", 1)[0]) if n.get("path") else {}
    all_shapes = {str(v["value"]) for v in host.get("variants_detail", [])}
    in_all = bool(all_shapes) and {str(v) for v in n.get("variants", [])} >= all_shapes
    if n.get("variants") and n.get("variant_field") and not n.get("is_tag") and not in_all:
        vals = " | ".join(json.dumps(v) for v in n["variants"])
        parts.append(f"{esc(n['variant_field'])} = {esc(vals)}")
    for w in n.get("when", []):
        vals = " | ".join(json.dumps(v) for v in w["values"])
        parts.append(f"{esc(w['field'])} = {esc(vals)}")
    return " and ".join(parts), False


# ---------------------------------------------------------------- rows


def render_row(builder, fromdoc: str, path: str, *, overlay: bool, show_path: bool = False) -> str:
    n = node(path)
    fo = S["fo"].get(path, {}) if overlay else {}
    is_leaf = n.get("kind") == "leaf"
    name = n.get("name", path.rsplit(".", 1)[-1])
    label = fo.get("label")
    label_fr = fo.get("label_fr") or (n.get("label_fr") if overlay else None)
    form = n.get("form", "") if is_leaf else table_form(n)
    if fo.get("form"):
        form_html = origin(esc(fo["form"]), True)
    else:
        form_html = origin(esc(form), False)
    if n.get("required"):
        default_html = '<span class="hmp-req" data-origin="auto">required</span>'
    else:
        default = n.get("default")
        default_html = (
            origin(f"<code>{esc(default)}</code>", False)
            if default not in (None, "not set")
            else origin('<span class="hmp-muted">not set</span>', False)
        )
    if fo.get("unit_text"):
        unit_html = origin(inline_md(fo["unit_text"], builder, fromdoc), True)
    elif n.get("unit") and not (n["unit"] == "-" and not n.get("numeric")):
        unit_html = origin(esc(n["unit"]), False)
    else:
        unit_html = ""
    badges = []
    wt, wt_written = when_text(n, fo)
    if wt:
        badges.append(
            f'<span class="hmp-b hmp-b-when" data-origin="{"written" if wt_written else "auto"}">only if {wt}</span>'
        )
    if n.get("calibrable"):
        tr = n["calibrable"].get("transform")
        badges.append(
            f'<span class="hmp-b hmp-b-cal" data-origin="auto">calibrable{" · " + esc(tr) if tr and tr != "identity" else ""}</span>'
        )
    if n.get("profile") in ("dev", "expert"):
        badges.append(
            f'<span class="hmp-b hmp-b-prof" data-origin="auto">{esc(n["profile"])}</span>'
        )
    if n.get("stability") == "experimental":
        badges.append('<span class="hmp-b hmp-b-exp" data-origin="auto">experimental</span>')
    if n.get("deprecated"):
        badges.append('<span class="hmp-b hmp-b-dep" data-origin="auto">deprecated</span>')
    if fo.get("flag"):
        badges.append(
            f'<span class="hmp-b hmp-b-flag" data-origin="written">{esc(fo["flag"])}</span>'
        )
    rng = range_text(n.get("range", {}))
    if rng:
        badges.append(f'<span class="hmp-b hmp-b-range" data-origin="auto">{esc(rng)}</span>')
    summary = fo.get("summary") or n.get("summary") or n.get("doc") or ""
    summary_html = origin(inline_md(summary, builder, fromdoc), bool(fo.get("summary")))
    title = f"<code>{esc(name)}</code>"
    if label or label_fr:
        bits = []
        if label:
            bits.append(f'<span class="hmp-label" data-origin="written">{esc(label)}</span>')
        if label_fr:
            bits.append(f'<span class="hmp-label-fr" data-origin="written">{esc(label_fr)}</span>')
        title += f'<span class="hmp-labels">{" · ".join(bits)}</span>'
    if show_path:
        title += f'<span class="hmp-labels hmp-rowpath">{esc(path.rsplit(".", 1)[0])}</span>'
    card = render_card(builder, fromdoc, path, n, fo)
    cls = "hmp-row" + ("" if is_leaf else " hmp-row-table")
    return (
        f'<details class="{cls}" id="{anchor_of(path)}" data-profile="{esc(n.get("profile", "user"))}" data-path="{esc(path)}">'
        f'<summary><span class="hmp-name">{title}</span>'
        f'<span class="hmp-form">{form_html}</span>'
        f'<span class="hmp-default">{default_html}</span>'
        f'<span class="hmp-unit">{unit_html}</span>'
        f'<span class="hmp-sumtext">{summary_html} {" ".join(badges)}</span>'
        f"</summary>{card}</details>"
    )


def clean_rst(text: str) -> str:
    """Docstrings carry RST: ``x`` and :role:`x` read as `x`."""
    text = re.sub(r"``([^`]+)``", r"`\1`", text or "")
    return re.sub(r":[a-z:]+:`~?([^`]+)`", r"`\1`", text)


def inline_md(text: str, builder, fromdoc: str) -> str:
    """Escape text, render `code`, and turn {toml}`path` into links."""
    out = esc(clean_rst(text))

    def toml_link(m: re.Match) -> str:
        target = html.unescape(m.group(1))
        canon = resolve(target)
        if canon is None:
            logger.warning(f"[hmp] unknown TOML path: {target}")
            return f'<code class="hmp-broken">{esc(target)}</code>'
        return f'<a class="hmp-toml-ref" href="{esc(uri(builder, fromdoc, canon))}"><code>{esc(target)}</code></a>'

    out = re.sub(r"\{toml\}`([^`]+)`", toml_link, out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return autolink_paths(_bold(out), builder, fromdoc)


def _bold(html_text: str) -> str:
    """Render **x** as bold, outside code spans."""
    parts = re.split(r"(<code\b.*?</code>)", html_text, flags=re.S)
    return "".join(
        part
        if part.startswith("<code")
        else re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", part)
        for part in parts
    )


def block_md(text: str, builder, fromdoc: str) -> str:
    """Paragraphs and "- " lists of a description, each line rendered by inline_md."""
    out = []
    for block in re.split(r"\n[ \t]*\n", (text or "").strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if all(line.startswith("- ") for line in lines):
            items = "".join(f"<li>{inline_md(line[2:], builder, fromdoc)}</li>" for line in lines)
            out.append(f"<ul>{items}</ul>")
        else:
            out.append(f"<p>{inline_md(' '.join(lines), builder, fromdoc)}</p>")
    return "".join(out)


_AUTO = re.compile(r"(?<![\w./#-])(\[{0,2})([a-z][a-z0-9_]*(?:\.[A-Za-z0-9_<>&;]+)+)(\]{0,2})")


def autolink_paths(html_text: str, builder, fromdoc: str) -> str:
    """Link every TOML path written in a description, outside tags and links."""
    roots = set(S["meta"]["roots"])
    parts = re.split(r"(<[^>]+>)", html_text)
    depth_a = 0
    for i, part in enumerate(parts):
        if part.startswith("<"):
            if part.startswith("<a "):
                depth_a += 1
            elif part.startswith("</a"):
                depth_a = max(0, depth_a - 1)
            continue
        if depth_a:
            continue

        def link(m: re.Match) -> str:
            raw_token = html.unescape(m.group(2))
            token = raw_token.rstrip(".,;:")
            trail = raw_token[len(token) :]
            if token.split(".")[0] not in roots:
                return m.group(0)
            canon = resolve(token)
            if canon is None:
                return m.group(0)
            return f'{m.group(1)}<a class="hmp-toml-ref hmp-auto" href="{esc(uri(builder, fromdoc, canon))}">{esc(token)}</a>{esc(trail)}{m.group(3)}'

        parts[i] = _AUTO.sub(link, part)
    return "".join(parts)


def render_card(builder, fromdoc: str, path: str, n: dict, fo: dict) -> str:
    rows = []

    def add(label: str, value: str) -> None:
        if value:
            rows.append(f"<dt>{label}</dt><dd>{value}</dd>")

    add(
        "Path",
        f'<code class="hmp-path">{esc(path)}</code> <button class="hmp-copy" data-copy="{esc(path)}" title="Copy">copy</button>',
    )
    if fo.get("detail"):
        add("What it does", origin(inline_md(fo["detail"], builder, fromdoc), True))
    desc = n.get("description") or n.get("doc") or ""
    if desc:
        label = "Docstring" if fo.get("summary") or fo.get("detail") else "Description"
        add(label, f'<div data-origin="auto">{block_md(desc, builder, fromdoc)}</div>')
    lits = n.get("literal", [])
    vdocs = dict(n.get("value_docs", {}))
    vdocs.update(fo.get("value_docs", {}))
    if lits:
        items = []
        for v in lits:
            doc = vdocs.get(str(v))
            written = str(v) in fo.get("value_docs", {})
            items.append(
                f"<li><code>{esc(json.dumps(v))}</code>"
                + (
                    f" : {origin(inline_md(doc, builder, fromdoc), written)}"
                    if doc
                    else ' <span class="hmp-gap" data-origin="auto">no explanation</span>'
                )
                + "</li>"
            )
        add("Values", f'<ul class="hmp-values">{"".join(items)}</ul>')
    if n.get("kind") == "leaf":
        accepted = esc(n.get("form", ""))
        if n.get("quantity"):
            accepted += (
                ' <span class="hmp-muted">(a bare number is read in the canonical unit)</span>'
            )
        add("Accepted", origin(accepted, False))
    rng = range_text(n.get("range", {}))
    if rng:
        add(
            "Valid range",
            origin(f'{esc(rng)} <span class="hmp-muted">(refused outside)</span>', False),
        )
    if (n.get("unit") and not (n["unit"] == "-" and not n.get("numeric"))) or fo.get("unit_text"):
        src = {
            "type": "from the quantity type",
            "metadata": "declared unit",
            "calibrable": "from the calibration metadata",
            "name": "from the name suffix",
        }.get(n.get("unit_source"), "")
        txt = (
            inline_md(fo["unit_text"], builder, fromdoc)
            if fo.get("unit_text")
            else esc(n.get("unit"))
        )
        add(
            "Unit",
            origin(txt, bool(fo.get("unit_text")))
            + (
                f' <span class="hmp-muted">({src})</span>'
                if src and not fo.get("unit_text")
                else ""
            ),
        )
    if fo.get("typical"):
        typ = fo["typical"]
        refs = "; ".join(typ.get("refs", []))
        add(
            "Typical",
            origin(
                inline_md(typ.get("text", ""), builder, fromdoc)
                + (f' <span class="hmp-ref">({esc(refs)})</span>' if refs else ""),
                True,
            ),
        )
    cal = n.get("calibrable")
    if cal:
        txt = f"yes, search space {esc(cal.get('transform'))}, prior {esc(cal.get('prior'))}"
        if cal.get("bounds"):
            txt += f", default bounds {esc(cal['bounds'])}"
        else:
            txt += ", bounds belong to the site: write them in the calibration section"
        add("Calibration", origin(txt, False))
    wt, wt_written = when_text(n, fo)
    if wt:
        add("Only if", origin(wt, wt_written))
    if n.get("kind") != "leaf" and n.get("variants_detail"):
        add(
            "Shapes",
            origin(
                ", ".join(
                    f"<code>{esc(json.dumps(v['value']))}</code>" for v in n["variants_detail"]
                ),
                False,
            ),
        )
    if fo.get("see_also"):
        links = []
        for target in fo["see_also"]:
            canon = resolve(target)
            if canon is None:
                logger.warning(f"[hmp] unknown see_also path: {target}")
                continue
            links.append(
                f'<a class="hmp-toml-ref" href="{esc(uri(builder, fromdoc, canon))}"><code>{esc(target)}</code></a>'
            )
        add("See also", origin(" ".join(links), True))
    if fo.get("note"):
        add("Note", origin(inline_md(fo["note"], builder, fromdoc), True))
    add("Profile", origin(esc(n.get("profile", "user")), False))
    if n.get("source"):
        add(
            "Declared in",
            origin(
                f'<code>{esc(n["source"])}</code> <span class="hmp-muted">({esc(n.get("model", ""))})</span>',
                False,
            ),
        )
    return f'<div class="hmp-card"><dl>{"".join(rows)}</dl></div>'


def sort_key(path: str) -> tuple:
    n = node(path)
    return (0 if n.get("required") else 1, PROFILE_RANK.get(n.get("profile", "user"), 0))


def render_rows(
    builder,
    fromdoc: str,
    paths: list[str],
    *,
    overlay: bool,
    collapse_advanced: bool = True,
    advanced_title: str = "Advanced settings",
    show_path: bool = False,
) -> str:
    basic = [p for p in paths if node(p).get("profile", "user") == "user"]
    adv = [p for p in paths if node(p).get("profile", "user") != "user"]
    if not collapse_advanced:
        basic, adv = paths, []
    out = ['<div class="hmp-rows">']
    out += [render_row(builder, fromdoc, p, overlay=overlay, show_path=show_path) for p in basic]
    out.append("</div>")
    if adv:
        counts = {}
        for p in adv:
            counts[node(p)["profile"]] = counts.get(node(p)["profile"], 0) + 1
        label = " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        out.append(
            f'<details class="hmp-advanced"><summary>{esc(advanced_title)} <span class="hmp-muted">({esc(label)})</span></summary><div class="hmp-rows">'
        )
        out += [render_row(builder, fromdoc, p, overlay=overlay, show_path=show_path) for p in adv]
        out.append("</div></details>")
    return "\n".join(out)


def raw(text: str) -> nodes.raw:
    return nodes.raw("", text, format="html")


def card(href: str, title: str, summary_html: str, meta_html: str) -> str:
    """One card of a grid. The title link covers the card through CSS.

    The card is not itself a link: a summary may hold links, and a link
    inside a link is invalid HTML that the browser splits apart.
    """
    return (
        f'<div class="sec-card"><a class="sec-title" href="{esc(href)}"><code>{esc(title)}</code></a>'
        f'<span class="sec-sum">{summary_html}</span><span class="sec-meta">{meta_html}</span></div>'
    )


# ---------------------------------------------------------------- directives


class AnchorDirective(SphinxDirective):
    """Invisible anchors for table paths, so {toml} links land on their heading."""

    has_content = True

    def run(self):
        spans = "".join(
            f'<span class="hmp-anchor" id="{anchor_of(p.strip())}"></span>'
            for p in self.content
            if p.strip()
        )
        return [raw(spans)]


class IndexDirective(SphinxDirective):
    """Several index entries at once, so search finds fields, labels and synonyms."""

    has_content = True

    def run(self):
        from sphinx import addnodes

        targetid = f"index-{self.env.new_serialno('index')}"
        index = addnodes.index(entries=[])
        for line in self.content:
            line = line.strip()
            if not line:
                continue
            value = line[len("single:") :].strip() if line.startswith("single:") else line
            index["entries"].append(("single", value, targetid, "", None))
        # A target node would hand its id to the raw HTML block that follows,
        # where the id is dropped; a raw anchor keeps it for the index and search.
        return [index, raw(f'<span id="{targetid}"></span>')]


class IntroDirective(SphinxDirective):
    """Automatic intro of a table: docstring, counts, files that write it."""

    required_arguments = 1

    def run(self):
        path = self.arguments[0]
        n = node(path)
        sub = [p for p in subtree(path) if node(p).get("kind") == "leaf"]
        counts = {
            k: sum(1 for p in sub if node(p).get("profile") == k) for k in ("user", "dev", "expert")
        }
        text = n.get("doc") or n.get("description") or ""
        intro = block_md(text, self.env.app.builder, self.env.docname)
        parts = [
            f'<div class="hmp-intro" data-origin="auto">{intro or "<p><span class=hmp-gap>no docstring</span></p>"}'
        ]
        facts = [
            f"<li><b>Path</b> <code>{esc(path)}</code> <span class='hmp-muted'>({esc(table_form(n))})</span></li>",
            f"<li><b>Required</b> {'yes' if n.get('required') else 'no'}</li>",
            f"<li><b>Fields</b> {len(sub)}: user {counts['user']}, dev {counts['dev']}, expert {counts['expert']}</li>",
        ]

        if n.get("source"):
            facts.append(
                f"<li><b>Model</b> <code>{esc(', '.join(n.get('models', [])))}</code> in <code>{esc(n['source'])}</code></li>"
            )
        user = [node(p) for p in sub if node(p).get("profile") == "user"]
        empty = sum(1 for x in user if not x.get("description"))
        short = sum(1 for x in user if 0 < len(x.get("description", "").split()) < 6)
        no_unit = sum(
            1
            for x in user
            if x.get("numeric")
            and not (x.get("unit") and x.get("unit_source") in ("type", "metadata", "name"))
        )
        no_vals = sum(1 for x in user if len(x.get("literal", [])) >= 2 and not x.get("value_docs"))
        gaps = [
            f"{n_} {one if n_ == 1 else many}"
            for n_, one, many in (
                (empty, "key without description", "keys without description"),
                (short, "description under six words", "descriptions under six words"),
                (no_unit, "number without a declared unit", "numbers without a declared unit"),
                (no_vals, "choice without explained values", "choices without explained values"),
            )
            if n_
        ]
        if gaps:
            facts.append(
                f"<li class='hmp-gaps'><b>Gaps in the models</b> {esc(', '.join(gaps))} <span class='hmp-muted'>(user keys; fixed in the Pydantic fields)</span></li>"
            )
        parts.append(f'<ul class="hmp-facts">{"".join(facts)}</ul></div>')
        return [raw("".join(parts))]


class KnownKeysDirective(SphinxDirective):
    """Named entries of a free-key table (flow.param.<id>), from the code."""

    required_arguments = 1
    option_spec = {"variant": directives.unchanged}

    def run(self):
        path = self.arguments[0]
        n = node(path)
        known = n.get("known_keys", {})
        ko: dict = {}
        rows = []
        for key, info in known.items():
            o = ko.get(key, {})
            label = o.get("label_en") or (info.get("label_en") or "").capitalize()
            label_html = origin(esc(label), bool(o.get("label_en")))
            fr = o.get("label_fr")
            phys = info.get("physical")
            phys_txt = (
                f"{fmt_num(phys[0])} .. {fmt_num(phys[1])}"
                if phys
                else '<span class="hmp-gap">no bound</span>'
            )
            note = o.get("note", "")
            rows.append(
                f"<tr><td><code>{esc(key)}</code></td><td>{label_html}"
                + (
                    f'<br><span class="hmp-label-fr" data-origin="written">{esc(fr)}</span>'
                    if fr
                    else ""
                )
                + f"</td><td data-origin='auto'>{esc(info.get('unit'))}</td><td data-origin='auto'>{phys_txt}</td>"
                f"<td>{origin(inline_md(note, self.env.app.builder, self.env.docname), True) if note else ''}</td></tr>"
            )
        table = (
            '<table class="hmp-known"><thead><tr><th>Name</th><th>Quantity</th><th>Unit</th>'
            "<th>Physical range (refused outside)</th><th></th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
            + f'<p class="hmp-muted hmp-small">Units and ranges come from <code>{esc(n.get("known_keys_source", ""))}</code>.</p>'
        )
        return [raw(table)]


# ---------------------------------------------------------------- TOML blocks


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if k.endswith("__append"):
            key = k[: -len("__append")]
            out[key] = list(out.get(key, [])) + list(v if isinstance(v, list) else [v])
        elif k.endswith("__delete"):
            continue
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_chain(path: Path) -> dict:
    try:
        from hydromodpy.core.toml_io.loader import load_toml_with_base_config

        return load_toml_with_base_config(path)
    except ImportError:
        pass
    data = tomllib.loads(path.read_text())
    base = data.pop("base_config", None)
    if base:
        return deep_merge(load_chain(path.parent / base), data)
    return data


def lookup(data: dict, concrete: str) -> Any:
    cur: Any = data
    for seg in concrete.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return KeyError
    return cur


def toml_html(
    text: str,
    builder,
    fromdoc: str,
    *,
    base: dict | None = None,
    current: dict | None = None,
    lineno0: int = 1,
) -> str:
    out = []
    table = ""
    array_table = False
    depth = 0
    for i, rawline in enumerate(text.splitlines(), start=lineno0):
        mark = ""
        stripped = rawline.strip()
        if depth > 0:
            depth += rawline.count("[") - rawline.count("]")
            out.append(f'<span class="ln">{i}</span><span class="mk"></span>{esc(rawline)}')
            continue
        if not stripped or stripped.startswith("#"):
            out.append(
                f'<span class="ln">{i}</span><span class="mk"></span><span class="c">{esc(rawline)}</span>'
            )
            continue
        h = HEADER.match(rawline)
        if h and "=" not in rawline.split("#")[0]:
            table = h.group(3).strip()
            array_table = h.group(2) == "[["
            canon = resolve(table)
            if base is not None:
                mark = (
                    "+"
                    if table.endswith("__append")
                    or (lookup(base, table.replace("__append", "")) is KeyError)
                    else ""
                )
            comment = h.group(5) or ""
            inner = esc(table)
            if canon:
                n = node(canon)
                inner = f'<a href="{esc(uri(builder, fromdoc, canon))}" title="{esc(n.get("summary") or n.get("doc") or canon)}">{esc(table)}</a>'
            out.append(
                f'<span class="ln">{i}</span><span class="mk mk-{"add" if mark == "+" else "none"}">{mark}</span>'
                f'<span class="h">{esc(h.group(1))}{esc(h.group(2))}{inner}{esc(h.group(4))}</span><span class="c">{esc(comment)}</span>'
            )
            continue
        kv = KEYLINE.match(rawline)
        if kv:
            key = kv.group(2)
            value = kv.group(4)
            comment = ""
            if " #" in value and value.count('"') % 2 == 0:
                value, comment = value.split(" #", 1)
                comment = " #" + comment
            depth = value.count("[") - value.count("]")
            concrete = f"{table}.{key}" if table else key
            canon = resolve(concrete) if key != "base_config" else None
            if base is not None and current is not None:
                if array_table or "__append" in table:
                    mark = "+" if ("__append" in table or lookup(base, table) is KeyError) else ""
                else:
                    old = lookup(base, concrete)
                    new = lookup(current, concrete)
                    mark = "+" if old is KeyError else ("~" if old != new else "")
            key_html = esc(key)
            if canon:
                n = node(canon)
                tip = (n.get("summary") or "") + (f" ({n['unit']})" if n.get("unit") else "")
                key_html = f'<a href="{esc(uri(builder, fromdoc, canon))}" title="{esc(tip)}">{esc(key)}</a>'
            elif key == "base_config":
                key_html = f'<a href="{esc(doc_uri(builder, fromdoc, "reference/parameters/grammar"))}#base-config" title="Inherit every table of another file">{esc(key)}</a>'
            vcls = (
                "s"
                if value.strip().startswith('"')
                else ("n" if re.match(r"^[-+]?[0-9.]", value.strip()) else "v")
            )
            mk_cls = {"+": "add", "~": "chg"}.get(mark, "none")
            out.append(
                f'<span class="ln">{i}</span><span class="mk mk-{mk_cls}">{mark}</span>'
                f'{esc(kv.group(1))}<span class="k">{key_html}</span>{esc(kv.group(3))}<span class="{vcls}">{esc(value)}</span><span class="c">{esc(comment)}</span>'
            )
            continue
        out.append(f'<span class="ln">{i}</span><span class="mk"></span>{esc(rawline)}')
    return '<pre class="hmp-toml">' + "\n".join(out) + "</pre>"


def excerpt(text: str, tables: list[str]) -> list[tuple[int, str]]:
    """Lines of the given tables, with the comment block right above each header."""
    lines = text.splitlines()
    keep: set[int] = set()
    current = None
    for idx, line in enumerate(lines):
        h = HEADER.match(line)
        if h and "=" not in line.split("#")[0]:
            j = idx - 1
            while j >= 0 and (lines[j].strip().startswith("#") or not lines[j].strip()):
                keep.discard(j)
                j -= 1
            current = h.group(3).strip()
            if current in tables:
                j = idx - 1
                while j >= 0 and lines[j].strip().startswith("#"):
                    keep.add(j)
                    j -= 1
        if current in tables and line.strip():
            keep.add(idx)
    return [(i + 1, lines[i]) for i in sorted(keep)]


class TomlDirective(SphinxDirective):
    """A TOML block whose keys link to their card. From a file, or inline."""

    has_content = True
    option_spec = {
        "file": directives.unchanged,
        "tables": directives.unchanged,
        "caption": directives.unchanged,
    }

    def run(self):
        builder = self.env.app.builder
        caption = self.options.get("caption", "")
        if "file" in self.options:
            path = S["example_dir"] / self.options["file"]
            text = path.read_text()
            if "tables" in self.options:
                tables = [t.strip() for t in self.options["tables"].split(",")]
                parts = []
                prev = None
                chunk: list[str] = []
                start = None
                for ln, line in excerpt(text, tables):
                    if prev is not None and ln != prev + 1:
                        parts.append(
                            toml_html("\n".join(chunk), builder, self.env.docname, lineno0=start)
                        )
                        chunk, start = [], None
                    if start is None:
                        start = ln
                    chunk.append(line)
                    prev = ln
                if chunk:
                    parts.append(
                        toml_html("\n".join(chunk), builder, self.env.docname, lineno0=start)
                    )
                body = '<div class="hmp-gap-line">...</div>'.join(parts)
            else:
                body = toml_html(text, builder, self.env.docname)
            caption = (
                caption
                or f"examples/projects/04_streamflow_intermittence_in_transient/{self.options['file']}"
            )
        else:
            body = toml_html("\n".join(self.content), builder, self.env.docname)
        cap = (
            f'<div class="hmp-toml-cap">{esc(caption)} <span class="hmp-muted">· keys link to their card</span></div>'
            if caption
            else ""
        )
        return [raw(f'<div class="hmp-toml-wrap">{cap}{body}</div>')]


class StepDirective(SphinxDirective):
    """One step of the example 04 staircase, marked against what it inherits."""

    required_arguments = 1

    def run(self):
        builder = self.env.app.builder
        path = S["example_dir"] / self.arguments[0]
        text = path.read_text()
        raw_data = tomllib.loads(text)
        base_name = raw_data.get("base_config")
        base = load_chain(path.parent / base_name) if base_name else {}
        current = load_chain(path)
        body = toml_html(
            text, builder, self.env.docname, base=base if base_name else None, current=current
        )
        legend = (
            '<div class="hmp-toml-cap"><code>'
            + esc(self.arguments[0])
            + "</code>"
            + (
                f' inherits <code>{esc(base_name)}</code> · <span class="mk-add">+</span> new · <span class="mk-chg">~</span> changed'
                if base_name
                else " · the base of the staircase"
            )
            + ' · <span class="hmp-muted">keys link to their card</span></div>'
        )
        return [raw(f'<div class="hmp-toml-wrap">{legend}{body}</div>')]


# ---------------------------------------------------------------- catalog, concepts, matrix, gates, changelog


class ChangelogDirective(SphinxDirective):
    def run(self):
        builder = self.env.app.builder
        c = S["changelog"]
        if not c:
            return [raw("<p>No changelog data.</p>")]
        parts = [f'<p class="hmp-muted">{esc(c.get("from"))} → {esc(c.get("to"))}</p>']

        def shown(path: str, value: Any) -> str:
            if value not in (None, ""):
                return str(value)
            return "required" if S["nodes"].get(path, {}).get("required") else "not set"

        moved = [it for it in c.get("changed", []) if "default" in it["changes"]]
        if moved:
            items = "".join(
                f'<li><a class="hmp-toml-ref" href="{esc(uri(builder, self.env.docname, it["path"]))}"><code>{esc(it["path"])}</code></a> '
                f"<code>{esc(shown(it['path'], it['changes']['default'][0]))}</code> → "
                f"<code>{esc(shown(it['path'], it['changes']['default'][1]))}</code></li>"
                for it in moved
            )
            parts.append(
                '<div class="admonition important"><p class="admonition-title">Defaults that changed</p>'
                f"<p>{len(moved)} default value(s) changed. A file that does not write these keys gets a different run.</p>"
                f"<ul>{items}</ul></div>"
            )

        def link(p: str) -> str:
            if p in S["nodes"]:
                return f'<a class="hmp-toml-ref" href="{esc(uri(builder, self.env.docname, p))}"><code>{esc(p)}</code></a>'
            return f"<code>{esc(p)}</code>"

        for key, title in (("added", "Added"), ("removed", "Removed"), ("changed", "Changed")):
            items = c.get(key, [])
            if not items:
                continue
            parts.append(
                f"<h3>{title} <span class='hmp-muted'>({len(items)})</span></h3><ul class='hmp-changes'>"
            )
            for it in items[:400]:
                if isinstance(it, dict):
                    detail = "; ".join(
                        f"{esc(k)}: <code>{esc(shown(it['path'], v[0]) if k == 'default' else v[0])}</code>"
                        f" → <code>{esc(shown(it['path'], v[1]) if k == 'default' else v[1])}</code>"
                        for k, v in it["changes"].items()
                    )
                    parts.append(f"<li>{link(it['path'])} {detail}</li>")
                else:
                    parts.append(f"<li>{link(it)}</li>")
            parts.append("</ul>")
        return [raw("".join(parts))]


class ResolvedDirective(SphinxDirective):
    """The card of one key, with the value an example file gives it and the line.

    The value is followed through the ``base_config`` chain of the file.
    """

    required_arguments = 1
    option_spec = {"config": directives.unchanged}

    def run(self):
        from hmp_card import render_text

        cfg = self.options.get("config")
        cfg_path = S["example_dir"] / cfg if cfg else None
        text = render_text(self.arguments[0], S, cfg_path)
        head = f"{self.arguments[0]}" + (f" in {cfg}" if cfg else "")
        return [
            raw(
                f'<div class="hmp-resolved"><div class="hmp-resolved-h"><code>{esc(head)}</code></div>'
                f'<pre class="hmp-term">{esc(text)}</pre></div>'
            )
        ]


# ---------------------------------------------------------------- page generation


def write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def heading(level: int, text: str) -> str:
    return "#" * min(level, 6) + " " + text


def title_of(path: str) -> str:
    n = node(path)
    shown = path
    if n.get("kind") == "array":
        return f"`[[{shown}]]`"
    return f"`[{shown}]`"


# ---------------------------------------------------------------- role


def toml_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    env = inliner.document.settings.env
    builder = env.app.builder
    title, target = text.split("|", 1) if "|" in text else (text, text)
    title, target = title.strip(), target.strip()
    canon = resolve(target)
    if canon is None:
        logger.warning(f"[hmp] unknown TOML path {target!r}", location=(env.docname, lineno))
        return [nodes.literal(rawtext, title, classes=["hmp-broken"])], []
    n = node(canon)
    tip = (n.get("summary") or n.get("doc") or "") + (f" ({n['unit']})" if n.get("unit") else "")
    ref = nodes.reference(
        rawtext, "", refuri=uri(builder, env.docname, canon), reftitle=tip, classes=["hmp-toml-ref"]
    )
    ref += nodes.literal(title, title)
    return [ref], []


# ---------------------------------------------------------------- setup


def on_builder_inited(app: Sphinx) -> None:
    """Write the data files from the code, then the generated pages.

    ``HMP_SKIP_DOC_DATA=1`` reuses the data files of the previous build.
    """
    import os

    data = Path(app.srcdir) / "_data"
    if os.environ.get("HMP_SKIP_DOC_DATA") != "1" or not (data / "registry.json").exists():
        from tools.docs.data import write_all

        write_all(data, label=app.config.release)
    load_state(app)
    import hmp_api
    import hmp_tview

    hmp_tview.gen_pages(Path(app.srcdir))
    hmp_api.gen_pages(Path(app.srcdir))


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_config_value("hmp_example_dir", "", "env")
    app.connect("builder-inited", on_builder_inited)
    app.add_role("toml", toml_role)
    app.add_directive("hmp-anchor", AnchorDirective)
    app.add_directive("hmp-intro", IntroDirective)
    app.add_directive("hmp-index", IndexDirective)
    app.add_directive("hmp-known-keys", KnownKeysDirective)
    app.add_directive("hmp-toml", TomlDirective)
    app.add_directive("hmp-step", StepDirective)
    app.add_directive("hmp-changelog", ChangelogDirective)
    app.add_directive("hmp-resolved", ResolvedDirective)
    import hmp_api
    import hmp_catalogs
    import hmp_tview
    import hmp_validation

    hmp_tview.setup_tview(app)
    hmp_api.setup_api(app)
    hmp_validation.setup_validation(app)
    hmp_catalogs.setup_catalogs(app)
    app.add_css_file("hmp.css")
    app.add_js_file("hmp.js")
    return {"version": "0.1", "parallel_read_safe": True, "parallel_write_safe": True}
