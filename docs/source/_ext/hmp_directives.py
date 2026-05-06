"""Custom Sphinx directives for HydroModPy documentation.

Three directives:

- ``.. config-field:: <dotted.path>`` renders the matching Pydantic
  ``Field`` metadata as an admonition (default, description, type).
- ``.. validation-case-summary:: <slug>`` reads the summary JSON of a
  validation gallery case and renders a fact card with metrics.
- ``.. solver-comparison::`` renders a solver x case matrix listing the
  primary RMSE metric for each cell.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.application import Sphinx
from sphinx.util.docutils import SphinxDirective

_VALIDATION_GLOB = "_static/capability_gallery/validation"


def _resolve_field(dotted_path: str) -> dict[str, Any] | None:
    """Look up a Pydantic field by dotted path on HydroModPyConfig."""
    try:
        from hydromodpy.config import HydroModPyConfig
    except Exception:
        return None

    parts = dotted_path.split(".")
    model: Any = HydroModPyConfig
    for part in parts[:-1]:
        fields = getattr(model, "model_fields", None)
        if not fields or part not in fields:
            return None
        annotation = fields[part].annotation
        model = _unwrap_annotation(annotation)
        if model is None:
            return None

    fields = getattr(model, "model_fields", None)
    if not fields or parts[-1] not in fields:
        return None
    info = fields[parts[-1]]
    return {
        "annotation": str(info.annotation),
        "default": "..." if info.is_required() else repr(info.default),
        "description": info.description or "",
    }


def _unwrap_annotation(annotation: Any) -> Any:
    origin = getattr(annotation, "__origin__", None)
    if origin is None:
        return annotation
    args = getattr(annotation, "__args__", ())
    for arg in args:
        if hasattr(arg, "model_fields"):
            return arg
    return None


class ConfigFieldDirective(SphinxDirective):
    """Render a Pydantic Field by dotted path."""

    required_arguments = 1
    optional_arguments = 0
    has_content = False
    option_spec = {
        "unit": directives.unchanged,
        "default": directives.unchanged,
        "see-also-cases": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        dotted = self.arguments[0]
        info = _resolve_field(dotted)
        admon = nodes.admonition(classes=["config-field"])
        title = nodes.title(text=f"Config field: {dotted}")
        admon += title

        if info is None:
            para = nodes.paragraph()
            para += nodes.Text(
                "Field not resolvable. Check the dotted path against "
            )
            para += nodes.literal(text="HydroModPyConfig.model_fields")
            para += nodes.Text(".")
            admon += para
            return [admon]

        rows = [
            ("Type", info["annotation"]),
            ("Default", self.options.get("default") or info["default"]),
        ]
        unit = self.options.get("unit")
        if unit:
            rows.append(("Unit", unit))
        if info["description"]:
            rows.append(("Description", info["description"]))
        cases = self.options.get("see-also-cases")
        if cases:
            rows.append(("See also cases", cases))

        for label, value in rows:
            para = nodes.paragraph()
            para += nodes.strong(text=f"{label}: ")
            para += nodes.Text(str(value))
            admon += para

        return [admon]


def _validation_dir(env: Any) -> Path:
    return Path(env.srcdir) / _VALIDATION_GLOB


class ValidationCaseSummaryDirective(SphinxDirective):
    """Render a validation case summary card from its summary JSON."""

    required_arguments = 1
    optional_arguments = 0
    has_content = False
    option_spec = {
        "show-metrics": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        slug = self.arguments[0]
        summary_path = _validation_dir(self.env) / f"{slug}_summary.json"
        if not summary_path.exists():
            warning = self.state.document.reporter.warning(
                f"validation-case-summary: missing summary JSON for slug {slug!r} at {summary_path}",
                line=self.lineno,
            )
            return [warning]
        data = json.loads(summary_path.read_text())

        admon = nodes.admonition(classes=["validation-case-summary"])
        admon += nodes.title(text=data.get("title", slug))

        meta = data.get("metadata", {})
        info_lines = [
            ("Regime", meta.get("regime", "n/a")),
            ("Dimension", meta.get("dimension", "n/a")),
            ("Reference", meta.get("reference_type_label", "n/a")),
            (
                "Solvers tested",
                ", ".join(meta.get("solver_variants", []) or ["n/a"]),
            ),
        ]
        for label, value in info_lines:
            para = nodes.paragraph()
            para += nodes.strong(text=f"{label}: ")
            para += nodes.Text(str(value))
            admon += para

        runs = data.get("solver_runs", [])
        if runs:
            metrics_para = nodes.paragraph()
            metrics_para += nodes.strong(text="Primary metrics: ")
            admon += metrics_para
            bullet = nodes.bullet_list()
            for run in runs:
                lines = run.get("metric_lines", []) or []
                summary = "; ".join(lines) if lines else "no metrics recorded"
                item = nodes.list_item()
                para = nodes.paragraph()
                para += nodes.literal(text=run.get("solver", "?"))
                para += nodes.Text(f": {summary}")
                item += para
                bullet += item
            admon += bullet

        return [admon]


class SolverComparisonDirective(SphinxDirective):
    """Render a solver x case matrix listing primary RMSE per cell."""

    required_arguments = 0
    optional_arguments = 0
    has_content = False
    option_spec = {
        "cases": directives.unchanged_required,
        "solvers": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        cases_opt = self.options.get("cases", "")
        case_slugs = [s.strip() for s in cases_opt.split(",") if s.strip()]
        if not case_slugs:
            warning = self.state.document.reporter.warning(
                "solver-comparison: option :cases: is required and must list one or more slugs",
                line=self.lineno,
            )
            return [warning]
        solver_filter = {
            s.strip() for s in self.options.get("solvers", "").split(",") if s.strip()
        }

        rows: list[dict[str, Any]] = []
        all_solvers: list[str] = []
        seen: set[str] = set()
        for slug in case_slugs:
            path = _validation_dir(self.env) / f"{slug}_summary.json"
            if not path.exists():
                continue
            data = json.loads(path.read_text())
            row: dict[str, Any] = {"title": data.get("title", slug), "slug": slug, "cells": {}}
            for run in data.get("solver_runs", []):
                solver = run.get("solver", "?")
                if solver_filter and solver not in solver_filter:
                    continue
                if solver not in seen:
                    all_solvers.append(solver)
                    seen.add(solver)
                primary = (run.get("metric_lines") or ["n/a"])[0]
                row["cells"][solver] = primary
            rows.append(row)

        if not rows:
            warning = self.state.document.reporter.warning(
                "solver-comparison: none of the listed slugs resolved to a summary JSON",
                line=self.lineno,
            )
            return [warning]

        table = nodes.table(classes=["solver-comparison"])
        tgroup = nodes.tgroup(cols=1 + len(all_solvers))
        table += tgroup
        for _ in range(1 + len(all_solvers)):
            tgroup += nodes.colspec(colwidth=1)

        thead = nodes.thead()
        header_row = nodes.row()
        header_row += _entry("Case")
        for solver in all_solvers:
            header_row += _entry(solver)
        thead += header_row
        tgroup += thead

        tbody = nodes.tbody()
        for row in rows:
            r = nodes.row()
            r += _entry(row["title"])
            for solver in all_solvers:
                r += _entry(row["cells"].get(solver, ""))
            tbody += r
        tgroup += tbody

        return [table]


def _entry(text: str) -> nodes.entry:
    cell = nodes.entry()
    cell += nodes.paragraph(text=text)
    return cell


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_directive("config-field", ConfigFieldDirective)
    app.add_directive("validation-case-summary", ValidationCaseSummaryDirective)
    app.add_directive("solver-comparison", SolverComparisonDirective)
    return {"version": "0.1.0", "parallel_read_safe": True, "parallel_write_safe": True}
