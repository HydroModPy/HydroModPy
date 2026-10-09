"""Citation entries of the documentation, written from ``CITATION.cff``.

Usage: python -m tools.docs.citation [bibtex|ris|text] [--version X] [--cff PATH]

The Cite page asks for the entries at build time. Nothing is copied by hand: the
authors, the title and the DOI of the technical note come from the file that
GitHub also reads behind "Cite this repository", and the version is the one the
site is built from. Two entries come out in each format: the technical note
(``preferred-citation``) and the software at a given version.
"""

from __future__ import annotations

import argparse
import re
import textwrap
import unicodedata
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
FORMATS = ("bibtex", "ris", "text")
RELEASE_LINE = re.compile(r"^## \[v?(?P<version>[^\]]+)\]\s*-\s*(?P<date>\d{4}-\d{2}-\d{2})\s*$")

# TeX accent commands for the combining marks that occur in names and titles.
_TEX_ACCENT = {
    "́": "'",
    "̀": "`",
    "̂": "^",
    "̈": '"',
    "̃": "~",
    "̄": "=",
}
_TEX_LETTER_ACCENT = {"̧": "c", "̌": "v", "̆": "u", "̊": "r"}
_TEX_SPECIAL = {"–": "--", "—": "---", "ß": r"{\ss}", "ø": r"{\o}"}


def load(path: Path | None = None) -> dict[str, Any]:
    """Parse ``CITATION.cff``."""
    path = path or ROOT / "CITATION.cff"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def release_year(changelog: str, version: str) -> str | None:
    """Year of ``version`` in the changelog headings, or None for an unreleased version."""
    for line in changelog.splitlines():
        match = RELEASE_LINE.match(line)
        if match and match["version"] == version:
            return match["date"][:4]
    return None


def tex(text: str) -> str:
    """Escape non-ASCII letters for classic BibTeX: ``Abhervé`` becomes ``Abherv{\\'e}``."""
    out: list[str] = []
    for char in text:
        if char in _TEX_SPECIAL:
            out.append(_TEX_SPECIAL[char])
            continue
        base, *marks = unicodedata.normalize("NFD", char)
        if not marks:
            out.append(char)
            continue
        mark = marks[0]
        if mark in _TEX_ACCENT:
            out.append(
                "{\\" + _TEX_ACCENT[mark] + (base if base not in "ij" else "\\" + base) + "}"
            )
        elif mark in _TEX_LETTER_ACCENT:
            out.append("{\\" + _TEX_LETTER_ACCENT[mark] + " " + base + "}")
        else:
            out.append(char)
    return "".join(out)


_TEX_UNACCENT = {v: k for k, v in _TEX_ACCENT.items()} | {
    "c": "\u0327",
    "v": "\u030c",
    "u": "\u0306",
    "r": "\u030a",
}
_TEX_COMMAND = re.compile(r"\\(?P<cmd>['`^\"~=]|[cvur](?=\s|\{))\s*\{?(?P<arg>\\?[A-Za-z])\}?")


def untex(text: str) -> str:
    """Read a BibTeX field as plain text: ``Abherv{\\'e}`` becomes ``Abhervé``."""

    def accent(match: re.Match[str]) -> str:
        letter = match["arg"].lstrip("\\")
        return unicodedata.normalize("NFC", letter + _TEX_UNACCENT[match["cmd"]])

    text = _TEX_COMMAND.sub(accent, text)
    return text.replace("{", "").replace("}", "").replace("--", "\u2013")


def authors(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """``(family, given)`` of every author of a CFF entry, in order."""
    return [(a["family-names"], a.get("given-names", "")) for a in entry["authors"]]


def initials(given: str) -> str:
    """``Jean-Raynald`` gives ``J.-R.`` and ``Rock S.`` gives ``R. S.``."""
    words = []
    for word in given.split():
        words.append("-".join(part[0] + "." for part in word.split("-") if part))
    return " ".join(words)


def _name_list(people: list[tuple[str, str]]) -> str:
    return " and ".join(f"{family}, {given}" if given else family for family, given in people)


def _text_names(people: list[tuple[str, str]]) -> str:
    names = [f"{family}, {initials(given)}" if given else family for family, given in people]
    if len(names) > 1:
        return ", ".join(names[:-1]) + ", & " + names[-1]
    return names[0]


def _fields(pairs: list[tuple[str, str | None]]) -> str:
    kept = [(key, value) for key, value in pairs if value]
    width = max(len(key) for key, _ in kept)
    indent = " " * (width + 6)
    rows = []
    for key, value in kept:
        body = "\n".join(
            textwrap.wrap(tex(str(value)), 80, subsequent_indent=indent, break_on_hyphens=False)
        )
        rows.append(f"  {key.ljust(width)} = {{{body}}}")
    return ",\n".join(rows)


def _doi_key(doi: str) -> str:
    return doi.rsplit("/", 1)[-1]


def note(cff: dict[str, Any]) -> dict[str, Any]:
    """The technical note, as a flat record."""
    pref = cff["preferred-citation"]
    return {
        "title": pref["title"],
        "authors": authors(pref),
        "journal": pref.get("journal"),
        "year": str(pref["year"]),
        "volume": str(pref["volume"]) if pref.get("volume") else None,
        "pages": (pref.get("start"), pref.get("end")),
        "doi": pref.get("doi"),
        "url": pref.get("url"),
    }


def software(cff: dict[str, Any], version: str, year: str | None) -> dict[str, Any]:
    """The software at ``version``, as a flat record."""
    return {
        "title": cff["title"],
        "authors": authors(cff),
        "version": version,
        "year": year,
        "url": cff["repository-code"],
        "license": cff.get("license"),
    }


def bibtex(cff: dict[str, Any], version: str, year: str | None = None) -> str:
    """BibTeX for the technical note then the software."""
    n, s = note(cff), software(cff, version, year)
    start, end = n["pages"]
    pages = f"{start}--{end}" if start and end else None
    article = _fields(
        [
            ("title", n["title"]),
            ("author", _name_list(n["authors"])),
            ("journal", n["journal"]),
            ("volume", n["volume"]),
            ("year", n["year"]),
            ("pages", pages),
            ("doi", n["doi"]),
            ("url", n["url"]),
        ]
    )
    soft = _fields(
        [
            ("title", s["title"]),
            ("author", _name_list(s["authors"])),
            ("version", s["version"]),
            ("year", s["year"]),
            ("url", s["url"]),
            ("license", s["license"]),
        ]
    )
    key = _doi_key(n["doi"]) if n["doi"] else "hydromodpy_note"
    return f"@article{{{key},\n{article}\n}}\n\n@software{{hydromodpy_software,\n{soft}\n}}\n"


def ris(cff: dict[str, Any], version: str, year: str | None = None) -> str:
    """RIS for the technical note then the software."""
    n, s = note(cff), software(cff, version, year)
    lines = ["TY  - JOUR", f"TI  - {n['title']}"]
    lines += [f"AU  - {f}, {g}" if g else f"AU  - {f}" for f, g in n["authors"]]
    start, end = n["pages"]
    for tag, value in (
        ("JO", n["journal"]),
        ("PY", n["year"]),
        ("VL", n["volume"]),
        ("SP", start),
        ("EP", end),
        ("DO", n["doi"]),
        ("UR", n["url"]),
    ):
        if value:
            lines.append(f"{tag}  - {value}")
    lines += ["ER  - ", "", "TY  - COMP", f"TI  - {s['title']}"]
    lines += [f"AU  - {f}, {g}" if g else f"AU  - {f}" for f, g in s["authors"]]
    for tag, value in (
        ("ET", s["version"]),
        ("PY", s["year"]),
        ("UR", s["url"]),
        ("N1", f"License: {s['license']}" if s["license"] else None),
    ):
        if value:
            lines.append(f"{tag}  - {value}")
    lines.append("ER  - ")
    return "\n".join(lines) + "\n"


def text(cff: dict[str, Any], version: str, year: str | None = None) -> str:
    """Plain-text references (author-year) for the technical note then the software."""
    n, s = note(cff), software(cff, version, year)
    start, end = n["pages"]
    pages = f", {start}–{end}" if start and end else ""
    doi = f" https://doi.org/{n['doi']}" if n["doi"] else f" {n['url']}"
    article = (
        f"{_text_names(n['authors'])} ({n['year']}). {n['title']}. {n['journal']}{pages}.{doi}"
    )
    soft = (
        f"{_text_names(s['authors'])} ({s['year'] or 'n.d.'}). {s['title']} "
        f"(Version {s['version']}) [Computer software]. {s['license']}. {s['url']}"
    )
    wrap = lambda t: textwrap.fill(t, 88, break_on_hyphens=False, break_long_words=False)  # noqa: E731
    return wrap(article) + "\n\n" + wrap(soft) + "\n"


RENDERERS = {"bibtex": bibtex, "ris": ris, "text": text}


def render(fmt: str, cff: dict[str, Any], version: str, year: str | None = None) -> str:
    """The entries in ``fmt`` (one of :data:`FORMATS`)."""
    if fmt not in RENDERERS:
        raise ValueError(f"unknown citation format {fmt!r}, expected one of {FORMATS}")
    return RENDERERS[fmt](cff, version, year)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("format", nargs="?", default="bibtex", choices=FORMATS)
    ap.add_argument("--version", default="")
    ap.add_argument("--cff", default=None)
    args = ap.parse_args()
    cff = load(Path(args.cff) if args.cff else None)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    print(render(args.format, cff, args.version, release_year(changelog, args.version)), end="")


if __name__ == "__main__":
    main()
