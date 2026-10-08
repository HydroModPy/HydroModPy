"""Site chrome the theme does not give.

- The image-comparison slider, the UML viewer and the image lightbox load only
  on the pages that use them, not on all 300 pages.
- Previous and next links stay inside a door: the link from the last guide to
  the first reference page means nothing to a reader.
- Pagefind indexes the article of each page only, with its door as a filter;
  the parameter explorer and the general index stay out of the search.
- A UML diagram is described by its title, not by its whole PlantUML source,
  which sphinxcontrib-plantuml puts in the alt text (read aloud by screen
  readers and indexed by the search).
"""

from __future__ import annotations

import html
import re
from typing import Any

from docutils import nodes
from sphinx.application import Sphinx

_RELATIONS: dict[str, list[str | None]] = {}
_DOORS = {
    "index": "Home",
    "understand": "Understand",
    "get-started": "Get started",
    "guides": "Guides",
    "reference": "Reference",
    "theory": "Theory",
    "contribute": "Contribute",
    "about": "About",
}
_NOT_SEARCHED = {"genindex", "search", "reference/parameters/explorer"}
_UML_ALT = re.compile(r'alt="(?:&#64;|@)startuml(.*?)"', re.S)


def _uml_alt(match: re.Match[str]) -> str:
    title = re.search(r"^\s*title\s+(.+)$", html.unescape(match.group(1)), re.M)
    return f'alt="{html.escape(title.group(1).strip()) if title else "UML diagram"}"'


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
    if "body" in context:
        context["body"] = _UML_ALT.sub(_uml_alt, context["body"])
    door_title = _DOORS.get(_door(pagename) or "")
    if "body" in context and door_title and pagename not in _NOT_SEARCHED:
        # Contributor pages weigh less in the ranking: a user query should land on
        # a guide or a reference page before an architecture note. Pagefind reads
        # the weight on an element inside the indexed body, not on the body itself.
        body = context["body"]
        if door_title == "Contribute":
            body = f'<div data-pagefind-weight="0.3">{body}</div>'
        context["body"] = (
            f'<div data-pagefind-body><span data-pagefind-filter="door:{door_title}" hidden></span>'
            f"{body}</div>"
        )
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
