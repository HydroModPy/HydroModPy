"""Validation page and "Checked by" boxes, generated from the test suite index.

The index is source/_data/tests.json, written by tools/tests_registry.py from
tests/ and validation_cases/. Nothing here is written by hand per test: titles,
texts, solvers, criteria and thresholds all come from the test files, the case
folders and tests/TOLERANCES.md.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import hmp_params as H
from sphinx.util.docutils import SphinxDirective

DATA: dict = {}

# Folder of tests/validation -> heading. A folder missing here keeps its own name.
GROUPS = {
    "analytical/steady": "Closed-form solutions, steady state",
    "analytical/transient": "Closed-form solutions, transient",
    "numerical/steady": "Published numerical references, steady state",
    "numerical/transient": "Published numerical references, transient",
    "mms": "Manufactured solutions",
    "calibration": "Calibration finds a known truth",
}
# A marker that names a solver, for tests that do not parametrize one.
MARK_SOLVER = {"mf6": "modflow6", "petsc": "petsc"}
SOLVER_ORDER = ["modflow_nwt", "modflow6", "modflow6_irregular_tri", "boussinesq"]
TIER_ORDER = ["validation", "integration", "regression", "e2e", "contract", "unit", "other"]
PREFIXES = ("Validation benchmark for ", "Validate ")


def load(srcdir: Path) -> None:
    path = srcdir / "_data" / "tests.json"
    DATA.clear()
    if path.exists():
        DATA.update(json.loads(path.read_text()))


def esc(text) -> str:
    return H.esc(text)


def md(text: str, builder, docname: str) -> str:
    """Inline Markdown of a docstring or a table cell: code, TOML links, bold."""
    return H.inline_md(text.replace("\\|", "|"), builder, docname)


def anchor_of(file: str) -> str:
    return "val-" + Path(file).stem.removeprefix("test_").replace("_", "-")


def title_of(entry: dict) -> str:
    first = (entry["doc"].strip().splitlines() or [Path(entry["file"]).stem])[0].strip()
    for p in PREFIXES:
        if first.startswith(p):
            first = first[len(p) :]
            first = first[:1].upper() + first[1:]
    return first


def sentence(stem: str) -> str:
    words = stem.removeprefix("test_").replace("_", " ").strip()
    return (words[:1].upper() + words[1:] + ".") if words else stem


def solvers_of(entry: dict) -> list[str]:
    """Parametrized solvers, else the solvers of its cases, else the solver markers."""
    if entry["solvers"]:
        return entry["solvers"]
    from_cases = list(dict.fromkeys(s for c in entry["cases"] for s in c.get("solver_files", {})))
    return from_cases or [MARK_SOLVER[m] for m in entry["markers"] if m in MARK_SOLVER]


def solver_key(s: str) -> tuple[int, str]:
    return (SOLVER_ORDER.index(s) if s in SOLVER_ORDER else len(SOLVER_ORDER), s)


def doc_html(doc: str, builder, docname: str) -> str:
    """Render a test docstring after its first line: paragraphs, lists, literal blocks."""
    lines = doc.strip().splitlines()[1:]
    blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        if ln.strip():
            cur.append(ln.rstrip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    out = []
    for b in blocks:
        if all(ln.startswith((" ", "\t")) for ln in b):
            out.append(
                f'<pre class="hmp-val-pre">{esc(chr(10).join(ln[4:] if ln.startswith("    ") else ln.strip() for ln in b))}</pre>'
            )
        elif len(b) == 2 and set(b[1].strip()) <= set("-=~^"):
            out.append(f"<p><strong>{esc(b[0].strip())}</strong></p>")
        elif all(ln.lstrip().startswith(("- ", "* ")) or ln.startswith("  ") for ln in b) and b[
            0
        ].lstrip().startswith(("- ", "* ")):
            items, buf = [], []
            for ln in b:
                if ln.lstrip().startswith(("- ", "* ")):
                    if buf:
                        items.append(" ".join(buf))
                    buf = [ln.lstrip()[2:]]
                else:
                    buf.append(ln.strip())
            if buf:
                items.append(" ".join(buf))
            out.append(
                "<ul>" + "".join(f"<li>{md(i, builder, docname)}</li>" for i in items) + "</ul>"
            )
        else:
            text = " ".join(ln.strip() for ln in b)
            out.append(
                f"<p>{md(text.removesuffix('::') + (':' if text.endswith('::') else ''), builder, docname)}</p>"
            )
    return "".join(out)


def fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return esc(value)


def criteria_html(entry: dict, case: dict) -> str:
    """One row per checked metric, one column per solver, values from the tolerance files."""
    crits = [c for c in entry["criteria"] if c["key"]]
    files = case.get("tolerance_files", {})
    per_solver = case.get("solver_files", {})
    if crits and per_solver:
        solvers = sorted(per_solver, key=solver_key)
        head = "".join(f"<th><code>{esc(s)}</code></th>" for s in solvers)
        rows = []
        seen = set()
        for c in crits:
            k = (c["label"], c["section"], c["key"])
            if k in seen:
                continue
            seen.add(k)
            cells = []
            for s in solvers:
                table = files.get(per_solver.get(s) or "", {})
                v = (
                    table.get(c["section"], {}).get(c["key"])
                    if isinstance(table.get(c["section"]), dict)
                    else None
                )
                cells.append(f"<td>{fmt(v) if v is not None else '-'}</td>")
            unit = f' <span class="hmp-muted">({esc(c["unit"])})</span>' if c["unit"] else ""
            rows.append(
                f'<tr><td>{esc(c["label"])}{unit} <span class="hmp-muted">&lt;</span></td>{"".join(cells)}</tr>'
            )
        src = ", ".join(
            f"<code>{esc(s)}</code> reads <code>{esc(f)}</code>"
            for s, f in sorted(per_solver.items(), key=lambda kv: solver_key(kv[0]))
            if f
        )
        return (
            f'<table class="hmp-val-crit"><thead><tr><th>Checked metric</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            f'<p class="hmp-muted hmp-val-src">Thresholds from <code>{esc(case["path"])}/</code>: {src}.</p>'
        )
    if files:
        parts = []
        for name, table in files.items():
            users = [s for s, f in per_solver.items() if f == name]
            cells = []
            for sec, metrics in table.items():
                if isinstance(metrics, dict):
                    cells.append(
                        f"<code>{esc(sec)}</code>: "
                        + ", ".join(
                            f"{esc(k)} {fmt(v)}"
                            for k, v in metrics.items()
                            if isinstance(v, (int, float))
                        )
                    )
            who = (
                f' <span class="hmp-muted">used by {", ".join(esc(u) for u in users)}</span>'
                if users
                else ""
            )
            parts.append(f"<li><code>{esc(name)}</code>{who}: {'; '.join(cells)}</li>")
        return f'<ul class="hmp-val-tol">{"".join(parts)}</ul>'
    return ""


def tol_rows_html(entry: dict, builder, docname: str) -> str:
    rows = entry.get("tolerance_rows") or []
    if not rows:
        return ""
    items = "".join(
        f"<li>Row {r['n']}: {md(r['domain'], builder, docname)}, {md(r['metric'], builder, docname)}: "
        f"<code>{esc(r['tolerance'].strip('`'))}</code>"
        f' <span class="hmp-muted">({md(r["source"], builder, docname)})</span></li>'
        for r in rows
    )
    return f'<div class="hmp-val-h">Thresholds from <code>tests/TOLERANCES.md</code></div><ul class="hmp-val-tol">{items}</ul>'


# Two facts a test states about itself. No chip means no claim.
SCOPE = {
    "launcher": (
        "end to end",
        "Its case calls run_launcher_validation_case: a HydroModPy configuration runs through the launcher, as a user run does.",
    ),
    "sanity": (
        "solver sanity",
        "Marked solver_sanity by its author: it checks the solver against the reference, not the HydroModPy pipeline.",
    ),
}


def scopes_of(entry: dict) -> list[str]:
    out = []
    if entry.get("launcher"):
        out.append("launcher")
    if "solver_sanity" in entry["markers"]:
        out.append("sanity")
    return out


def scope_chips(entry: dict) -> str:
    return "".join(
        f'<span class="tc hmp-reach hmp-reach-{k}" title="{esc(SCOPE[k][1])}">{esc(SCOPE[k][0])}</span>'
        for k in scopes_of(entry)
    )


def chips(solvers: list[str]) -> str:
    return "".join(
        f'<span class="tc tc-unit">{esc(s)}</span>' for s in sorted(solvers, key=solver_key)
    )


def entry_html(entry: dict, builder, docname: str) -> str:
    solvers = solvers_of(entry)
    speed = "slow" if "slow" in entry["markers"] else ("fast" if "fast" in entry["markers"] else "")
    body = [doc_html(entry["doc"], builder, docname)]
    for case in entry["cases"]:
        ref = (
            f"<p><strong>Compared with:</strong> {H.inline_md(case['reference'].rstrip(',;. '), builder, docname)}.</p>"
            if case["reference"]
            else ""
        )
        head = (
            f'<div class="hmp-val-case"><div class="hmp-val-h">Case <code>{esc(case["id"])}</code>: {esc(case["title"])}</div>'
            if len(entry["cases"]) > 1
            else '<div class="hmp-val-case">'
        )
        summ = (
            f"<p>{H.inline_md(case['summary'], builder, docname)}</p>"
            if case["summary"] and len(entry["cases"]) > 1
            else ""
        )
        run = (
            f'<p class="hmp-muted">Run it alone: <code>{esc(case["run"])}</code></p>'
            if case["run"]
            else ""
        )
        body.append(head + summ + ref + criteria_html(entry, case) + run + "</div>")
    body.append(tol_rows_html(entry, builder, docname))
    tests = "".join(f"<li>{md(sentence(t), builder, docname)}</li>" for t in entry["tests"])
    body.append(
        f'<div class="hmp-val-h">Test functions</div><ul class="hmp-val-tests">{tests}</ul>'
    )
    body.append(
        f'<p class="hmp-muted">File <code>{esc(entry["file"])}</code>. Markers: {", ".join(esc(m) for m in entry["markers"]) or "none"}.</p>'
    )
    return (
        f'<details class="hmp-val" id="{anchor_of(entry["file"])}"><summary>'
        f'<span class="hmp-val-title">{md(title_of(entry), builder, docname)}</span> {scope_chips(entry)}{chips(solvers)}'
        f"{f'<span class=tc>{speed}</span>' if speed else ''}</summary>"
        f'<div class="hmp-val-body">{"".join(body)}</div></details>'
    )


class ValidationDirective(SphinxDirective):
    """The whole validation page body."""

    def run(self):
        builder = H.current_builder()
        doc = self.env.docname
        entries = DATA.get("validation", [])
        if not entries:
            return [H.raw('<p class="hmp-gap">No test index: run tools/tests_registry.py.</p>')]
        n_tests = sum(len(e["tests"]) for e in entries)
        n_cases = len({c["path"] for e in entries for c in e["cases"]})
        groups: dict[str, list[dict]] = {}
        for e in entries:
            groups.setdefault(e["group"], []).append(e)
        order = [g for g in GROUPS if g in groups] + sorted(g for g in groups if g not in GROUPS)

        # Coverage: test files per group, and per solver inside the group.
        rows = []
        for g in order:
            cnt = Counter(s for e in groups[g] for s in solvers_of(e))
            none = sum(1 for e in groups[g] if not solvers_of(e))
            solv = " ".join(
                f'<span class="hmp-val-solv"><code>{esc(s)}</code> {cnt[s]}</span>'
                for s in sorted(cnt, key=solver_key)
            )
            if none:
                solv += f' <span class="hmp-val-solv hmp-muted">no solver named {none}</span>'
            scope = Counter(k for e in groups[g] for k in scopes_of(e))
            reach_html = (
                " ".join(
                    f'<span class="hmp-val-solv"><span class="tc hmp-reach hmp-reach-{k}">{esc(SCOPE[k][0])}</span> {scope[k]}</span>'
                    for k in SCOPE
                    if scope[k]
                )
                or '<span class="hmp-muted">-</span>'
            )
            rows.append(
                f'<tr><td><a href="#valg-{g.replace("/", "-")}">{esc(GROUPS.get(g, g))}</a></td>'
                f'<td class="hmp-val-n">{len(groups[g])}</td><td>{reach_html}</td><td>{solv}</td></tr>'
            )
        matrix = (
            f'<p class="hmp-val-count">{len(entries)} test files, {n_tests} test functions, {n_cases} benchmark cases.</p>'
            '<table class="hmp-val-matrix"><thead><tr><th>Kind of reference</th><th>Files</th>'
            "<th>Declared scope</th><th>Files per solver</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
            '<p class="hmp-muted">A solver is named by the parametrization of the test, or by a marker '
            "(<code>mf6</code>, <code>petsc</code>). Scope: "
            + "; ".join(f"<em>{esc(v[0])}</em>: {esc(v[1].rstrip('.'))}" for v in SCOPE.values())
            + ". A test with neither says nothing about its scope; read its text.</p>"
        )
        parts = [matrix]
        for g in order:
            parts.append(f'<h2 id="valg-{g.replace("/", "-")}">{esc(GROUPS.get(g, g))}</h2>')
            parts.append("".join(entry_html(e, builder, doc) for e in groups[g]))
        return [H.raw("".join(parts))]


class TestedByDirective(SphinxDirective):
    """The tests that import the modules a page describes, as sentences."""

    has_content = True

    def run(self):
        prefixes = [ln.strip() for ln in self.content if ln.strip()]
        hits = {
            f: info
            for f, info in DATA.get("imports", {}).items()
            if any(m == p or m.startswith(p + ".") for m in info["modules"] for p in prefixes)
        }
        if not hits:
            return [H.raw('<p class="hmp-gap">No test imports these modules.</p>')]
        builder = H.current_builder()
        val_doc = builder.get_relative_uri(self.env.docname, "theory/validation")
        by_tier: dict[str, list[str]] = {}
        for f in sorted(hits):
            by_tier.setdefault(hits[f]["tier"], []).append(f)
        mods = ", ".join(f"<code>{esc(p)}</code>" for p in prefixes)
        out = [
            '<div class="hmp-links hmp-tested"><div class="hmp-links-h">Checked by</div>'
            f'<p class="hmp-muted">{len(hits)} test files import {mods}. Their names say what they check.</p>'
        ]
        for tier in sorted(by_tier, key=lambda t: TIER_ORDER.index(t) if t in TIER_ORDER else 99):
            files = by_tier[tier]
            items = []
            for f in files:
                text = esc(sentence(Path(f).stem))
                if tier == "validation":
                    text = f'<a href="{esc(val_doc)}#{anchor_of(f)}">{text}</a>'
                folder = "/".join(Path(f).parts[2:-1])
                where = (
                    f' <span class="hmp-muted">{esc(folder)}</span>'
                    if folder and tier != "validation"
                    else ""
                )
                items.append(f'<li title="{esc(f)}">{text}{where}</li>')
            label = f"{tier}: {len(files)}"
            opened = " open" if tier in ("validation", "integration") else ""
            out.append(
                f'<details class="hmp-tested-tier"{opened}><summary>{esc(label)}</summary><ul>{"".join(items)}</ul></details>'
            )
        out.append("</div>")
        return [H.raw("".join(out))]


def setup_validation(app) -> None:
    app.connect("builder-inited", lambda a: load(Path(a.srcdir)))
    app.add_directive("hmp-validation", ValidationDirective)
    app.add_directive("hmp-tested-by", TestedByDirective)
