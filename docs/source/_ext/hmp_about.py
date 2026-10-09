"""Directives of the About pages: the citation entries, the authors and the studies.

- ``{hmp-citation} bibtex|ris|text`` prints the entries that ``tools/docs/citation.py``
  writes from ``CITATION.cff``, with the version the site is built from.
- ``{hmp-authors}`` prints the authors of ``CITATION.cff`` with the affiliations of
  ``about/affiliations.yaml``.
- ``{hmp-studies}`` prints the studies of ``about/applications.yaml``, each one
  described by its entry of ``theory/references.bib``.

Nothing is typed twice. A wrong author is fixed in ``CITATION.cff``, a wrong paper in
``references.bib``, a study that is missing in ``applications.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from docutils import nodes
from sphinx.application import Sphinx
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

from tools.docs import citation

LOG = logging.getLogger(__name__)
CHANGELOG = "CHANGELOG.md"
REFERENCES = "theory/references.bib"


def repo_root(srcdir: str | Path) -> Path:
    """The checkout that holds ``docs/source``."""
    return Path(srcdir).resolve().parents[1]


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def bib_entries(path: Path) -> dict[str, Any]:
    """The entries of a BibTeX file, by key."""
    from pybtex.database import parse_file

    return dict(parse_file(str(path), bib_format="bibtex").entries)


def plain(text: str) -> str:
    """A BibTeX field as plain text: accents and braces resolved."""
    return citation.untex(text)


def author_list(entry: Any) -> str:
    """``Abhervé et al.`` or ``Marti, Leray and Roques``."""
    names = [plain(" ".join(p.prelast_names + p.last_names)) for p in entry.persons["author"]]
    if len(names) > 2:
        return f"{names[0]} et al."
    return " and ".join(names)


def link(text: str, uri: str) -> nodes.reference:
    return nodes.reference(text, text, refuri=uri)


class CitationDirective(SphinxDirective):
    """The technical note and the software in one format, ready to copy."""

    required_arguments = 1
    final_argument_whitespace = False

    def run(self) -> list[nodes.Node]:
        fmt = self.arguments[0]
        if fmt not in citation.FORMATS:
            return [self.state_machine.reporter.error(f"unknown citation format: {fmt}")]
        root = repo_root(self.env.srcdir)
        cff_path = root / "CITATION.cff"
        changelog = root / CHANGELOG
        self.env.note_dependency(str(cff_path))
        self.env.note_dependency(str(changelog))
        year = citation.release_year(
            changelog.read_text(encoding="utf-8") if changelog.exists() else "",
            self.config.release,
        )
        body = citation.render(fmt, citation.load(cff_path), self.config.release, year)
        block = nodes.literal_block(body, body.rstrip("\n"))
        block["language"] = {"bibtex": "bibtex", "ris": "text", "text": "text"}[fmt]
        return [block]


class AuthorsDirective(SphinxDirective):
    """The authors of CITATION.cff and their affiliations."""

    def run(self) -> list[nodes.Node]:
        root = repo_root(self.env.srcdir)
        cff_path = root / "CITATION.cff"
        data_path = Path(self.env.srcdir) / "about" / "affiliations.yaml"
        self.env.note_dependency(str(cff_path))
        self.env.note_dependency(str(data_path))
        people = citation.authors(citation.load(cff_path))
        data = read_yaml(data_path)
        numbers: dict[str, list[int]] = data.get("authors", {})
        institutions: dict[int, str] = data.get("institutions", {})
        for family, given in people:
            if family not in numbers:
                LOG.warning("%s %s has no affiliation in about/affiliations.yaml", given, family)
        used = sorted({n for ns in numbers.values() for n in ns})
        for n in used:
            if n not in institutions:
                LOG.warning("affiliation %s is not defined in about/affiliations.yaml", n)

        names = nodes.paragraph()
        for i, (family, given) in enumerate(people):
            if i:
                names += nodes.Text(", ")
            names += nodes.Text(f"{citation.initials(given)} {family}")
            sup = nodes.superscript(text=",".join(str(n) for n in numbers.get(family, [])))
            names += sup
        names += nodes.Text(".")

        listing = nodes.bullet_list()
        for n in used:
            item = nodes.list_item()
            para = nodes.paragraph()
            para += nodes.superscript(text=str(n))
            para += nodes.Text(f" {institutions.get(n, '')}")
            item += para
            listing += item
        return [names, listing]


class StudiesDirective(SphinxDirective):
    """The studies of applications.yaml, newest first."""

    def run(self) -> list[nodes.Node]:
        data_path = Path(self.env.srcdir) / "about" / "applications.yaml"
        bib_path = Path(self.env.srcdir) / REFERENCES
        self.env.note_dependency(str(data_path))
        self.env.note_dependency(str(bib_path))
        studies = read_yaml(data_path).get("studies", [])
        entries = bib_entries(bib_path)

        rows: list[tuple[str, Any, str]] = []
        for study in studies:
            key = study["bib"]
            if key not in entries:
                LOG.warning("applications.yaml: %s is not in %s", key, REFERENCES)
                continue
            rows.append((key, entries[key], study["use"].strip()))
        rows.sort(key=lambda r: -int(r[1].fields.get("year", 0)))

        table = nodes.table()
        group = nodes.tgroup(cols=2)
        table += group
        for width in (45, 55):
            group += nodes.colspec(colwidth=width)
        head = nodes.thead()
        head_row = nodes.row()
        for label in ("Paper", "What HydroModPy did"):
            head_row += nodes.entry("", nodes.paragraph(text=label))
        head += head_row
        group += head
        body = nodes.tbody()
        group += body
        for _key, entry, use in rows:
            body += self.row(entry, use)
        return [table]

    @staticmethod
    def row(entry: Any, use: str) -> nodes.row:
        fields = entry.fields
        cite = nodes.paragraph()
        cite += nodes.strong(text=f"{author_list(entry)} ({fields.get('year', 'n.d.')})")
        cite += nodes.Text(f". {plain(fields.get('title', ''))}. ")
        cite += nodes.emphasis(text=plain(fields.get("journal", "")))
        if fields.get("doi"):
            cite += nodes.Text(". ")
            cite += link(f"doi:{fields['doi']}", f"https://doi.org/{fields['doi']}")
        row = nodes.row()
        row += nodes.entry("", cite)
        row += nodes.entry("", nodes.paragraph(text=use))
        return row


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_directive("hmp-citation", CitationDirective)
    app.add_directive("hmp-authors", AuthorsDirective)
    app.add_directive("hmp-studies", StudiesDirective)
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
