"""Custom Sphinx directives and roles for HydroModPy documentation.

Five directives:

- ``.. config-field:: <dotted.path>`` renders the matching Pydantic
  ``Field`` metadata as an admonition (default, description, type).
- ``.. validation-case-summary:: <slug>`` reads the summary JSON of a
  validation gallery case and renders a fact card with metrics.
- ``.. solver-comparison::`` renders a solver x case matrix listing the
  primary RMSE metric for each cell.
- ``.. gallery-figure:: <png_path>`` emits a ``<picture>`` block with a
  WebP source and a PNG fallback for the gallery figures (HTML builder
  only). Other builders fall back to the plain PNG ``figure``.
- ``.. image-comparison::`` renders a draggable before/after slider over
  two images (HTML builder only). Falls back to two stacked figures.

Three API stability roles:

- ``:stable:`` (green badge): public API covered by SemVer guarantees.
- ``:experimental:`` (orange badge): public surface that may change
  between minor versions.
- ``:deprecated:`` (red badge): scheduled for removal; pair with the
  removal version in the badge text.

Optional analytics:

- Set ``HMP_DOCS_GOATCOUNTER_URL`` to the GoatCounter ``count`` endpoint
  (for example ``https://hydromodpy.goatcounter.com/count``) to enable
  page-view tracking and the "Was this page helpful?" widget. The widget
  always renders, but only pushes events to GoatCounter when the script
  has loaded.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx import addnodes
from sphinx.application import Sphinx
from sphinx.util.docutils import SphinxDirective

_VALIDATION_GLOB = "_static/capability_gallery/validation"
_GOATCOUNTER_ENV = "HMP_DOCS_GOATCOUNTER_URL"


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
            para += nodes.Text("Field not resolvable. Check the dotted path against ")
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
        solver_filter = {s.strip() for s in self.options.get("solvers", "").split(",") if s.strip()}

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


def _webp_path_for(png_path: str) -> str:
    name = png_path.rsplit("/", 1)[-1]
    if "." in name:
        return png_path.rsplit(".", 1)[0] + ".webp"
    return png_path + ".webp"


def _escape_attr(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_text(value: str) -> str:
    return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class GalleryFigureDirective(SphinxDirective):
    """Render a gallery figure as a ``<picture>`` block with a PNG fallback.

    Emits raw HTML for the HTML builder (the only published target). Other
    builders fall back to a standard ``image`` node pointing at the PNG.
    """

    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    has_content = True
    option_spec = {
        "alt": directives.unchanged,
        "width": directives.length_or_percentage_or_unitless,
    }

    def run(self) -> list[nodes.Node]:
        png_path = self.arguments[0].strip()
        webp_path = _webp_path_for(png_path)
        alt = self.options.get("alt", "")
        width = self.options.get("width", "100%")
        caption = "\n".join(self.content).strip()

        style_attr = f' style="width: {width};"' if width else ""
        figcaption = f"<figcaption>{_escape_text(caption)}</figcaption>" if caption else ""
        html = (
            '<figure class="hmp-gallery-figure">'
            "<picture>"
            f'<source srcset="{_escape_attr(webp_path)}" type="image/webp">'
            f'<img src="{_escape_attr(png_path)}" alt="{_escape_attr(alt)}"'
            f'{style_attr} loading="lazy">'
            "</picture>"
            f"{figcaption}"
            "</figure>"
        )
        html_node = nodes.raw("", html, format="html")

        image_node = nodes.image(uri=png_path, alt=alt)
        if width:
            image_node["width"] = width
        fallback = nodes.figure(classes=["hmp-gallery-figure-fallback"])
        fallback += image_node
        if caption:
            fallback += nodes.caption("", caption)
        fallback_only = addnodes.only(expr="not html")
        fallback_only += fallback

        return [html_node, fallback_only]


class ImageComparisonDirective(SphinxDirective):
    """Render a draggable before/after image-comparison slider."""

    required_arguments = 0
    optional_arguments = 0
    final_argument_whitespace = False
    has_content = False
    option_spec = {
        "before": directives.unchanged_required,
        "after": directives.unchanged_required,
        "before-label": directives.unchanged,
        "after-label": directives.unchanged,
        "before-alt": directives.unchanged,
        "after-alt": directives.unchanged,
        "caption": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        before = self.options.get("before", "").strip()
        after = self.options.get("after", "").strip()
        if not before or not after:
            warning = self.state.document.reporter.warning(
                "image-comparison: options :before: and :after: are required",
                line=self.lineno,
            )
            return [warning]

        before_label = self.options.get("before-label", "")
        after_label = self.options.get("after-label", "")
        before_alt = self.options.get("before-alt", before_label or "Before")
        after_alt = self.options.get("after-alt", after_label or "After")
        caption = self.options.get("caption", "")

        before_html = (
            f'<picture class="hmp-before"><source srcset="{_escape_attr(_webp_path_for(before))}" type="image/webp">'
            f'<img src="{_escape_attr(before)}" alt="{_escape_attr(before_alt)}" loading="lazy"></picture>'
        )
        after_html = (
            f'<picture class="hmp-after"><source srcset="{_escape_attr(_webp_path_for(after))}" type="image/webp">'
            f'<img src="{_escape_attr(after)}" alt="{_escape_attr(after_alt)}" loading="lazy"></picture>'
        )
        labels_html = ""
        if before_label:
            labels_html += (
                f'<span class="hmp-image-compare-label hmp-image-compare-label-before">'
                f"{_escape_text(before_label)}</span>"
            )
        if after_label:
            labels_html += (
                f'<span class="hmp-image-compare-label hmp-image-compare-label-after">'
                f"{_escape_text(after_label)}</span>"
            )
        figcaption = f"<figcaption>{_escape_text(caption)}</figcaption>" if caption else ""
        html = (
            '<figure class="hmp-image-compare-figure">'
            '<div class="hmp-image-compare">'
            f"{before_html}{after_html}{labels_html}"
            "</div>"
            f"{figcaption}"
            "</figure>"
        )
        html_node = nodes.raw("", html, format="html")

        fallback = nodes.container(classes=["hmp-image-compare-fallback"])
        for path, alt, label in (
            (before, before_alt, before_label),
            (after, after_alt, after_label),
        ):
            sub_figure = nodes.figure()
            image = nodes.image(uri=path, alt=alt)
            image["width"] = "100%"
            sub_figure += image
            if label:
                sub_figure += nodes.caption("", label)
            fallback += sub_figure
        if caption:
            fallback += nodes.paragraph("", caption)
        fallback_only = addnodes.only(expr="not html")
        fallback_only += fallback

        return [html_node, fallback_only]


def _stability_role(label: str, css_class: str):
    def role(name, rawtext, text, lineno, inliner, options=None, content=None):
        node = nodes.inline(
            rawtext,
            f"{label}{(': ' + text) if text else ''}",
            classes=["api-stability", css_class],
        )
        return [node], []

    return role


def _register_goatcounter(app: Sphinx) -> None:
    """Inject the GoatCounter snippet when the environment variable is set."""
    url = os.environ.get(_GOATCOUNTER_ENV, "").strip()
    if not url:
        return
    app.add_js_file(
        "https://gc.zgo.at/count.js",
        priority=900,
        loading_method="async",
        **{"data-goatcounter": url},
    )


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_directive("config-field", ConfigFieldDirective)
    app.add_directive("validation-case-summary", ValidationCaseSummaryDirective)
    app.add_directive("solver-comparison", SolverComparisonDirective)
    app.add_directive("gallery-figure", GalleryFigureDirective)
    app.add_directive("image-comparison", ImageComparisonDirective)
    app.add_role("stable", _stability_role("Stable", "api-stable"))
    app.add_role("experimental", _stability_role("Experimental", "api-experimental"))
    app.add_role("deprecated", _stability_role("Deprecated", "api-deprecated"))
    _register_goatcounter(app)
    return {"version": "0.5.0", "parallel_read_safe": True, "parallel_write_safe": True}
