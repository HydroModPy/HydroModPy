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

SNAPSHOTS = Path(__file__).resolve().parents[3] / "tools" / "docs" / "snapshots"

# BuildEnvironment.app is deprecated since Sphinx 9 (removed in 11): the
# application is kept here by setup() and every directive asks for the builder.
_APP: Sphinx | None = None


def current_builder():
    """The builder of the running Sphinx application."""
    return _APP.builder


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
    for name in ("gates",):
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
    for file in S["meta"].get("files", {}).values():
        for root in file["roots"]:
            pages[root] = file["page"]
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


def static_uri(builder, fromdoc: str, name: str) -> str:
    """Relative link from a page to a file of ``_static``."""
    to_root = builder.get_relative_uri(fromdoc, "index")
    prefix = to_root.rsplit("/", 1)[0] + "/" if "/" in to_root else ""
    return f"{prefix}_static/{name}"


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
    lo_n, hi_n = rng.get("min_length"), rng.get("max_length")
    if lo_n is not None and lo_n == hi_n:
        return f"exactly {lo_n} item{'s' if lo_n != 1 else ''}"
    parts = []
    if lo_n is not None:
        parts.append(f"at least {lo_n} item{'s' if lo_n != 1 else ''}")
    if hi_n is not None:
        parts.append(f"at most {hi_n} item{'s' if hi_n != 1 else ''}")
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


def when_text(n: dict[str, Any]) -> str:
    """The condition under which a key is read: its shape, or a declared VisibleWhen."""
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
    return " and ".join(parts)


# ---------------------------------------------------------------- copy buttons

ICON_COPY = (
    '<svg class="hmp-ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>'
)
ICON_LINK = (
    '<svg class="hmp-ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/>'
    '<path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>'
)


def copy_button(label: str, *, text: str | None = None, anchor: str | None = None) -> str:
    """One icon button. It copies ``text``, or the URL of the page with ``#anchor``."""
    data = f' data-copy="{esc(text)}"' if text is not None else f' data-anchor="{esc(anchor)}"'
    icon = ICON_COPY if text is not None else ICON_LINK
    return (
        f'<button class="hmp-copy" type="button"{data} aria-label="{esc(label)}" '
        f'title="{esc(label)}">{icon}</button>'
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


_TOML_LINK = re.compile(r'<a class="hmp-toml-ref[^"]*" href="([^"]*)"[^>]*>(.*?)</a>', re.S)


def summary_md(text: str, builder, fromdoc: str) -> str:
    """Like ``inline_md``, for the inside of a ``<summary>``, where a link is not allowed.

    A link inside a ``<summary>`` is an interactive element nested in another one:
    a screen reader cannot tell what a click does. The path stays visible as text;
    ``render_card`` lists the links again under the line (row "See").
    """
    return _TOML_LINK.sub(
        r'<span class="hmp-toml-ref">\2</span>', inline_md(text, builder, fromdoc)
    )


def summary_links(text: str, builder, fromdoc: str) -> list[tuple[str, str]]:
    """The links ``inline_md`` writes in a text, as (href, label html), without repeats."""
    seen: dict[str, str] = {}
    for href, label in _TOML_LINK.findall(inline_md(text, builder, fromdoc)):
        seen.setdefault(href, label)
    return list(seen.items())


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
    for file in S["meta"].get("files", {}).values():
        roots.update(file["roots"])
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


def rest_of_description(n: dict[str, Any]) -> str:
    """What the description says beyond the summary line shown above the card."""
    desc = (n.get("description") or "").strip()
    summary = (n.get("summary") or "").strip()
    if not summary:
        return desc
    i = j = 0
    while j < len(summary):
        if i >= len(desc):
            return desc
        if desc[i] == summary[j]:
            i, j = i + 1, j + 1
        elif desc[i].isspace():
            i += 1
        elif summary[j].isspace():
            j += 1
        else:
            return desc
    return desc[i:].strip()


def unexplained(n: dict[str, Any]) -> set[str]:
    """Values of a choice that neither value_docs nor the description explains."""
    docs = n.get("value_docs") or {}
    text = n.get("description") or ""
    out = set()
    for v in n.get("literal") or []:
        if str(v) in docs or re.search(rf"[`'\"]{re.escape(str(v))}[`'\"]", text):
            continue
        out.add(str(v))
    return out


def render_card(builder, fromdoc: str, path: str, n: dict, line_text: str | None = None) -> str:
    """The card under a key line: what the line itself cannot say.

    ``line_text`` is the text the line shows when it is not the summary of the key.
    """
    rows = []

    def add(label: str, value: str) -> None:
        if value:
            rows.append(f"<dt>{label}</dt><dd>{value}</dd>")

    anchor = anchor_of(path)
    add(
        "Path",
        f'<code class="hmp-path">{esc(path)}</code> '
        + copy_button("Copy the path", text=path)
        + copy_button("Copy a link to this key", anchor=anchor),
    )
    rest = rest_of_description(n)
    if rest:
        add("More", block_md(rest, builder, fromdoc))
    shown = (n.get("summary") or "") if line_text is None else line_text
    links = summary_links(shown, builder, fromdoc)
    if links:
        add(
            "See",
            ", ".join(
                f'<a class="hmp-toml-ref" href="{esc(href)}">{label}</a>' for href, label in links
            ),
        )
    lits = n.get("literal", [])
    vdocs = n.get("value_docs", {})
    if lits:
        missing = unexplained(n)
        items = []
        for v in lits:
            doc = vdocs.get(str(v))
            note = (
                f" : {inline_md(doc, builder, fromdoc)}"
                if doc
                else (' <span class="hmp-muted">no explanation</span>' if str(v) in missing else "")
            )
            items.append(f"<li><code>{esc(json.dumps(v))}</code>{note}</li>")
        add("Values", f'<ul class="hmp-values">{"".join(items)}</ul>')
    if n.get("kind") == "leaf":
        accepted = esc(n.get("form", ""))
        if n.get("quantity"):
            accepted += (
                ' <span class="hmp-muted">(a bare number is read in the canonical unit)</span>'
            )
        add("Accepted", accepted)
    rng = range_text(n.get("range", {}))
    if rng:
        add("Valid range", f'{esc(rng)} <span class="hmp-muted">(refused outside)</span>')
    if n.get("unit") and not (n["unit"] == "-" and not n.get("numeric")):
        add("Unit", esc(n.get("unit")))
    examples = n.get("examples") or []
    if examples:
        add("Example", ", ".join(f"<code>{esc(e)}</code>" for e in examples[:3]))
    cal = n.get("calibrable")
    if cal:
        bounds_link = uri(builder, fromdoc, "calibration.parameters.<name>.bounds")
        txt = f"yes, search space {esc(cal.get('transform'))}, prior {esc(cal.get('prior'))}"
        if cal.get("bounds"):
            txt += f", default bounds {esc(cal['bounds'])}"
        else:
            txt += (
                f', bounds belong to the site: write them in <a class="hmp-toml-ref" '
                f'href="{esc(bounds_link)}"><code>calibration.parameters.&lt;name&gt;.bounds</code></a>'
            )
        if n.get("pseudo") and rng:
            txt += f"; the valid range {esc(rng)} caps them"
        add("Calibration", txt)
    add("Only if", when_text(n))
    if n.get("kind") != "leaf" and n.get("variants_detail"):
        add(
            "Shapes",
            ", ".join(f"<code>{esc(json.dumps(v['value']))}</code>" for v in n["variants_detail"]),
        )
    if n.get("instance_of"):
        add(
            "Same as",
            f'<a class="hmp-toml-ref" href="{esc(uri(builder, fromdoc, n["instance_of"]))}">'
            f"<code>{esc(n['instance_of'])}</code></a>, with the unit and range of "
            f"<code>{esc(path.split('.')[2])}</code>",
        )
    if n.get("renamed_from"):
        add("Was", ", ".join(f"<code>{esc(p)}</code>" for p in n["renamed_from"]))
    return f'<div class="hmp-card"><dl>{"".join(rows)}</dl></div>'


def sort_key(path: str) -> tuple:
    n = node(path)
    return (0 if n.get("required") else 1, PROFILE_RANK.get(n.get("profile", "user"), 0))


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
    """Intro of a table: its docstring, then what to write, in a few lines."""

    required_arguments = 1

    def run(self):
        path = self.arguments[0]
        n = node(path)
        builder = current_builder()
        doc = self.env.docname
        sub = [p for p in subtree(path) if node(p).get("kind") == "leaf"]
        user = sum(1 for p in sub if node(p).get("profile") == "user")
        text = n.get("doc") or n.get("description") or ""
        intro = block_md(text, builder, doc)
        facts = [
            f"<li><code>{esc(path)}</code> <span class='hmp-muted'>{esc(table_form(n))}</span>"
            f" · {'required in every file' if n.get('required') else 'optional'}"
            f" · {user} user key{'s' if user != 1 else ''}"
            + (f", {len(sub) - user} dev or expert" if len(sub) > user else "")
            + "</li>"
        ]
        if "." not in path:
            minimal = doc_uri(builder, doc, "reference/parameters/minimal-files")
            template = static_uri(builder, doc, f"templates/{path}.toml")
            facts.append(
                f"<li>Start a file: <code>hmp config template --modules {esc(path)}</code> "
                f'(<a href="{esc(template)}" download>download it</a>), '
                f"then <code>hmp config check file.toml</code>. "
                f'<a href="{esc(minimal)}#min-{esc(path)}">Minimal file</a></li>'
            )
        adv = len(sub) > user
        switch = ADV_SWITCH if adv else ""
        return [
            raw(
                f'<div class="hmp-intro">{intro}<ul class="hmp-facts">{"".join(facts)}</ul>'
                f"{switch}</div>"
            )
        ]


ADV_SWITCH = (
    '<button class="hmp-adv-switch" type="button" aria-pressed="false">'
    '<span class="hmp-adv-off">Show dev and expert keys</span>'
    '<span class="hmp-adv-on">Hide dev and expert keys</span></button>'
)


class KnownKeysDirective(SphinxDirective):
    """The names of a free-key table the code knows (flow.param.<id>), with unit and range."""

    required_arguments = 1
    option_spec = {"variant": directives.unchanged}

    def run(self):
        builder = current_builder()
        doc = self.env.docname
        path = self.arguments[0]
        known = node(path).get("known_keys", {})
        rows = []
        unit_only = []
        for key, info in known.items():
            if info.get("alias_of"):
                continue
            if not info.get("paths"):
                unit_only.append(f"<code>{esc(key)}</code> ({esc(info.get('unit'))})")
                continue
            table_path, value_path = info["paths"]
            vn = node(value_path)
            phys = info["physical"]
            aliases = info.get("aliases") or []
            label = (info.get("label") or "").capitalize()
            rows.append(
                f'<tr id="{anchor_of(table_path)}"><td><a class="hmp-toml-ref" '
                f'href="{esc(uri(builder, doc, value_path))}"><code>[flow.param.{esc(key)}]</code></a>'
                + (
                    f' <span class="hmp-muted">or {", ".join(f"<code>{esc(a)}</code>" for a in aliases)}</span>'
                    if aliases
                    else ""
                )
                + f"</td><td>{esc(label)}</td><td>{esc(info.get('unit'))}</td>"
                f"<td>{fmt_num(phys[0])} .. {fmt_num(phys[1])} {esc((info.get('physical_unit') or '').strip('-'))}</td></tr>"
            )
            rows.append(
                f'<tr class="hmp-known-card"><td colspan="4">'
                f'<details class="tl" id="{anchor_of(value_path)}"><summary><span class="tl-code">'
                f'<span class="k">value</span><span class="eq"> = </span>'
                f'<span class="ph">‹{esc(vn.get("form", ""))}›</span></span>'
                f'<span class="tl-note"><span class="tl-sum">{summary_md(vn.get("summary", ""), builder, doc)}</span></span>'
                f"</summary>{render_card(builder, doc, value_path, vn)}</details></td></tr>"
            )
        table = (
            '<div class="hmp-matrix-wrap"><table class="hmp-known"><thead><tr><th>Table</th> '
            # The spaces keep Pagefind from running the header cells into one word.
            "<th>Quantity</th> <th>Unit</th> <th>Valid range (refused outside)</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )
        if unit_only:
            table += (
                f"<p>The code also gives a default unit to {', '.join(unit_only)}, "
                "with no range check.</p>"
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
        builder = current_builder()
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
        builder = current_builder()
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


def resolved_toml_diff(older: Path, newer: Path, context: int = 1) -> str:
    """Unified diff of two example files, each resolved through the real loader.

    Both files go through ``load_toml_with_base_config`` (the ``base_config`` chain
    and the merge rules of the loader), then are written back as TOML with the keys
    in the order the loader returns them, so the diff shows what a run would read.
    There is no fallback loader: a file the loader refuses fails the build.
    """
    import difflib

    import tomli_w

    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    def dump(path: Path) -> list[str]:
        return tomli_w.dumps(load_toml_with_base_config(path)).splitlines()

    lines = difflib.unified_diff(
        dump(older), dump(newer), older.stem, newer.stem, n=context, lineterm=""
    )
    return "\n".join(lines)


def base_chain(path: Path) -> list[Path]:
    """The file and every ``base_config`` it inherits, so a build rereads them when one changes."""
    chain = [path]
    base = tomllib.loads(path.read_text()).get("base_config")
    if base:
        chain += base_chain((path.parent / base).resolve())
    return chain


class TomlDiffDirective(SphinxDirective):
    """What a file of the example changes against another, both resolved by the loader.

    ``{hmp-toml-diff} older.toml newer.toml``. A line starting with ``-`` is what the
    older file resolves to, ``+`` what the newer one resolves to. The diff is
    computed at build time, so it follows the files and cannot drift from them.
    """

    required_arguments = 2
    option_spec = {"context": directives.nonnegative_int}

    def run(self):
        older, newer = (S["example_dir"] / name for name in self.arguments)
        for path in (*base_chain(older), *base_chain(newer)):
            self.env.note_dependency(str(path))
        diff = resolved_toml_diff(older, newer, self.options.get("context", 1))
        if not diff:
            return [
                nodes.paragraph(text=f"{newer.name} resolves to the same file as {older.name}.")
            ]
        block = nodes.literal_block(diff, diff)
        block["language"] = "diff"
        block["force"] = True
        return [block]


# ---------------------------------------------------------------- catalog, concepts, matrix, gates, changelog


CURRENT = "current"


def version_history() -> dict[str, Any]:
    """Diffs between every released snapshot and the fields of this tree."""
    if "history" not in S:
        from packaging.version import Version

        from tools.docs import toml_changelog

        snaps = sorted(
            SNAPSHOTS.glob("fields-*.json"),
            key=lambda p: Version(p.stem.removeprefix("fields-")),
        )
        docs = [json.loads(p.read_text()) for p in snaps]
        current = toml_changelog.snapshot({"meta": {"label": CURRENT}, "nodes": S["nodes"]})
        S["history"] = toml_changelog.history([*docs, current])
    return S["history"]


def version_name(label: str) -> str:
    return "this documentation" if label == CURRENT else label


class ChangelogDirective(SphinxDirective):
    """Keys added, renamed, removed and changed between two versions, both chosen by the reader.

    Every pair is rendered; the page shows the newest release against this tree,
    and a script swaps the pair when the reader picks two other versions.
    """

    def run(self):
        builder = current_builder()
        doc = self.env.docname
        hist = version_history()
        versions = hist["versions"]
        if len(versions) < 2:
            return [raw("<p>No released version to compare with.</p>")]

        def shown(path: str, value: Any) -> str:
            if value not in (None, ""):
                return str(value)
            return "required" if S["nodes"].get(path, {}).get("required") else "not set"

        def link(p: str) -> str:
            if p in S["nodes"]:
                return f'<a class="hmp-toml-ref" href="{esc(uri(builder, doc, p))}"><code>{esc(p)}</code></a>'
            return f"<code>{esc(p)}</code>"

        def by_section(items: list, key) -> str:
            groups: dict[str, list[str]] = {}
            for it in items:
                groups.setdefault(key(it).split(".")[0], []).append(it)
            out = []
            for sec in sorted(groups):
                out.append(f'<li class="hmp-ch-sec"><code>[{esc(sec)}]</code><ul>')
                out.extend(render(it) for it in groups[sec])
                out.append("</ul></li>")
            return "".join(out)

        from tools.docs import legacy_keys

        reads = legacy_keys.accepted_old_names(S["nodes"])
        STILL = {
            legacy_keys.WARNS: "still loads; ConfigKeyRenamedWarning names the new key",
            legacy_keys.MIGRATES: "still loads; the loader rewrites or drops it on load",
        }

        def rename_note(c: dict) -> str:
            """What the loader does with an old name, read from the loader (legacy_keys)."""
            if c["to"] != CURRENT:
                return "Write the new name"
            kinds = {reads.get(it["from"]) for it in c["renamed"]}
            if kinds == {None}:
                return "A file that writes the old name is refused"
            if None in kinds:
                return (
                    "A file that writes an old name is refused, unless its line says it still loads"
                )
            return (
                "A file that writes an old name still loads, as each line says. Write the new name"
            )

        def removal_note(c: dict) -> str:
            """What the loader does with a removed key, read from the loader (legacy_keys)."""
            if c["to"] != CURRENT:
                return "a file that writes them is refused"
            kinds = {reads.get(p) for p in c["removed"]}
            if kinds == {None}:
                return "a file that writes them is refused"
            if None in kinds:
                return (
                    "a file that writes one of them is refused, unless its line says it still loads"
                )
            return "a file that writes them still loads, as each line says"

        loader = {"reads": {}}

        def render_pair(c: dict) -> str:
            loader["reads"] = reads if c["to"] == CURRENT else {}
            parts = []
            moved = [it for it in c["changed"] if "default" in it["changes"]]
            if moved:
                items = "".join(
                    f"<li>{link(it['path'])} "
                    f"<code>{esc(shown(it['path'], it['changes']['default'][0]))}</code> to "
                    f"<code>{esc(shown(it['path'], it['changes']['default'][1]))}</code></li>"
                    for it in moved
                )
                parts.append(
                    '<div class="admonition important"><p class="admonition-title">Defaults that changed</p>'
                    f"<p>A file that does not write these keys gets a different run.</p><ul>{items}</ul></div>"
                )
            blocks = (
                ("renamed", "Renamed", rename_note(c)),
                ("removed", "Removed", removal_note(c)),
                ("added", "Added", ""),
                ("changed", "Changed", ""),
            )
            for key, title, note in blocks:
                items = c.get(key, [])
                if not items:
                    continue
                breaking = (
                    key == "removed" and any(it not in loader["reads"] for it in items)
                ) or (key == "renamed" and any(it["from"] not in loader["reads"] for it in items))
                parts.append(
                    f'<h2 class="hmp-ch-h">{title} <span class="hmp-muted">({len(items)})</span>'
                    + (' <span class="tc tc-req">breaking</span>' if breaking else "")
                    + "</h2>"
                    + (
                        f'<p class="hmp-muted">{esc(note[:1].upper() + note[1:])}.</p>'
                        if note
                        else ""
                    )
                    + '<ul class="hmp-changes">'
                )
                parts.append(by_section(items, change_path))
                parts.append("</ul>")
            if not parts:
                parts.append("<p>No key changed between these two versions.</p>")
            return "".join(parts)

        def change_path(it) -> str:
            if isinstance(it, dict):
                return it.get("from") or it["path"]
            return it

        def render(it) -> str:
            if isinstance(it, dict) and "from" in it:
                kind = loader["reads"].get(it["from"])
                still = f' <span class="hmp-muted">({STILL[kind]})</span>' if kind in STILL else ""
                return f"<li><code>{esc(it['from'])}</code> is now {link(it['to'])}{still}</li>"
            if isinstance(it, dict):
                detail = "; ".join(
                    f"{esc(k)}: <code>{esc(shown(it['path'], v[0]) if k == 'default' else v[0])}</code>"
                    f" to <code>{esc(shown(it['path'], v[1]) if k == 'default' else v[1])}</code>"
                    for k, v in it["changes"].items()
                )
                return f"<li>{link(it['path'])} {detail}</li>"
            kind = loader["reads"].get(it)
            still = f' <span class="hmp-muted">({STILL[kind]})</span>' if kind in STILL else ""
            return f"<li>{link(it)}{still}</li>"

        default = (versions[-2], versions[-1])
        sections = []
        for c in hist["pairs"]:
            pair = (c["from"], c["to"])
            hidden = "" if pair == default else " hidden"
            sections.append(
                f'<section class="hmp-ch-pair" data-from="{esc(c["from"])}" data-to="{esc(c["to"])}"{hidden}>'
                f"{render_pair(c)}</section>"
            )

        def select(name: str, choices: list[str], chosen: str) -> str:
            opts = "".join(
                f'<option value="{esc(v)}"{" selected" if v == chosen else ""}>{esc(version_name(v))}</option>'
                for v in choices
            )
            return f'<label>{name} <select class="hmp-ch-{name.lower()}">{opts}</select></label>'

        form = (
            '<form class="hmp-ch-form" hidden>'
            + select("From", versions[:-1], default[0])
            + select("To", versions[1:], default[1])
            + '<span class="hmp-ch-same hmp-muted" hidden>Pick a newer version on the right.</span>'
            + "</form>"
        )
        lead = (
            f'<p class="hmp-ch-lead">From <b>{esc(version_name(default[0]))}</b> to '
            f"<b>{esc(version_name(default[1]))}</b>.</p>"
        )
        return [raw(f'<div class="hmp-changelog">{form}{lead}{"".join(sections)}</div>')]


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
    builder = current_builder()
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


RELIABLE_UNITS = {"type", "metadata", "name", "known"}


def shown_unit(n: dict[str, Any]) -> str | None:
    """The unit a page shows: declared by the code, and not "-" on a non-number."""
    unit = n.get("unit")
    if not unit or n.get("unit_source", "known") not in RELIABLE_UNITS:
        return None
    if unit == "-" and not n.get("numeric"):
        return None
    return unit


def keys_payload(builder) -> list[dict[str, Any]]:
    """One entry per path, for the explorer search and the hover cards of {toml} links.

    Short keys keep the file small: p path, n name, t kind, s summary, u unit,
    f form, d default, r required, a profile when not user, l label of a named
    instance, w where its card is, x the rest of the text a search may match.
    """
    out = []
    for path, n in S["nodes"].items():
        doc = S["home"].get(path)
        if not path or not doc:
            continue
        leaf = n.get("kind") == "leaf"
        item: dict[str, Any] = {
            "p": path,
            "n": n.get("name", ""),
            "t": "l" if leaf else n.get("kind", "table")[0],
            "s": clean_rst(n.get("summary") or n.get("doc") or ""),
            "w": f"{builder.get_target_uri(doc)}#{anchor_of(path)}",
        }
        unit = shown_unit(n)
        if unit:
            item["u"] = unit
        item["f"] = n.get("form", "") if leaf else table_form(n)
        if n.get("required"):
            item["r"] = 1
        elif leaf and n.get("default") not in (None, "not set", "(computed)"):
            item["d"] = n["default"]
        if n.get("profile", "user") != "user":
            item["a"] = n["profile"]
        if n.get("label"):
            item["l"] = n["label"]
        extra = [
            rest_of_description(n),
            " ".join(str(v) for v in n.get("literal", [])),
            " ".join(f"{k} {v}" for k, v in (n.get("value_docs") or {}).items()),
            " ".join(n.get("examples") or []),
        ]
        text = clean_rst(" ".join(" ".join(e.split()) for e in extra if e))
        if text:
            item["x"] = text
        out.append(item)
    return out


def on_build_finished(app: Sphinx, exception: Exception | None) -> None:
    """Write the keys file next to the static files of the HTML site."""
    if exception is not None or getattr(app.builder, "format", "") != "html" or "nodes" not in S:
        return
    out = Path(app.outdir) / "_static" / "hmp-keys.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(keys_payload(app.builder), ensure_ascii=False, separators=(",", ":")))
    write_templates(Path(app.outdir) / "_static" / "templates")


def write_templates(folder: Path) -> None:
    """The file ``hmp config template --modules <section>`` writes, one per section."""
    from hydromodpy.core.toml_io.generator import available_modules, generate_toml

    folder.mkdir(parents=True, exist_ok=True)
    for module in available_modules():
        text = generate_toml(output_path=None, modules=[module], profile="user")
        (folder / f"{module}.toml").write_text(text)


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
    global _APP
    _APP = app
    app.add_config_value("hmp_example_dir", "", "env")
    app.connect("builder-inited", on_builder_inited)
    app.connect("build-finished", on_build_finished)
    app.add_role("toml", toml_role)
    app.add_directive("hmp-anchor", AnchorDirective)
    app.add_directive("hmp-intro", IntroDirective)
    app.add_directive("hmp-index", IndexDirective)
    app.add_directive("hmp-known-keys", KnownKeysDirective)
    app.add_directive("hmp-toml", TomlDirective)
    app.add_directive("hmp-step", StepDirective)
    app.add_directive("hmp-toml-diff", TomlDiffDirective)
    app.add_directive("hmp-changelog", ChangelogDirective)
    app.add_directive("hmp-resolved", ResolvedDirective)
    import hmp_api
    import hmp_calibration
    import hmp_catalogs
    import hmp_tview
    import hmp_validation

    hmp_tview.setup_tview(app)
    hmp_api.setup_api(app)
    hmp_validation.setup_validation(app)
    hmp_catalogs.setup_catalogs(app)
    hmp_calibration.setup_calibration(app)
    app.add_css_file("hmp.css")
    app.add_js_file("hmp.js", defer="defer")
    return {"version": "0.2", "parallel_read_safe": True, "parallel_write_safe": True}
