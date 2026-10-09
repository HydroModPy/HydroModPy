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
- A raster image that has a ``<name>-dark.<ext>`` twin next to it is shown in
  both themes: the page writes the light one, this extension adds the dark one
  next to it (classes ``hmp-light`` and ``hmp-dark``, shown by hmp-site.css).
- Every image of the article gets its intrinsic ``width`` and ``height``, read
  from the file, so the browser reserves its box before it loads (no layout
  shift), and ``loading="lazy"`` unless it is the first image of the page.
- The glossary is written to ``_static/hmp-glossary.json`` for the hover card
  of the terms (``js/hmp-site.js`` over ``window.hmpHoverCard``).
- ``hmp-task`` opens every guide with the same box: one definition list of
  Task, Time, Needs and Gives, in that order. Another shape warns, so a strict
  build keeps the guides alike.
"""

from __future__ import annotations

import html
import json
import posixpath
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from docutils import nodes
from sphinx import addnodes
from sphinx.application import Sphinx
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

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
_RASTER = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_DARK = "-dark"
_IMG_TAG = re.compile(r"<img\b[^>]*>")
_ATTR = re.compile(r'\b(src|class|style|width|height|loading)="([^"]*)"')
_STYLE_PX = re.compile(r"\b(width|height):\s*([0-9.]+)px")
_SVG_ATTR = re.compile(r'\b(width|height|viewBox)="([^"]*)"')
_SIZES: dict[tuple[str, float], tuple[int, int] | None] = {}
logger = logging.getLogger(__name__)


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


def _local_raster(app: Sphinx, uri: str) -> Path | None:
    """The file of a local raster image URI written in the current document."""
    if "://" in uri or uri.startswith("data:"):
        return None
    _rel, absolute = app.env.relfn2path(unquote(uri), app.env.docname)
    path = Path(absolute)
    return path if path.suffix.lower() in _RASTER else None


def add_dark_twins(app: Sphinx, doctree: nodes.document) -> None:
    """Show an image in both themes when ``<name>-dark.<ext>`` sits next to it.

    A copy of the image that points to the twin is inserted right after the
    original (inside the same figure, so the caption is written once and the
    figure numbering does not move). The classes ``hmp-light`` and ``hmp-dark``
    let ``hmp-site.css`` show one of the two; ``dark-light`` tells the theme not
    to dim or whiten them. An image that carries ``only-light`` or ``only-dark``
    written by hand is left alone.
    """
    for image in list(doctree.findall(nodes.image)):
        classes = image.get("classes", [])
        if {"only-light", "only-dark", "hmp-light", "hmp-dark"} & set(classes):
            continue
        light = _local_raster(app, image["uri"])
        if light is None or light.stem.endswith(_DARK):
            continue
        if not light.with_name(light.stem + _DARK + light.suffix).is_file():
            continue
        uri, ext = image["uri"], light.suffix
        twin = image.deepcopy()
        twin["uri"] = uri[: len(uri) - len(ext)] + _DARK + uri[len(uri) - len(ext) :]
        image["classes"] += ["hmp-light", "dark-light"]
        twin["classes"] += ["hmp-dark", "dark-light"]
        image.parent.insert(image.parent.index(image) + 1, twin)


def _svg_size(path: Path) -> tuple[int, int] | None:
    head = path.read_text(encoding="utf-8", errors="ignore")[:2000]
    svg = re.search(r"<svg\b[^>]*>", head, re.S)
    if not svg:
        return None
    attrs = dict(_SVG_ATTR.findall(svg.group(0)))

    def px(value: str | None) -> float | None:
        match = re.fullmatch(r"\s*([0-9.]+)\s*(px)?\s*", value or "")
        return float(match.group(1)) if match else None

    width, height = px(attrs.get("width")), px(attrs.get("height"))
    if not (width and height) and attrs.get("viewBox"):
        parts = attrs["viewBox"].replace(",", " ").split()
        if len(parts) == 4:
            width, height = float(parts[2]), float(parts[3])
    return (round(width), round(height)) if width and height else None


def _file_size(path: Path) -> tuple[int, int] | None:
    key = (str(path), path.stat().st_mtime)
    if key not in _SIZES:
        try:
            if path.suffix.lower() == ".svg":
                _SIZES[key] = _svg_size(path)
            else:
                from PIL import Image

                with Image.open(path) as picture:
                    _SIZES[key] = picture.size
        except (OSError, ValueError, ImportError):
            _SIZES[key] = None
    return _SIZES[key]


def _image_path(app: Sphinx, pagename: str, src: str) -> Path | None:
    """Find the file behind the ``src`` of an image written in ``pagename``."""
    rel = posixpath.normpath(posixpath.join(posixpath.dirname(pagename), unquote(src)))
    builder = app.builder
    imgdir = getattr(builder, "imagedir", "_images")
    if rel.startswith(imgdir + "/"):
        name = rel[len(imgdir) + 1 :]
        for source, copied in getattr(builder, "images", {}).items():
            if copied == name:
                return Path(app.srcdir) / source
    for root in (Path(app.srcdir), Path(app.outdir)):
        if (root / rel).is_file():
            return root / rel
    return None


def size_images(app: Sphinx, pagename: str, body: str) -> str:
    """Give each ``<img>`` of the article its intrinsic size and lazy loading."""
    first = [True]

    def fix(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = dict(_ATTR.findall(tag))
        extra = ""
        if "width" not in attrs or "height" not in attrs:
            size = None
            src = attrs.get("src", "")
            if src.startswith("data:"):
                pass
            elif "://" in src:
                style = dict(_STYLE_PX.findall(attrs.get("style", "")))
                if "width" in style and "height" in style:
                    size = (round(float(style["width"])), round(float(style["height"])))
            else:
                path = _image_path(app, pagename, src)
                size = _file_size(path) if path is not None else None
            if size:
                extra += f' width="{size[0]}" height="{size[1]}"'
            else:
                logger.debug("image without a known size on %s: %s", pagename, src)
        # The first local image is the one the reader waits for: it loads at once.
        # A remote badge keeps the default.
        if "://" not in attrs.get("src", ""):
            if "loading" not in attrs and not first[0]:
                extra += ' loading="lazy" decoding="async"'
            first[0] = False
        close = "/>" if tag.endswith("/>") else ">"
        return tag[: -len(close)].rstrip() + extra + (" " + close if close == "/>" else close)

    return _IMG_TAG.sub(fix, body)


def write_glossary(app: Sphinx, exception: Exception | None) -> None:
    """Write ``_static/hmp-glossary.json``: one card per glossary anchor."""
    if exception is not None or app.builder.format != "html":
        return
    std = app.env.get_domain("std")
    documents = sorted({doc for (kind, _), (doc, _) in std.objects.items() if kind == "term"})
    cards: dict[str, dict[str, str]] = {}
    for docname in documents:
        for glossary in app.env.get_doctree(docname).findall(addnodes.glossary):
            for item in glossary.findall(nodes.definition_list_item):
                definition = item.next_node(nodes.definition)
                if definition is None:
                    continue
                paragraphs = [
                    " ".join(p.astext().split()) for p in definition.findall(nodes.paragraph)
                ]
                setting = next((t for t in paragraphs[1:] if t.startswith("In the file")), "")
                for term in item.findall(nodes.term):
                    card = {
                        "p": term.astext(),
                        "l": "glossary",
                        "s": paragraphs[0] if paragraphs else "",
                    }
                    if setting:
                        card["f"] = setting
                    for anchor in term["ids"]:
                        cards[anchor] = card
    target = Path(app.outdir) / "_static" / "hmp-glossary.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cards, ensure_ascii=False, separators=(",", ":")), "utf-8")


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
        context["body"] = size_images(app, pagename, context["body"])
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


class TaskDirective(SphinxDirective):
    """The box that opens a guide: Task, Time, Needs and Gives."""

    has_content = True
    TERMS = ("Task", "Time", "Needs", "Gives")

    def run(self) -> list[nodes.Node]:
        box = nodes.container(classes=["hmp-task"])
        self.state.nested_parse(self.content, self.content_offset, box)
        terms = tuple(term.astext() for term in box.findall(nodes.term))
        lists = [child for child in box.children if isinstance(child, nodes.definition_list)]
        if len(box.children) != 1 or len(lists) != 1 or terms != self.TERMS:
            logger.warning(
                "hmp-task holds one definition list of %s, in that order; found %s",
                ", ".join(self.TERMS),
                ", ".join(terms) or "none",
                location=(self.env.docname, self.lineno),
            )
        return [box]


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_css_file("css/hmp-site.css", priority=900)
    app.add_js_file("js/hmp-site.js", defer="defer")
    app.add_directive("hmp-task", TaskDirective)
    app.connect("doctree-read", add_dark_twins, priority=400)
    app.connect("html-page-context", on_page_context)
    app.connect("build-finished", write_glossary)
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
