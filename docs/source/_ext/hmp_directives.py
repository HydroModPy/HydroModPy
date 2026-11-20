"""Custom Sphinx directive for HydroModPy documentation, and optional analytics.

- ``.. image-comparison::`` renders a draggable before/after slider over two
  images (HTML builder only). Other builders get two stacked figures.
- Set ``HMP_DOCS_GOATCOUNTER_URL`` to the GoatCounter ``count`` endpoint (for
  example ``https://hydromodpy.goatcounter.com/count``) to enable page-view
  tracking.
"""

from __future__ import annotations

import os
from typing import Any

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx import addnodes
from sphinx.application import Sphinx
from sphinx.util.docutils import SphinxDirective

_GOATCOUNTER_ENV = "HMP_DOCS_GOATCOUNTER_URL"


def _doc_relative_uri(env: Any, path: str) -> str:
    # Convert a source-root absolute path (/_static/...) to a path relative
    # to the current doc so raw <img src=...> works when the docs are served
    # under a sub-path (versioned folders, file://, GH Pages).
    if not path.startswith("/"):
        return path
    depth = env.docname.count("/")
    return ("../" * depth) + path.lstrip("/")


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

        before_uri = _doc_relative_uri(self.env, before)
        after_uri = _doc_relative_uri(self.env, after)
        before_html = (
            f'<img class="hmp-before" src="{_escape_attr(before_uri)}" '
            f'alt="{_escape_attr(before_alt)}" loading="lazy">'
        )
        after_html = (
            f'<img class="hmp-after" src="{_escape_attr(after_uri)}" '
            f'alt="{_escape_attr(after_alt)}" loading="lazy">'
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
    app.add_directive("image-comparison", ImageComparisonDirective)
    _register_goatcounter(app)
    return {"version": "0.7.0", "parallel_read_safe": True, "parallel_write_safe": True}
