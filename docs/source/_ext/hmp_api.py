"""Python API and command-line reference, generated from the package.

Pages come from ``_data/api.json`` (built by ``tools/api_registry.py`` from
``hydromodpy.__all__``, the signatures, the docstrings, the argparse parser of
``hmp`` and the exit codes of the CLI). Docstrings are rendered by autodoc and
napoleon. No text is written beside the code: the sentences below are templates.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import hmp_params as H
from docutils.parsers.rst import directives
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective
from sphinx.util.nodes import make_refnode

logger = logging.getLogger(__name__)

PY = "reference/python"
CLI = "reference/cli"
A: dict = {}


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def load(srcdir: Path) -> None:
    path = srcdir / "_data/api.json"
    A.clear()
    if path.exists():
        A.update(json.loads(path.read_text()))


def verb_doc(name: str) -> str:
    return f"{PY}/hmp-{name}"


def class_doc(name: str) -> str:
    return f"{PY}/{name}"


def command_doc(top: str) -> str:
    return f"{CLI}/{top}"


def classes(*kinds: str) -> list[dict]:
    return [c for c in A.get("classes", []) if c["kind"] in kinds]


def cli_users_of(verb: str) -> list[str]:
    return [cmd for cmd, verbs in A.get("cli_to_verbs", {}).items() if verb in verbs]


def command(path: list[str]) -> dict:
    return next((c for c in A.get("commands", []) if c["path"] == path), {})


def returns_html(v: dict, b, doc: str) -> str:
    if not v["returns"]:
        # No documented class or alias: the annotation as written, when it says something.
        ann = v.get("annotation", "")
        if ann in ("", "Any"):
            return '<span class="hmp-gap">no return type</span>'
        return f"<code>{esc(ann)}</code>"
    parts = []
    for r in v["returns"]:
        if "qualname" in r:
            parts.append(
                f'<a href="{esc(H.doc_uri(b, doc, class_doc(r["name"])))}"><code>{esc(r["name"])}</code></a>'
            )
        else:
            parts.append(
                f'<code title="{esc(r["alias"])}">{esc(r["name"])}</code> <span class="hmp-muted">({esc(r["alias"])})</span>'
            )
    return ", ".join(parts)


def users_html(verb: str, b, doc: str) -> str:
    users = cli_users_of(verb)
    if not users:
        return '<span class="hmp-muted">none found</span>'
    return ", ".join(
        f'<a href="{esc(H.doc_uri(b, doc, command_doc(c)))}"><code>hmp {esc(c)}</code></a>'
        for c in users
    )


# ---------------------------------------------------------------- Python directives


class VerbsDirective(SphinxDirective):
    def run(self):
        b, doc = H.current_builder(), self.env.docname
        rows = "".join(
            f'<tr><td><a href="{esc(H.doc_uri(b, doc, verb_doc(v["name"])))}"><code>hmp.{esc(v["name"])}()</code></a></td>'
            f"<td>{H.inline_md(v['summary'], b, doc)}</td><td>{returns_html(v, b, doc)}</td><td>{users_html(v['name'], b, doc)}</td></tr>"
            for v in sorted(A.get("verbs", []), key=lambda v: v["name"])
        )
        return [
            H.raw(
                '<div class="hmp-matrix-wrap"><table class="api-t"><thead><tr><th>Function</th><th>What it does</th>'
                f"<th>Returns</th><th>Used by</th></tr></thead><tbody>{rows}</tbody></table></div>"
            )
        ]


class ObjectsDirective(SphinxDirective):
    option_spec = {"kind": directives.unchanged}

    def run(self):
        b, doc = H.current_builder(), self.env.docname
        kind = self.options.get("kind", "result")
        cards = "".join(
            H.card(
                H.doc_uri(b, doc, class_doc(c["name"])),
                c["name"],
                H.inline_md(c["summary"], b, doc) or '<span class="hmp-gap">no docstring</span>',
                f"{len(c.get('members', []))} public members",
            )
            for c in classes(kind)
        )
        return [H.raw(f'<div class="sec-grid">{cards}</div>')]


class ConfigsDirective(SphinxDirective):
    def run(self):
        b, doc = H.current_builder(), self.env.docname
        kinds = A.get("toml_kinds", {})
        rows = []
        for c in sorted(classes("config"), key=lambda c: (c.get("toml") or ["~"])[0]):
            if c["name"] == "HydroModPyConfig":
                links = '<span class="hmp-muted">the whole file</span>'
            else:
                links = (
                    " ".join(
                        f'<a class="hmp-toml-ref" href="{esc(H.uri(b, doc, p))}"><code>{"[[" if kinds.get(p) == "array" else "["}{esc(p)}{"]]" if kinds.get(p) == "array" else "]"}</code></a>'
                        for p in c.get("toml", [])
                    )
                    or '<span class="hmp-muted">not reached from a TOML file</span>'
                )
            tags = " ".join(
                f"<code>{esc(k)} = {esc(json.dumps(v))}</code>"
                for k, v in (c.get("tags") or {}).items()
            )
            rows.append(
                f"<tr><td><code>{esc(c['name'])}</code></td><td>{links}</td><td>{tags}</td><td>{H.inline_md(c['summary'], b, doc)}</td></tr>"
            )
        return [
            H.raw(
                '<div class="hmp-matrix-wrap"><table class="api-t"><thead><tr><th>Class</th><th>TOML section</th>'
                "<th>Selected by</th><th>Docstring</th></tr></thead><tbody>"
                + "".join(rows)
                + "</tbody></table></div>"
            )
        ]


class ModulesDirective(SphinxDirective):
    def run(self):
        b, doc = H.current_builder(), self.env.docname
        rows = "".join(
            f"<tr><td><code>hmp.{esc(m['name'])}</code></td><td>{H.inline_md(m['summary'] or '', b, doc) or '<span class=hmp-gap>no docstring</span>'}</td></tr>"
            for m in A.get("modules", [])
        )
        return [
            H.raw(
                f'<table class="api-t"><thead><tr><th>Module</th><th>Docstring</th></tr></thead><tbody>{rows}</tbody></table>'
            )
        ]


class GapsDirective(SphinxDirective):
    def run(self):
        verbs = A.get("verbs", [])
        items = []
        for sec in ("Parameters", "Returns", "Examples"):
            missing = [v["name"] for v in verbs if sec not in v["sections"]]
            if missing:
                items.append(
                    f"<li>{len(missing)} function(s) without a <b>{esc(sec)}</b> section: {', '.join(f'<code>{esc(x)}</code>' for x in missing)}</li>"
                )
        nodoc = [c["name"] for c in classes("result", "engine") if not c["summary"]]
        if nodoc:
            items.append(
                f"<li>{len(nodoc)} class(es) without a docstring: {', '.join(f'<code>{esc(x)}</code>' for x in nodoc)}</li>"
            )
        undoc = sum(
            1
            for c in classes("result")
            for m in c.get("members", [])
            if m["kind"] != "attribute" and not m["summary"]
        )
        if undoc:
            items.append(
                f"<li>{undoc} method(s) or propertie(s) of the returned objects without a docstring</li>"
            )
        mods = [m["name"] for m in A.get("modules", []) if not m["summary"]]
        if mods:
            items.append(
                f"<li>{len(mods)} module(s) without a docstring: {', '.join(f'<code>{esc(x)}</code>' for x in mods)}</li>"
            )
        nohelp = sum(1 for c in A.get("commands", []) for a in c["arguments"] if not a["help"])
        if nohelp:
            items.append(f"<li>{nohelp} command-line argument(s) without a help string</li>")
        if not items:
            return []
        return [
            H.raw(
                f'<div class="hmp-links"><div class="hmp-links-h">Gaps in the docstrings and help strings</div><ul>{"".join(items)}</ul></div>'
            )
        ]


class TwinDirective(SphinxDirective):
    required_arguments = 1

    def run(self):
        b, doc = H.current_builder(), self.env.docname
        v = next((x for x in A.get("verbs", []) if x["name"] == self.arguments[0]), None)
        if v is None:
            return []
        rows = [f"<li><b>Used by</b> {users_html(v['name'], b, doc)}</li>"]
        if v["returns"]:
            rows.append(f"<li><b>Returns</b> {returns_html(v, b, doc)}</li>")
        if v.get("source"):
            rows.append(
                f"<li><b>Defined in</b> <code>{esc(v['source'].rsplit(':', 1)[0])}</code></li>"
            )
        return [
            H.raw(
                f'<div class="hmp-links"><div class="hmp-links-h">Found in the code</div><ul>{"".join(rows)}</ul></div>'
            )
        ]


class ExampleCallsDirective(SphinxDirective):
    required_arguments = 1

    def run(self):
        calls = A.get("example_calls", {}).get(self.arguments[0], [])
        if not calls:
            return []
        shown = calls[:8]
        items = "".join(
            f'<li><code class="hmp-path">{esc(c["file"])}:{c["line"]}</code>'
            + (
                f' <span class="hmp-muted">also {esc(", ".join(c["also"]))}</span>'
                if c["also"]
                else ""
            )
            + f'<pre class="hmp-toml api-call">{esc(c["code"])}</pre></li>'
            for c in shown
        )
        more = (
            f'<li class="hmp-muted">and {len(calls) - len(shown)} more</li>'
            if len(calls) > len(shown)
            else ""
        )
        folder = A.get("examples_dir", "the examples")
        return [
            H.raw(
                f'<div class="api-calls"><div class="hmp-links-h">Called in the Python scripts of <code>{esc(folder)}</code></div><ul>{items}{more}</ul></div>'
            )
        ]


class MembersDirective(SphinxDirective):
    """Table of the public members of a class, before the details autodoc renders."""

    required_arguments = 1

    def run(self):
        c = next((x for x in A.get("classes", []) if x["name"] == self.arguments[0]), None)
        if c is None or not c.get("members"):
            return []
        b, doc = H.current_builder(), self.env.docname
        rows = []
        for kind in ("property", "method", "attribute"):
            for m in (m for m in c["members"] if m["kind"] == kind):
                name = f"<code>{esc(m['name'])}</code>"
                if m["summary"]:
                    # autodoc renders only the members with a docstring, so only
                    # those have an anchor to link to.
                    name = f'<a href="#{esc(c["qualname"])}.{esc(m["name"])}">{name}</a>'
                    summary = H.inline_md(m["summary"], b, doc)
                else:
                    summary = '<span class="hmp-gap">no docstring</span>'
                rows.append(f"<tr><td>{name}</td><td>{esc(kind)}</td><td>{summary}</td></tr>")
        return [
            H.raw(
                '<div class="hmp-matrix-wrap"><table class="api-t"><thead><tr><th>Member</th><th>Kind</th><th>What it is</th></tr></thead>'
                f"<tbody>{''.join(rows)}</tbody></table></div>"
            )
        ]


# ---------------------------------------------------------------- command-line directives


def args_table(arguments: list[dict], skip: set[str]) -> str:
    rows = []
    for a in arguments:
        if skip and a["flags"][0] in skip:
            continue
        flags = ", ".join(f"<code>{esc(f)}</code>" for f in a["flags"])
        if a.get("metavar"):
            flags += f" <code class='hmp-muted'>{esc(a['metavar'])}</code>"
        extra = []
        if a.get("choices"):
            extra.append("one of " + " | ".join(f"<code>{esc(x)}</code>" for x in a["choices"]))
        if (
            a.get("default") not in (None, "False", "None", "[]")
            and "default" not in (a.get("help") or "").lower()
        ):
            extra.append(f"default <code>{esc(a['default'])}</code>")
        if a.get("required") and not a["positional"]:
            extra.append('<span class="tc tc-req">required</span>')
        helptext = esc(a.get("help") or "") or '<span class="hmp-gap">no help string</span>'
        rows.append(f"<tr><td>{flags}</td><td>{helptext} {' · '.join(extra)}</td></tr>")
    if not rows:
        return ""
    return (
        '<table class="api-t api-args"><thead><tr><th>Argument</th><th>What it does</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table>"
    )


class CommandDirective(SphinxDirective):
    required_arguments = 1
    final_argument_whitespace = True
    option_spec = {"skip": directives.unchanged}

    def run(self):
        path = self.arguments[0].split()
        skip = set((self.options.get("skip") or "").split())
        c = command(path)
        if not c:
            logger.warning(f"[hmp] unknown command {' '.join(path)}", location=self.get_location())
            return []
        parts = [
            f'<pre class="hmp-term cli-usage"><span class="cmd">$ {esc(c["usage"])}</span></pre>'
        ]
        if c["description"]:
            parts.append(f"<p>{esc(c['description'])}</p>")
        if c["subcommands"]:
            b, doc = H.current_builder(), self.env.docname

            def target(name: str) -> str:
                # A top-level command has a page; a deeper one is a section of it,
                # whose id is its words joined by dashes.
                if len(path) == 1:
                    return H.doc_uri(b, doc, command_doc(name))
                return H.doc_uri(b, doc, command_doc(path[1])) + "#" + "-".join(path + [name])

            rows = "".join(
                f'<tr><td><a href="{esc(target(s["name"]))}"><code>{esc(" ".join(path + [s["name"]]))}</code></a></td>'
                f"<td>{esc(s.get('help') or '')}</td></tr>"
                for s in c["subcommands"]
            )
            parts.append(
                f'<table class="api-t"><thead><tr><th>Command</th><th>What it does</th></tr></thead><tbody>{rows}</tbody></table>'
            )
        parts.append(args_table(c["arguments"], skip))
        if c["epilog"]:
            parts.append(f'<pre class="hmp-toml cli-epilog">{esc(c["epilog"])}</pre>')
        return [H.raw("".join(parts))]


class SharedOptionsDirective(SphinxDirective):
    required_arguments = 1
    final_argument_whitespace = True

    def run(self):
        words = self.arguments[0].split()
        top, flags = words[:2], set(words[2:])
        family = [
            c
            for c in A.get("commands", [])
            if c["path"][:2] == top and len(c["path"]) >= 3 and not c["subcommands"]
        ]
        if not family:
            return []
        return [
            H.raw(args_table([a for a in family[0]["arguments"] if a["flags"][0] in flags], set()))
        ]


class ExitCodesDirective(SphinxDirective):
    def run(self):
        codes = A.get("exit_codes", [])
        with_comment = any(e["comment"] for e in codes)
        rows = "".join(
            f"<tr><td><code>{e['code']}</code></td><td><code>{esc(e['name'])}</code></td>"
            f"<td>{', '.join(f'<code>{esc(x)}</code>' for x in e['exceptions']) or '<span class=hmp-muted>no exception mapped</span>'}</td>"
            + (f"<td>{esc(e['comment'])}</td>" if with_comment else "")
            + "</tr>"
            for e in codes
        )
        head = "<th>Comment in the code</th>" if with_comment else ""
        return [
            H.raw(
                f'<table class="api-t"><thead><tr><th>Code</th><th>Name</th><th>Raised for</th>{head}</tr></thead>'
                f"<tbody>{rows}</tbody></table>"
            )
        ]


# ---------------------------------------------------------------- cross references


def resolve_missing(app, env, node, contnode):
    """Link a Python reference written with a re-export path to the page of the object."""
    if node.get("refdomain") != "py":
        return None
    target = node.get("reftarget", "")
    if not target:
        return None
    objects = env.get_domain("py").objects
    parts = target.split(".")
    for n in (3, 2, 1):
        if len(parts) < n:
            continue
        tail = ".".join(parts[-n:])
        cands = [name for name in objects if name.endswith("." + tail) or name == tail]
        if len(cands) == 1:
            obj = objects[cands[0]]
            return make_refnode(
                app.builder, node["refdoc"], obj.docname, obj.node_id, contnode, cands[0]
            )
    return None


# ---------------------------------------------------------------- pages


def class_page(c: dict) -> str:
    return (
        "\n".join(
            [
                "% AUTO-GENERATED by _ext/hmp_api.py. Do not edit.",
                "",
                f"# `{c['name']}`",
                "",
                "```{hmp-api-members} " + c["name"],
                "```",
                "",
                "```{eval-rst}",
                f".. autoclass:: {c['qualname']}",
                "   :members:",
                "   :inherited-members:",
                "   :member-order: groupwise",
                "```",
                "",
            ]
        )
        + "\n"
    )


def gen_pages(srcdir: Path) -> None:
    load(srcdir)
    if not A:
        return
    py, cli = srcdir / PY, srcdir / CLI
    verbs = sorted(v["name"] for v in A["verbs"])
    results = classes("result")
    engines = classes("engine")
    index = (
        [
            "% AUTO-GENERATED by _ext/hmp_api.py. Do not edit.",
            "",
            "# Python API",
            "",
            "`import hydromodpy as hmp`. The functions below are the entry points of the package; the objects "
            "they return hold the results. The Used by column names the `hmp` commands whose source calls the function.",
            "",
            "## Functions",
            "",
            "```{hmp-api-verbs}",
            "```",
            "",
            "## Objects you get back",
            "",
            "```{hmp-api-objects}",
            ":kind: result",
            "```",
            "",
            "## Configuration objects",
            "",
            "Each TOML section is a Pydantic model. In Python you build or edit the same keys, so their reference "
            "is the TOML one. Several classes can share a section: the Selected by column gives the value that picks each one.",
            "",
            "```{hmp-api-configs}",
            "```",
            "",
            "## Engine classes",
            "",
            "```{hmp-api-objects}",
            ":kind: engine",
            "```",
            "",
            "## Modules",
            "",
            "```{hmp-api-modules}",
            "```",
            "",
            "```{hmp-api-gaps}",
            "```",
            "",
            "```{toctree}",
            ":hidden:",
            ":caption: Functions",
            "",
        ]
        + [f"hmp-{v}" for v in verbs]
        + [
            "```",
            "",
            "```{toctree}",
            ":hidden:",
            ":caption: Objects you get back",
            "",
        ]
        + [c["name"] for c in results]
        + [
            "```",
            "",
            "```{toctree}",
            ":hidden:",
            ":caption: Engine classes",
            "",
        ]
        + [c["name"] for c in engines]
        + ["```", ""]
    )
    H.write_if_changed(py / "index.md", "\n".join(index) + "\n")
    for v in A["verbs"]:
        lines = [
            "% AUTO-GENERATED by _ext/hmp_api.py. Do not edit.",
            "",
            f"# `hmp.{v['name']}()`",
            "",
            "```{hmp-api-twin} " + v["name"],
            "```",
            "",
            "```{eval-rst}",
            f".. autofunction:: hydromodpy.{v['name']}",
            "```",
            "",
        ]
        H.write_if_changed(py / f"hmp-{v['name']}.md", "\n".join(lines) + "\n")
    for c in results + engines:
        H.write_if_changed(py / f"{c['name']}.md", class_page(c))

    tops = [c["path"][1] for c in A["commands"] if len(c["path"]) == 2]
    index = (
        [
            "% AUTO-GENERATED by _ext/hmp_api.py. Do not edit.",
            "",
            "# Command line",
            "",
            "```{hmp-command} hmp",
            "```",
            "",
            "Every command ends with a typed exit code: {doc}`exit-codes`.",
            "",
            "```{toctree}",
            ":hidden:",
            "",
        ]
        + tops
        + ["exit-codes", "```", ""]
    )
    H.write_if_changed(cli / "index.md", "\n".join(index) + "\n")
    H.write_if_changed(
        cli / "exit-codes.md",
        "\n".join(
            [
                "% AUTO-GENERATED by _ext/hmp_api.py. Do not edit.",
                "",
                "# Exit codes",
                "",
                "```{hmp-exit-codes}",
                "```",
                "",
            ]
        )
        + "\n",
    )
    for top in tops:
        lines = [
            "% AUTO-GENERATED by _ext/hmp_api.py. Do not edit.",
            "",
            f"# `hmp {top}`",
            "",
        ]
        users = A.get("cli_to_verbs", {}).get(top, [])
        if users:
            lines += [
                "Uses " + ", ".join(f"{{doc}}`hmp.{t}() <../python/hmp-{t}>`" for t in users) + ".",
                "",
            ]
        family = [
            c
            for c in A["commands"]
            if len(c["path"]) >= 3 and c["path"][1] == top and not c["subcommands"]
        ]
        shared: set[str] = set()
        if len(family) >= 3:
            sets = [
                {(a["flags"][0], a["help"]) for a in c["arguments"] if not a["positional"]}
                for c in family
            ]
            shared = {flag for flag, _ in set.intersection(*sets)}
        for c in A["commands"]:
            if len(c["path"]) >= 2 and c["path"][1] == top:
                depth = len(c["path"]) - 1
                if depth > 1:
                    lines += [H.heading(depth, f"`{' '.join(c['path'])}`"), ""]
                lines += ["```{hmp-command} " + " ".join(c["path"])]
                if shared and depth > 1:
                    lines += [":skip: " + " ".join(sorted(shared))]
                lines += ["```", ""]
                if depth == 1 and shared:
                    lines += [
                        f"## Options of every `hmp {top}` subcommand",
                        "",
                        "```{hmp-shared-options} hmp " + top + " " + " ".join(sorted(shared)),
                        "```",
                        "",
                    ]
        H.write_if_changed(cli / f"{top}.md", "\n".join(lines) + "\n")


def setup_api(app) -> None:
    app.add_directive("hmp-api-verbs", VerbsDirective)
    app.add_directive("hmp-api-objects", ObjectsDirective)
    app.add_directive("hmp-api-configs", ConfigsDirective)
    app.add_directive("hmp-api-modules", ModulesDirective)
    app.add_directive("hmp-api-gaps", GapsDirective)
    app.add_directive("hmp-api-twin", TwinDirective)
    app.add_directive("hmp-api-calls", ExampleCallsDirective)
    app.add_directive("hmp-api-members", MembersDirective)
    app.add_directive("hmp-command", CommandDirective)
    app.add_directive("hmp-shared-options", SharedOptionsDirective)
    app.add_directive("hmp-exit-codes", ExitCodesDirective)
    app.connect("missing-reference", resolve_missing)
