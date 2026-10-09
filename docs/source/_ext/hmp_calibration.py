"""Calibration methods and metrics, rendered from the registries of the code.

``tools/docs/calibration_catalog.py`` reads the optimizer registry, the options
model and the traits of each engine, the metric kernels and their formulas. Two
directives render that payload:

- ``hmp-calibration-methods``: a summary table of every method, then one section
  per method with its options and what it declares. ``:summary:`` keeps the
  table only, and its names link to the sections of the page that renders them
  whole.
- ``hmp-calibration-metrics``: a summary table of every metric, then the formula
  of each. ``:table:`` or ``:formulas:`` keeps one of the two.

A wrong row is fixed in the code: the docstring or a field of the engine's
options model, the traits of its adapter, or ``criteria/formulas.py``.

The text is built as reStructuredText and parsed with the role ``:toml:`` and
``:math:`` available, so it reads the same on a Markdown and on a
reStructuredText page.
"""

from __future__ import annotations

from typing import Any

from docutils import nodes
from docutils.parsers.rst import Parser, directives
from docutils.utils import new_document
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

logger = logging.getLogger(__name__)

PAGES = ("reference/calibration-methods", "theory/calibration/inverse-problem-formulation")
"""The pages that render the catalog. They are read again at every build."""

LABEL_PREFIX = "calibration-method-"

_PAYLOAD: dict[str, Any] = {}


def payload() -> dict[str, Any]:
    """The catalog, built once per process."""
    if not _PAYLOAD:
        from tools.docs.calibration_catalog import build

        _PAYLOAD.update(build())
    return _PAYLOAD


def _cell(text: str) -> str:
    return " ".join(str(text).split()) or "\\-"


def _literal(value: Any) -> str:
    if isinstance(value, str):
        return f'``"{value}"``'
    if isinstance(value, bool):
        return f"``{str(value).lower()}``"
    if value is None:
        return "not set"
    return f"``{value}``"


def _table(head: list[str], rows: list[list[str]], widths: str) -> str:
    lines = [".. list-table::", "   :header-rows: 1", f"   :widths: {widths}", ""]
    for row in [head, *rows]:
        lines.append("   * - " + "\n     - ".join(_cell(c) for c in row))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- methods


def method_parameters(m: dict[str, Any]) -> str:
    count = m["max_parameters"]
    moved = "Any number" if count is None else ("One" if count == 1 else f"Up to {count}")
    space = m["required_transform"]
    return f"{moved}, in {space} space only" if space else moved


def method_stops(m: dict[str, Any]) -> str:
    option = m["tolerance_option"]
    if option is None:
        return (
            "On its budget, or on a rule of its own options. "
            ":toml:`calibration.tolerance` is refused."
        )
    if m["tolerance_reads"] == "relative_value":
        how = "a relative precision on the parameter, passed through as is"
    else:
        how = "a width in the space the search walks, converted from the relative precision"
    return (
        f"On a precision on the parameter: :toml:`calibration.tolerance` writes "
        f"``{option}``, {how}."
    )


def method_budget(m: dict[str, Any]) -> str:
    if m["counts_its_budget"]:
        return (
            '``max_iter = "auto"`` counts the evaluations its rule needs before the first '
            "solve. A smaller number is refused or warned by ``hmp calibrate --check``."
        )
    return f'``max_iter = "auto"`` gives {m["uncounted_budget"]} evaluations.'


def method_facts(m: dict[str, Any]) -> list[tuple[str, str]]:
    facts = [("Parameters", method_parameters(m))]
    if m["needs_signed_residual"]:
        facts.append(
            (
                "Criterion",
                "A signed one only: every block it scores reads a signed residual, "
                "``distance_gap``.",
            )
        )
    if m.get("reads_cost_as"):
        facts.append(
            (
                "Cost",
                f"Read as ``{m['reads_cost_as']}``: score the search on that metric. "
                "``hmp calibrate --check`` warns when it is scored on another one.",
            )
        )
    facts.append(("Stops", method_stops(m)))
    facts.append(("Budget", method_budget(m)))
    facts.append(
        (
            "Parallel trials",
            "Yes, with :toml:`calibration.parallel`."
            if m["supports_parallel"]
            else "No: it proposes one trial at a time, so ``parallel`` buys nothing.",
        )
    )
    facts.append(
        (
            "Starts from an earlier phase",
            "Yes: a parameter an earlier phase passed on starts at that value."
            if m["accepts_a_start_point"]
            else "No.",
        )
    )
    facts.append(
        (
            "Restarts",
            "Accepted by the ``multistart`` uncertainty."
            if m["restarts_explore_differently"]
            else "Refused by the ``multistart`` uncertainty: it returns the same answer every time.",
        )
    )
    rank = m["chosen_rank"]
    if rank == 0:
        facts.append(
            (
                "Without a method",
                "Chosen first, when the search meets every condition above.",
            )
        )
    elif rank is not None:
        facts.append(("Without a method", "Chosen when the methods before it do not fit."))
    return facts


def methods_summary_rst(rows: list[dict[str, Any]], *, link: bool) -> str:
    body = []
    for m in rows:
        name = f":ref:`{m['name']} <{LABEL_PREFIX}{m['name']}>`" if link else f"``{m['name']}``"
        body.append(
            [
                name,
                m["summary"],
                method_parameters(m),
                "precision" if m["tolerance_option"] else "budget",
                "yes" if m["supports_parallel"] else "no",
            ]
        )
    return _table(
        ["Method", "What it does", "Parameters", "Stops on", "Parallel"],
        body,
        "16 46 18 10 10",
    )


def option_rows(m: dict[str, Any]) -> list[list[str]]:
    rows = []
    for o in m["options"] or []:
        default = "required" if o["required"] else _literal(o["default"])
        rows.append([f"``{o['name']}``", o["type"], default, o["description"] or "\\-"])
    return rows


def method_section_rst(m: dict[str, Any]) -> str:
    title = f"``{m['name']}``"
    parts = [title, "~" * (len(title) + 2), "", m["summary"], ""]
    for paragraph in m["details"]:
        parts += [paragraph, ""]
    if not m["registered"]:
        parts += [
            "Not available in this build: its adapter could not be imported.",
            "",
        ]
    if m["options"] is None:
        parts += ["Its options are read by its own constructor.", ""]
    elif m["options"]:
        parts.append(
            "Options, written under :toml:`calibration.method_options` with "
            "``method`` beside them, or in the ``method_options`` of a phase:"
        )
        parts.append("")
        parts.append(
            _table(["Option", "Type", "Default", "What it sets"], option_rows(m), "18 16 14 52")
        )
    else:
        parts += ["It takes no option.", ""]
    for label, text in method_facts(m):
        parts.append(f"- **{label}:** {text}")
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------- metrics


def metrics_table_rst(rows: list[dict[str, Any]]) -> str:
    body = []
    for r in rows:
        supports = "network output" if r["reads_supports"] == ["network"] else "series output"
        body.append(
            [
                f"``{r['name']}``",
                r["family"],
                r["cost"],
                r["unit"],
                supports,
                "yes" if r["signed"] else "no",
                r["normalize_cost"],
            ]
        )
    return _table(
        [
            "Metric",
            "Family",
            "Cost minimised",
            "Unit of the cost",
            "Reads",
            "Signed",
            "``normalize_cost`` divides by",
        ],
        body,
        "14 14 12 14 14 8 24",
    )


def metrics_formulas_rst(rows: list[dict[str, Any]]) -> str:
    parts = []
    for r in rows:
        parts.append(f"``{r['name']}``")
        lines = [r["reads"] or "\\-", "", ".. math::", "", f"   {r['score']}", ""]
        if r["where"]:
            lines += [f"where :math:`{r['where']}`.", ""]
        if r["higher_is_better"]:
            lines.append("Higher is better; the search minimises one minus the score.")
        else:
            lines.append("Lower is better; the search minimises it as it is.")
        if r["note"]:
            lines += ["", r["note"]]
        parts += ["   " + line if line else "" for line in lines]
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------- directives


class _CatalogDirective(SphinxDirective):
    has_content = False

    def parse(self, text: str) -> list[nodes.Node]:
        doc = new_document(self.env.docname, self.state.document.settings)
        Parser().parse(text, doc)
        return list(doc.children)


class MethodsDirective(_CatalogDirective):
    """Every calibration method, from the optimizer registry."""

    option_spec = {"summary": directives.flag}

    def run(self) -> list[nodes.Node]:
        rows = payload()["methods"]
        if "summary" in self.options:
            return self.parse(methods_summary_rst(rows, link=True))
        out = self.parse(methods_summary_rst(rows, link=True))
        std = self.env.get_domain("std")
        for m in rows:
            parsed = self.parse(method_section_rst(m))
            for node in parsed:
                if isinstance(node, nodes.section) and node["ids"]:
                    std.note_hyperlink_target(
                        f"{LABEL_PREFIX}{m['name']}",
                        self.env.docname,
                        node["ids"][0],
                        m["name"],
                    )
            out += parsed
        return out


class MetricsDirective(_CatalogDirective):
    """Every calibration metric, from the metric kernels and their formulas."""

    option_spec = {"table": directives.flag, "formulas": directives.flag}

    def run(self) -> list[nodes.Node]:
        rows = payload()["metrics"]
        table = "table" in self.options
        formulas = "formulas" in self.options
        if not table and not formulas:
            table = formulas = True
        out: list[nodes.Node] = []
        if table:
            out += self.parse(metrics_table_rst(rows))
        if formulas:
            out += self.parse(metrics_formulas_rst(rows))
        return out


def _always_reread(app, env, added, changed, removed) -> list[str]:
    """The catalog comes from the code, not from the page: read the pages again."""
    return [doc for doc in PAGES if doc in env.found_docs]


def setup_calibration(app) -> None:
    app.add_directive("hmp-calibration-methods", MethodsDirective)
    app.add_directive("hmp-calibration-metrics", MetricsDirective)
    app.connect("env-get-outdated", _always_reread)
