"""Validation page and "Checked by" boxes, generated from the tests and their results.

Two sources, both written from the repository:

- source/_data/tests.json, written by tools/docs/tests_index.py at build: the
  validation test files, their cases (README, equations, tolerance files),
  and the CI jobs that select them;
- source/theory/validation_results.json, committed, refreshed by
  tools/docs/validation_results.py from a local run or from the artifact of
  the nightly job: what each test measured, its outcome, the run date and
  commit.

Nothing here is written by hand per test.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

import hmp_params as H
from docutils import nodes
from docutils.statemachine import StringList
from sphinx.util.docutils import SphinxDirective

DATA: dict = {}
RESULTS: dict = {}
RESULTS_FILE = Path("theory") / "validation_results.json"
REPO_URL = "https://github.com/HydroModPy/HydroModPy"

# Folder of tests/validation -> heading. A folder missing here keeps its own name.
GROUPS = {
    "analytical/steady": "Closed-form solutions, steady state",
    "analytical/transient": "Closed-form solutions, transient",
    "sanity": "MODFLOW 6 alone against a closed form",
    "numerical/steady": "Published numerical references, steady state",
    "numerical/transient": "Published numerical references, transient",
    "mms": "Manufactured solutions",
    "calibration": "Calibration finds a known truth",
}
# A marker that names a solver, for tests that do not parametrize one.
MARK_SOLVER = {"mf6": "modflow6", "petsc": "petsc"}
SOLVER_ORDER = ["modflow_nwt", "modflow6", "modflow6_irregular_tri", "boussinesq"]
MATRIX_COLUMNS = [*SOLVER_ORDER, "other"]
COLUMN_LABELS = {
    "modflow_nwt": "NWT",
    "modflow6": "MF6",
    "modflow6_irregular_tri": "MF6 triangles",
    "boussinesq": "Boussinesq",
    "other": "other",
}
TIER_ORDER = ["validation", "integration", "regression", "e2e", "contract", "unit", "other"]
PREFIXES = (
    "Validation benchmark for ",
    "Validate the ",
    "Validate a ",
    "Validate ",
    "MMS benchmark: ",
)
# Share of the threshold a run used, by bin: CSS class and words.
BINS = [
    (0.25, "r1", "under a quarter of the threshold"),
    (0.5, "r2", "a quarter to half"),
    (0.75, "r3", "half to three quarters"),
    (1.0, "r4", "three quarters to the threshold"),
    (math.inf, "r5", "over the threshold"),
]
STATUS_WORDS = {
    "passed": "pass",
    "failed": "fail",
    "error": "error",
    "skipped": "skipped",
    "not measured": "not measured",
}


def load(srcdir: Path) -> None:
    DATA.clear()
    RESULTS.clear()
    path = srcdir / "_data" / "tests.json"
    if path.exists():
        DATA.update(json.loads(path.read_text()))
    res = srcdir / RESULTS_FILE
    if res.exists():
        RESULTS.update(json.loads(res.read_text()))


def esc(text) -> str:
    return H.esc(text)


def md(text: str, builder, docname: str) -> str:
    """Inline Markdown of a docstring or a table cell: code, TOML links, bold."""
    return H.inline_md(text.replace("\\|", "|"), builder, docname)


def anchor_of(file: str) -> str:
    return "val-" + Path(file).stem.removeprefix("test_").replace("_", "-")


def group_anchor(group: str) -> str:
    return "valg-" + group.replace("/", "-")


def title_of(entry: dict) -> str:
    """First docstring line, without the words every title repeats."""
    first = (entry["doc"].strip().splitlines() or [Path(entry["file"]).stem])[0].strip()
    for p in PREFIXES:
        if first.startswith(p):
            first = first[len(p) :]
            break
    first = first.rstrip(".")
    return first[:1].upper() + first[1:]


def sentence(stem: str) -> str:
    words = stem.removeprefix("test_").replace("_", " ").strip()
    return (words[:1].upper() + words[1:] + ".") if words else stem


def group_of(entry: dict) -> str:
    return "sanity" if "solver_sanity" in entry["markers"] else entry["group"]


def solvers_of(entry: dict) -> list[str]:
    """Parametrized solvers, else the solvers of its cases, else the solver markers."""
    if entry["solvers"]:
        return entry["solvers"]
    from_cases = list(dict.fromkeys(s for c in entry["cases"] for s in c.get("solver_files", {})))
    return from_cases or [MARK_SOLVER[m] for m in entry["markers"] if m in MARK_SOLVER]


def solver_key(s: str) -> tuple[int, str]:
    return (SOLVER_ORDER.index(s) if s in SOLVER_ORDER else len(SOLVER_ORDER), s)


def column_of(solver: str | None) -> str:
    return solver if solver in SOLVER_ORDER else "other"


def fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3g}"
    return esc(value)


# ---------------------------------------------------------------- results


def records_of(entry: dict) -> list[dict]:
    """The recorded results of the tests of one file."""
    return [t for t in RESULTS.get("tests", {}).values() if t["file"] == entry["file"]]


def ratio(metric: dict) -> float | None:
    """The share of the threshold a measure used: 1 is the threshold itself."""
    v, t, op, ideal = metric["value"], metric["threshold"], metric["op"], metric.get("ideal")
    if v is None or t is None:
        return None
    if op in ("<", "<="):
        if t > 0:
            return abs(v) / t
        return 0.0 if v <= 0 else math.inf
    if ideal is not None and ideal != t:
        return max(0.0, (ideal - v) / (ideal - t))
    if v > 0 and t > 0:
        return t / v
    return None


def within(metric: dict) -> bool | None:
    v, t, op = metric["value"], metric["threshold"], metric["op"]
    if v is None or t is None:
        return None
    return {"<": v < t, "<=": v <= t, ">": v > t, ">=": v >= t}.get(op)


def bin_of(r: float | None) -> tuple[str, str]:
    if r is None:
        return "r0", "no threshold recorded"
    for top, cls, words in BINS:
        if (r <= top) if top == 1.0 else (r < top):
            return cls, words
    return "r5", BINS[-1][2]


def outcome_of(records: list[dict]) -> str:
    """One status for several records: failed wins, then passed, then skipped."""
    outcomes = {r["outcome"] for r in records}
    for o in ("failed", "error", "passed", "skipped"):
        if o in outcomes:
            return o
    return "not measured"


def gap_notes(entry: dict) -> dict[str, str]:
    """Known discrepancies the thresholds let through, by solver."""
    out = {}
    for case in entry["cases"]:
        notes = case.get("tolerance_notes", {})
        for solver, name in case.get("solver_files", {}).items():
            gap = notes.get(name or "", {}).get("gap")
            if gap:
                out[solver] = gap
    return out


def reason_notes(entry: dict) -> list[tuple[list[str], str]]:
    """Why a tolerance file has its values, with the solvers that read it."""
    out = []
    for case in entry["cases"]:
        users: dict[str, list[str]] = {}
        for solver, name in case.get("solver_files", {}).items():
            users.setdefault(name or "", []).append(solver)
        for name, notes in case.get("tolerance_notes", {}).items():
            if notes.get("reason") and name in users:
                out.append((sorted(users[name], key=solver_key), notes["reason"]))
    return out


def loose_thresholds(entry: dict) -> list[str]:
    """Thresholds of one solver more than twice those of another, with no reason written."""
    out = []
    reasons = {s for solvers, _ in reason_notes(entry) for s in solvers}
    for case in entry["cases"]:
        files = case.get("tolerance_files", {})
        per = case.get("solver_files", {})
        if len(per) < 2:
            continue
        for c in entry["criteria"]:
            if not c["key"] or c.get("op", "<") != "<":
                continue
            values = {}
            for s, name in per.items():
                table = files.get(name or "", {}).get(c["section"] or "", {})
                v = table.get(c["key"]) if isinstance(table, dict) else None
                if isinstance(v, (int, float)) and v > 0:
                    values[s] = float(v)
            if len(values) < 2:
                continue
            low = min(values, key=values.get)
            for s, v in values.items():
                if v > 2 * values[low] and s not in reasons:
                    out.append(
                        f"{esc(c['label'])}: <code>{esc(s)}</code> allows {v:g}, "
                        f"{v / values[low]:.0f} times the {values[low]:g} of <code>{esc(low)}</code>"
                    )
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- html pieces


def status_chip(status: str, gap: bool = False) -> str:
    if gap and status == "passed":
        return '<span class="hmp-vs hmp-vs-gap">pass, known gap</span>'
    word = STATUS_WORDS.get(status, status)
    return f'<span class="hmp-vs hmp-vs-{status.replace(" ", "-")}">{esc(word)}</span>'


def run_line(records: list[dict]) -> str:
    """Date, commit and version of the runs behind some records."""
    parts = []
    for key in sorted({r.get("run") for r in records if r.get("run")}):
        run = RESULTS.get("runs", {}).get(key, {})
        commit = run.get("commit") or ""
        link = (
            f'<a href="{REPO_URL}/commit/{esc(commit)}"><code>{esc(commit[:9])}</code></a>'
            if commit
            else "an unknown commit"
        )
        where = "the nightly CI job" if run.get("ci_run") else "a local run"
        ci = f' (<a href="{esc(run["ci_run"])}">job log</a>)' if run.get("ci_run") else ""
        dirty = " with uncommitted changes" if run.get("dirty") else ""
        parts.append(
            f"{esc(run.get('date', '')[:10])}, commit {link}{dirty}, "
            f"version {esc(run.get('version', '?'))}, {where}{ci}"
        )
    return "; ".join(parts)


def scale_text(metric: dict, scale: dict | None) -> str:
    """The value and the threshold as shares of the signal they are read against."""
    if not scale or metric["unit"] != scale.get("unit") or metric["threshold"] is None:
        return ""
    t = metric["threshold"] / scale["value"]
    v = f"{abs(metric['value']) / scale['value']:.1%}" if metric["value"] is not None else "-"
    return f"{v} / {t:.1%}"


def scales_line(records: list[dict]) -> str:
    """The signals the shares of the last column are read against."""
    seen = {}
    for r in records:
        sc = r.get("scale")
        if sc:
            key = (sc["label"], sc["unit"])
            seen.setdefault(key, []).append(sc["value"])
    if not seen:
        return ""
    parts = []
    for (label, unit), values in seen.items():
        lo, hi = min(values), max(values)
        size = f"{lo:.3g} {unit}" if lo == hi else f"{lo:.3g} to {hi:.3g} {unit}"
        parts.append(f"the {esc(label)}, {esc(size)}")
    return (
        " The last column gives the measured value and the threshold as shares of "
        + "; ".join(parts)
        + "."
    )


def results_table(entry: dict, records: list[dict], builder, docname: str) -> str:
    """One row per recorded metric: measured, threshold, share used, share of the signal."""
    if not records:
        return (
            '<p class="hmp-val-warn">No measurement in the results snapshot: no recorded run '
            "has reached this file.</p>"
        )
    gaps = gap_notes(entry)
    many_functions = len({r["function"] for r in records}) > 1
    rows = []
    for r in sorted(records, key=lambda r: (r["function"], solver_key(r.get("solver") or ""))):
        label = r.get("params") or r.get("solver") or ""
        if many_functions:
            name = sentence(r["function"]).rstrip(".")
            label = f"{name} [{label}]" if label else name
        chip = status_chip(r["outcome"], bool(gaps.get(r.get("solver") or "")))
        head = f'<td rowspan="{max(1, len(r["metrics"]))}">{esc(label) or "-"}<br>{chip}</td>'
        if not r["metrics"]:
            why = (
                esc(r["reason"])
                if r["reason"]
                else "no metric recorded; the asserts of the test decide"
            )
            rows.append(f'<tr>{head}<td colspan="5" class="hmp-muted">{why}</td></tr>')
            continue
        for i, m in enumerate(r["metrics"]):
            rr = ratio(m)
            cls, words = bin_of(rr)
            ok = within(m)
            out_cls = " hmp-val-out" if ok is False else ""
            unit = f" {esc(m['unit'])}" if m["unit"] else ""
            share = f"{rr:.0%}" if rr is not None and math.isfinite(rr) else "-"
            rows.append(
                ("<tr>" + head if i == 0 else "<tr>")
                + f"<td>{md(m['name'], builder, docname)}</td>"
                + f'<td class="hmp-val-num{out_cls}">{fmt(m["value"])}{unit}</td>'
                + f'<td class="hmp-val-num">{esc(m["op"])} {fmt(m["threshold"])}{unit}</td>'
                + f'<td class="hmp-val-num"><span class="hmp-val-share hmp-val-{cls}" title="{esc(words)}">{share}</span></td>'
                + f'<td class="hmp-muted">{scale_text(m, r.get("scale"))}</td></tr>'
            )
    skipped = sum(1 for r in records if r["outcome"] == "skipped")
    note = (
        f'<p class="hmp-muted">{skipped} of {len(records)} variants were skipped in that run: '
        "they prove nothing here.</p>"
        if skipped
        else ""
    )
    return (
        '<div class="hmp-val-scroll"><table class="hmp-val-res"><thead><tr><th>Variant</th>'
        "<th>Metric</th><th>Measured</th><th>Threshold</th><th>Share used</th>"
        "<th>Share of the signal</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        f'<p class="hmp-muted">Measured on {run_line(records)}.{scales_line(records)}</p>{note}'
    )


def _axis(values: list, log: bool) -> tuple[float, float]:
    vals = [math.log10(v) if log else v for v in values if v is not None and (not log or v > 0)]
    if not vals:
        return 0.0, 1.0
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        pad = abs(hi) * 0.05 or 1.0
        lo, hi = lo - pad, hi + pad
    return lo, hi


def svg_series(series: dict, title: str) -> str:
    """A small figure: the reference as a line, the simulation as dots."""
    w, h, ml, mr, mt, mb = 300, 190, 46, 8, 8, 34
    log = series.get("log", False)
    xs, ref, sim = series["x"], series["reference"], series["simulated"]
    x0, x1 = _axis(xs, log)
    y0, y1 = _axis([*ref, *sim], log)

    def px(v: float) -> float:
        v = math.log10(v) if log else v
        return ml + (v - x0) / (x1 - x0) * (w - ml - mr)

    def py(v: float) -> float:
        v = math.log10(v) if log else v
        return h - mb - (v - y0) / (y1 - y0) * (h - mt - mb)

    def good(v) -> bool:
        return v is not None and (not log or v > 0)

    line = " ".join(
        f"{px(xs[i]):.1f},{py(ref[i]):.1f}" for i in range(len(xs)) if good(xs[i]) and good(ref[i])
    )
    dots = "".join(
        f'<circle cx="{px(xs[i]):.1f}" cy="{py(sim[i]):.1f}" r="2.2"/>'
        for i in range(len(xs))
        if good(xs[i]) and good(sim[i])
    )

    def tick(v: float) -> str:
        return f"{10**v:.2g}" if log else f"{v:.3g}"

    y_name = series["y_label"].split(" (")[0]
    y_unit = series["y_label"][len(y_name) :].strip(" ()")
    labels = (
        f'<text x="{ml}" y="{h - mb + 13}" text-anchor="start">{tick(x0)}</text>'
        f'<text x="{w - mr}" y="{h - mb + 13}" text-anchor="end">{tick(x1)}</text>'
        f'<text x="{(ml + w - mr) / 2}" y="{h - 4}" text-anchor="middle">{esc(series["x_label"])}</text>'
        f'<text x="{ml - 4}" y="{h - mb}" text-anchor="end">{tick(y0)}</text>'
        f'<text x="{ml - 4}" y="{mt + 8}" text-anchor="end">{tick(y1)}</text>'
        f'<text x="{ml - 4}" y="{(mt + h - mb) / 2}" text-anchor="end">{esc(y_unit)}</text>'
    )
    desc = f"{series['name']}, {title}: reference as a line, simulation as dots"
    return (
        f'<figure class="hmp-val-fig"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(desc)}">'
        f'<g class="hmp-val-axes"><line x1="{ml}" y1="{h - mb}" x2="{w - mr}" y2="{h - mb}"/>'
        f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{h - mb}"/></g><g class="hmp-val-lab">{labels}</g>'
        f'<polyline class="hmp-val-ref" points="{line}"/><g class="hmp-val-sim">{dots}</g></svg>'
        f"<figcaption><code>{esc(title)}</code>: {esc(series['name'].lower())}, {esc(y_name)}"
        f"{', log scales' if log else ''}</figcaption></figure>"
    )


def figures_html(records: list[dict]) -> str:
    figs = [
        svg_series(s, r.get("params") or r.get("solver") or "run")
        for r in sorted(records, key=lambda r: solver_key(r.get("solver") or ""))
        for s in r.get("series", [])
    ]
    if not figs:
        return ""
    more = (
        f'<p class="hmp-muted">{len(figs) - 8} more curves are in the results snapshot.</p>'
        if len(figs) > 8
        else ""
    )
    legend = (
        '<p class="hmp-muted hmp-val-legend"><span class="hmp-val-key-ref"></span> reference '
        '<span class="hmp-val-key-sim"></span> simulated, in the run above</p>'
    )
    return f'<div class="hmp-val-figs">{"".join(figs[:8])}</div>{legend}{more}'


def criteria_html(entry: dict, case: dict) -> str:
    """One row per checked metric, one column per solver, values from the tolerance files."""
    crits = [c for c in entry["criteria"] if c["key"]]
    files = case.get("tolerance_files", {})
    per_solver = case.get("solver_files", {})
    if not (crits and per_solver):
        return ""
    solvers = sorted(per_solver, key=solver_key)
    head = "".join(f"<th><code>{esc(s)}</code></th>" for s in solvers)
    rows, seen = [], set()
    for c in crits:
        k = (c["label"], c["section"], c["key"])
        if k in seen:
            continue
        seen.add(k)
        cells = []
        for s in solvers:
            table = files.get(per_solver.get(s) or "", {})
            sec = table.get(c["section"])
            v = sec.get(c["key"]) if isinstance(sec, dict) else None
            cells.append(f'<td class="hmp-val-num">{fmt(v)}</td>')
        unit = f' <span class="hmp-muted">({esc(c["unit"])})</span>' if c["unit"] else ""
        rows.append(
            f"<tr><td>{esc(c['label'])}{unit} {esc(c.get('op', '<'))}</td>{''.join(cells)}</tr>"
        )
    src = ", ".join(
        f"<code>{esc(s)}</code> reads <code>{esc(f)}</code>"
        for s, f in sorted(per_solver.items(), key=lambda kv: solver_key(kv[0]))
        if f
    )
    return (
        '<div class="hmp-val-scroll"><table class="hmp-val-crit"><thead><tr><th>Threshold</th>'
        f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        f'<p class="hmp-muted">From <code>{esc(case["path"])}/</code>: {src}.</p>'
    )


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
    return (
        '<p class="hmp-val-h">Thresholds from <code>tests/TOLERANCES.md</code></p>'
        f'<ul class="hmp-val-tol">{items}</ul>'
    )


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
            body = "\n".join(ln[4:] if ln.startswith("    ") else ln.strip() for ln in b)
            out.append(f'<pre class="hmp-val-pre">{esc(body)}</pre>')
        elif len(b) == 2 and set(b[1].strip()) <= set("-=~^"):
            out.append(f"<p><strong>{esc(b[0].strip())}</strong></p>")
        elif b[0].lstrip().startswith(("- ", "* ")) and all(
            ln.lstrip().startswith(("- ", "* ")) or ln.startswith("  ") for ln in b
        ):
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
            if text.lower().startswith("compared with:"):
                continue
            text = text.removesuffix("::") + (":" if text.endswith("::") else "")
            out.append(f"<p>{md(text, builder, docname)}</p>")
    return "".join(out)


SCOPE = {
    "launcher": (
        "end to end",
        "Its case calls run_launcher_validation_case: a HydroModPy configuration runs "
        "through the launcher, as a user run does.",
    ),
    "sanity": (
        "solver sanity",
        "Marked solver_sanity by its author: it checks the solver against the reference, "
        "not the HydroModPy pipeline.",
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
        f'<span class="tc hmp-val-scope" title="{esc(SCOPE[k][1])}">{esc(SCOPE[k][0])}</span>'
        for k in scopes_of(entry)
    )


def jobs_html(entry: dict) -> str:
    """Which CI jobs select this file, per solver."""
    jobs = DATA.get("schedule", [])
    runs = entry.get("runs_in", {})
    if not jobs or not runs:
        return ""
    by_jobs: dict[tuple, list[str]] = {}
    for solver, hits in runs.items():
        by_jobs.setdefault(tuple((h["job"], h["skipped"]) for h in hits), []).append(solver)
    parts = []
    for key, solvers in by_jobs.items():
        who = (
            "This file"
            if solvers == [""]
            else ", ".join(f"<code>{esc(s)}</code>" for s in sorted(solvers, key=solver_key))
        )
        live = [jobs[j]["job"] for j, skipped in key if not skipped]
        dead = [jobs[j]["job"] for j, skipped in key if skipped]
        text = (
            "runs in " + ", ".join(esc(n) for n in live)
            if live
            else '<span class="hmp-val-warn">runs in no CI job</span>'
        )
        if dead:
            text += f" (skipped in {', '.join(esc(n) for n in dead)}: no petsc4py there)"
        parts.append(f"{who}: {text}.")
    return (
        '<p class="hmp-val-jobs"><strong>Schedule.</strong> '
        f'{" ".join(parts)} <a href="#val-schedule">Jobs</a>.</p>'
    )


# ---------------------------------------------------------------- nodes


def title_node(text: str) -> nodes.title:
    """A section title with ``code`` spans."""
    title = nodes.title()
    for i, part in enumerate(re.split(r"`+([^`]+)`+", text)):
        if i % 2:
            title += nodes.literal(part, part)
        elif part:
            title += nodes.Text(part)
    return title


def section(ident: str, text: str) -> nodes.section:
    sec = nodes.section(ids=[ident])
    sec += title_node(text)
    return sec


class ValidationDirective(SphinxDirective):
    """The whole validation page body, as real sections."""

    def label(self, ident: str, title: str) -> None:
        """Make a section citable with {ref} from any page."""
        std = self.env.domains.standard_domain
        std.note_hyperlink_target(ident, self.env.docname, ident, title.replace("`", ""))

    def parse_md(self, text: str) -> nodes.container:
        box = nodes.container(classes=["hmp-val-eq"])
        self.state.nested_parse(StringList(text.splitlines()), self.content_offset, box)
        return box

    def run(self):
        builder = H.current_builder()
        doc = self.env.docname
        entries = DATA.get("validation", [])
        if not entries:
            return [H.raw('<p class="hmp-gap">No test index: run tools/docs/tests_index.py.</p>')]
        # Both sources change without the page source changing: read the page again.
        self.env.note_dependency(str(Path(self.env.srcdir) / RESULTS_FILE))
        self.env.note_dependency(str(Path(self.env.srcdir) / "_data" / "tests.json"))
        groups: dict[str, list[dict]] = {}
        for e in entries:
            groups.setdefault(group_of(e), []).append(e)
        order = [g for g in GROUPS if g in groups] + sorted(g for g in groups if g not in GROUPS)

        out: list[nodes.Node] = [H.raw(self.summary(entries))]
        out.append(self.schedule_section(entries))
        out.append(self.matrix_section(order, groups))
        for g in order:
            sec = section(group_anchor(g), GROUPS.get(g, g))
            self.label(group_anchor(g), GROUPS.get(g, g))
            for e in groups[g]:
                sec += self.entry_section(e, builder, doc)
            out.append(sec)
        return out

    def summary(self, entries: list[dict]) -> str:
        n_tests = sum(len(e["tests"]) for e in entries)
        n_cases = len({c["path"] for e in entries for c in e["cases"]})
        records = [r for e in entries for r in records_of(e)]
        count = Counter(r["outcome"] for r in records)
        runs = RESULTS.get("runs", {})
        dates = sorted(r.get("date", "")[:10] for r in runs.values())
        if records:
            span = dates[0] if dates[0] == dates[-1] else f"{dates[0]} to {dates[-1]}"
            measured = (
                f"The results snapshot holds {len(records)} test results from {len(runs)} "
                f"run{'s' if len(runs) > 1 else ''} ({span}): "
                + ", ".join(f"{n} {STATUS_WORDS.get(k, k)}" for k, n in count.most_common())
                + "."
            )
        else:
            measured = "No result has been recorded yet."
        return (
            f'<p class="hmp-val-count">{len(entries)} test files, {n_tests} test functions, '
            f"{n_cases} benchmark cases. {measured}</p>"
        )

    def schedule_section(self, entries: list[dict]) -> nodes.section:
        sec = section("val-schedule", "When the checks run")
        self.label("val-schedule", "When the checks run")
        rows = []
        for j in DATA.get("schedule", []):
            sel = " ".join(f"<code>{esc(p)}</code>" for p in j["paths"])
            if j["markers"]:
                sel += f' with <code>-m "{esc(j["markers"])}"</code>'
            branches = f" on {', '.join(j['branches'])}" if j["branches"] else ""
            rows.append(
                f'<tr><td>{esc(j["job"])}<br><code class="hmp-val-wf">{esc(j["workflow"])}</code></td>'
                f"<td>{'; '.join(esc(w) for w in j['when'])}{esc(branches)}</td><td>{sel}</td>"
                f"<td>{'yes' if j['petsc4py'] else 'no'}</td></tr>"
            )
        never = sorted(
            {
                (e["file"], s)
                for e in entries
                for s, hits in e.get("runs_in", {}).items()
                if not any(not h["skipped"] for h in hits)
            }
        )
        never_html = ""
        if never:
            by_solver = Counter(s or "no solver named" for _, s in never)
            never_html = (
                f'<p class="hmp-val-warn">{len(never)} pairs of a test file and a solver run in no '
                "CI job: "
                + ", ".join(f"<code>{esc(s)}</code> {n}" for s, n in by_solver.most_common())
                + ". The test suite marks the Boussinesq variant of every analytical case "
                "<code>petsc</code>. The jobs that exclude that marker leave it out, the push gate "
                "skips it for want of petsc4py, and the PETSc job selects named files only. "
                "Each section below says which jobs run its file.</p>"
            )
        sec += H.raw(
            "<p>Read from <code>.github/workflows/</code>. A job runs a file when one of its paths "
            "holds it and its marker expression accepts the markers of the file. A test marked "
            "<code>petsc</code> is skipped where petsc4py is not installed. The nightly jobs "
            "upload what they measured. The deployed page lays the latest nightly results of "
            "its branch over the snapshot committed with the documentation.</p>"
            '<div class="hmp-val-scroll"><table class="hmp-val-sched"><thead><tr><th>Job</th>'
            "<th>When</th><th>Selects</th><th>petsc4py</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>{never_html}"
        )
        return sec

    def matrix_section(self, order: list[str], groups: dict) -> nodes.section:
        sec = section("val-matrix", "Case by solver")
        self.label("val-matrix", "Case by solver")
        builder, doc = H.current_builder(), self.env.docname
        head = "".join(f'<th title="{esc(c)}">{esc(COLUMN_LABELS[c])}</th>' for c in MATRIX_COLUMNS)
        rows = []
        for g in order:
            rows.append(
                f'<tr class="hmp-val-grow"><th colspan="{len(MATRIX_COLUMNS) + 1}">'
                f'<a href="#{group_anchor(g)}">{esc(GROUPS.get(g, g))}</a></th></tr>'
            )
            for e in groups[g]:
                recs = records_of(e)
                gaps = {column_of(s) for s in gap_notes(e)}
                declared = {column_of(s) for s in solvers_of(e)} or {"other"}
                only = next(iter(declared)) if len(declared) == 1 else "other"

                def col_of(r: dict, only: str = only) -> str:
                    return column_of(r["solver"]) if r.get("solver") else only

                cells = "".join(
                    self.cell(
                        [r for r in recs if col_of(r) == col],
                        col in declared,
                        col in gaps,
                    )
                    for col in MATRIX_COLUMNS
                )
                rows.append(
                    f'<tr><td><a href="#{anchor_of(e["file"])}">{md(title_of(e), builder, doc)}</a></td>'
                    f"{cells}</tr>"
                )
        legend = " ".join(
            f'<span class="hmp-val-share hmp-val-{cls}">{esc(words)}</span>'
            for _, cls, words in BINS
        )
        sec += H.raw(
            "<p>Each cell is the largest share of its threshold that a metric used in the last "
            "recorded run of that solver: 50 % means the worst metric sat at half its threshold. "
            "A metric that must stay above its threshold counts the share of the margin it used "
            "between its ideal value and the threshold. <em>skipped</em> and <em>not measured</em> "
            "prove nothing. A cross marks a failure. <em>gap</em> marks a known discrepancy that "
            "the threshold lets through; the section of the case explains it. <em>other</em> "
            "gathers the solvers outside the four columns and the tests that name none. The columns "
            "are <code>modflow_nwt</code>, <code>modflow6</code>, <code>modflow6_irregular_tri</code> "
            "and <code>boussinesq</code>.</p>"
            f'<p class="hmp-val-legend">{legend}</p>'
            '<div class="hmp-val-scroll"><table class="hmp-val-matrix"><thead><tr><th>Case</th>'
            f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        )
        return sec

    @staticmethod
    def cell(records: list[dict], declared: bool, gap: bool) -> str:
        if not records:
            if declared:
                return '<td class="hmp-val-cell hmp-val-nm">not measured</td>'
            return '<td class="hmp-val-cell hmp-val-na"></td>'
        status = outcome_of(records)
        ratios = [ratio(m) for r in records for m in r["metrics"]]
        worst = max((x for x in ratios if x is not None), default=None)
        mark = ' <span class="hmp-val-gapmark">gap</span>' if gap else ""
        if status in ("failed", "error"):
            share = f" {worst:.0%}" if worst is not None and math.isfinite(worst) else ""
            return f'<td class="hmp-val-cell hmp-val-r5" title="failed">&#x2717;{share}{mark}</td>'
        if status == "skipped":
            return '<td class="hmp-val-cell hmp-val-sk">skipped</td>'
        if worst is None:
            return (
                f'<td class="hmp-val-cell hmp-val-r0" title="passed, no metric recorded">'
                f"pass{mark}</td>"
            )
        cls, words = bin_of(worst)
        text = f"{worst:.0%}" if math.isfinite(worst) else "over"
        return f'<td class="hmp-val-cell hmp-val-{cls}" title="{esc(words)}">{text}{mark}</td>'

    def entry_section(self, entry: dict, builder, doc: str) -> nodes.section:
        ident = anchor_of(entry["file"])
        title = title_of(entry)
        sec = section(ident, title)
        self.label(ident, title)
        records = records_of(entry)
        solvers = sorted(solvers_of(entry), key=solver_key)
        status = outcome_of(records)
        gaps = gap_notes(entry)
        chips = scope_chips(entry) + "".join(
            f'<span class="tc tc-unit">{esc(s)}</span>' for s in solvers
        )
        head = f'<p class="hmp-val-chips">{status_chip(status, bool(gaps))} {chips}</p>'
        by_text: dict[str, list[str]] = {}
        for solver, text in gaps.items():
            by_text.setdefault(text, []).append(solver)
        for text, who in by_text.items():
            names = ", ".join(f"<code>{esc(s)}</code>" for s in sorted(who, key=solver_key))
            head += (
                '<div class="admonition warning hmp-val-gap"><p class="admonition-title">'
                f"Known gap: {names}</p><p>{md(text, builder, doc)}</p></div>"
            )
        sec += H.raw(head)

        refs = [c["reference"] for c in entry["cases"] if c["reference"]] or (
            [entry["reference"]] if entry.get("reference") else []
        )
        if refs:
            what = (
                "<p><strong>Compared with:</strong> "
                + "; ".join(md(r.rstrip(",;. "), builder, doc) for r in dict.fromkeys(refs))
                + ".</p>"
            )
        else:
            what = '<p class="hmp-val-warn">No reference named. The text of the test says what it checks.</p>'
        sec += H.raw(what)
        for case in entry["cases"]:
            if case.get("equations"):
                if len(entry["cases"]) > 1:
                    sec += H.raw(f'<p class="hmp-val-h">Case <code>{esc(case["id"])}</code></p>')
                sec += self.parse_md(case["equations"])

        sec += H.raw(
            '<p class="hmp-val-h">Last measurement</p>'
            + results_table(entry, records, builder, doc)
            + figures_html(records)
        )
        notes = []
        for who, reason in reason_notes(entry):
            names = ", ".join(f"<code>{esc(s)}</code>" for s in who)
            notes.append(f"<li>Thresholds of {names}: {md(reason, builder, doc)}</li>")
        notes += [
            f"<li>{text}. No reason is written for this difference.</li>"
            for text in loose_thresholds(entry)
        ]
        if notes:
            sec += H.raw(f'<p class="hmp-val-h">Why these thresholds</p><ul>{"".join(notes)}</ul>')
        sec += H.raw(jobs_html(entry))

        body = [doc_html(entry["doc"], builder, doc)]
        for case in entry["cases"]:
            if len(entry["cases"]) > 1:
                body.append(
                    f'<p class="hmp-val-h">Case <code>{esc(case["id"])}</code>: {esc(case["title"])}</p>'
                )
            body.append(criteria_html(entry, case))
            if case["run"]:
                body.append(
                    f'<p class="hmp-muted">Run it alone: <code>{esc(case["run"])}</code></p>'
                )
        body.append(tol_rows_html(entry, builder, doc))
        tests = "".join(f"<li>{md(sentence(t), builder, doc)}</li>" for t in entry["tests"])
        body.append(
            f'<p class="hmp-val-h">Test functions</p><ul class="hmp-val-tests">{tests}</ul>'
        )
        body.append(
            f'<p class="hmp-muted">File <code>{esc(entry["file"])}</code>. '
            f"Markers: {', '.join(esc(m) for m in entry['markers']) or 'none'}.</p>"
        )
        sec += H.raw(
            '<details class="hmp-val-more"><summary>What the test does, all thresholds, '
            f'the file</summary><div class="hmp-val-body">{"".join(body)}</div></details>'
        )
        return sec


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
        self.env.note_dependency(str(Path(self.env.srcdir) / "_data" / "tests.json"))
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
                f'<details class="hmp-tested-tier"{opened}><summary>{esc(label)}</summary>'
                f"<ul>{''.join(items)}</ul></details>"
            )
        out.append("</div>")
        return [H.raw("".join(out))]


def _page_css(app, pagename, templatename, context, doctree) -> None:
    """Load the validation styles only on the pages that show a check."""
    if doctree is not None and any(
        "hmp-val" in n.astext() or "hmp-tested" in n.astext() for n in doctree.findall(nodes.raw)
    ):
        app.add_css_file("css/hmp-validation.css", priority=600)


def setup_validation(app) -> None:
    app.connect("builder-inited", lambda a: load(Path(a.srcdir)))
    app.add_directive("hmp-validation", ValidationDirective)
    app.add_directive("hmp-tested-by", TestedByDirective)
    app.connect("html-page-context", _page_css)
