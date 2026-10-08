"""Site chrome the theme does not give.

- The image-comparison slider, the UML viewer and the image lightbox load only
  on the pages that use them, not on all 300 pages.
- Previous and next links stay inside a door: the link from the last guide to
  the first reference page means nothing to a reader.
"""

from __future__ import annotations

from typing import Any

from docutils import nodes
from sphinx.application import Sphinx

_RELATIONS: dict[str, list[str | None]] = {}


def _door(docname: str | None) -> str | None:
    return docname.split("/", 1)[0] if docname else None


def _has_slider(doctree: nodes.document) -> bool:
    return any("hmp-image-compare" in n.astext() for n in doctree.findall(nodes.raw))


def _has_uml(doctree: nodes.document) -> bool:
    return any(
        type(n).__name__ == "plantuml" or "uml-diagram" in n.get("classes", [])
        for n in doctree.findall(nodes.Element)
    )


def on_page_context(
    app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree
) -> None:
    # Called during html-page-context, add_*_file applies to this page only.
    if doctree is not None:
        if _has_slider(doctree):
            app.add_css_file("css/hmp-image-compare.css")
            app.add_js_file("js/hmp-image-compare.js")
        if _has_uml(doctree):
            app.add_css_file("uml-diagrams.css")
            app.add_js_file("uml-diagrams.js")
        if doctree.next_node(nodes.figure) is not None:
            app.add_css_file("css/hmp-zoom-image.css")
            app.add_js_file("js/hmp-zoom-image.js")
    if not _RELATIONS:
        _RELATIONS.update(app.env.collect_relations())
    _parent, prev_doc, next_doc = (_RELATIONS.get(pagename) or [None, None, None])[:3]
    door = _door(pagename)
    if context.get("prev") and _door(prev_doc) != door:
        context["prev"] = None
    if context.get("next") and _door(next_doc) != door:
        context["next"] = None


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_css_file("css/hmp-site.css", priority=900)
    app.add_js_file("js/hmp-site.js", defer="defer")
    app.connect("html-page-context", on_page_context)
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
