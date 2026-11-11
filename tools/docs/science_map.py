"""The science map: each theory page, the modules that compute it and the tests behind it.

A theory page names the modules it describes in a ``hmp-tested-by`` block, in
Markdown or in reStructuredText. ``tools/docs/tests_index.py`` lists the
modules each test file imports, with its tier. The map joins the two, so no
list is kept by hand: a renamed module makes the block fail at build time, and
a page without a block is reported.

``science_map``, ``missing_blocks`` and ``unknown_prefixes`` are pure.
``read_pages`` reads the pages of a ``theory/`` folder and imports nothing.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

# A theory page is a title and the module prefixes of its block.
Pages = Mapping[str, tuple[str, list[str]]]

# These pages describe the documentation and not a calculation.
NOT_A_CALCULATION = {
    "theory/bibliography": "the list of references",
    "theory/notation": "the symbols used by the other pages",
    "theory/validation": "the validation results, generated from the tests",
    "theory/science-map": "this map",
}

MD_BLOCK = re.compile(r"^(`{3,})\{hmp-tested-by\}\s*$")
RST_BLOCK = re.compile(r"^\.\. hmp-tested-by::\s*$")
MD_TOCTREE = re.compile(r"^`{3,}\{toctree\}")
RST_TOCTREE = re.compile(r"^\.\. toctree::")
RST_UNDERLINE = re.compile(r"^([=\-~^\"#*+])\1{2,}\s*$")


def _title(lines: list[str], suffix: str) -> str:
    if suffix == ".md":
        return next((ln[2:].strip() for ln in lines if ln.startswith("# ")), "")
    for above, line in zip(lines, lines[1:], strict=False):
        if above.strip() and RST_UNDERLINE.match(line) and not RST_UNDERLINE.match(above):
            return above.strip()
    return ""


def _prefixes(lines: list[str], suffix: str) -> list[str]:
    """The module prefixes of every ``hmp-tested-by`` block of a page."""
    found: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        md = MD_BLOCK.match(line) if suffix == ".md" else None
        if md:
            i += 1
            while i < len(lines) and not lines[i].startswith(md.group(1)):
                found.extend(lines[i].split())
                i += 1
        elif suffix == ".rst" and RST_BLOCK.match(line):
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith((" ", "\t"))):
                found.extend(lines[i].split())
                i += 1
            continue
        i += 1
    return list(dict.fromkeys(found))


def read_pages(srcdir: Path) -> tuple[dict[str, tuple[str, list[str]]], set[str]]:
    """Every page of ``<srcdir>/theory``, and the pages that hold a ``toctree``.

    The page names are ``theory/<path without suffix>``, as Sphinx names them.
    """
    pages: dict[str, tuple[str, list[str]]] = {}
    indexes: set[str] = set()
    for path in sorted((srcdir / "theory").rglob("*")):
        if path.suffix not in (".md", ".rst") or "_generated" in path.parts:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        name = path.relative_to(srcdir).with_suffix("").as_posix()
        pages[name] = (_title(lines, path.suffix), _prefixes(lines, path.suffix))
        toctree = MD_TOCTREE if path.suffix == ".md" else RST_TOCTREE
        if any(toctree.match(line) for line in lines):
            indexes.add(name)
    return pages, indexes


def missing_blocks(pages: Pages, indexes: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """One warning per page that names no module, except an index and the exempt pages."""
    return [
        f"theory page {page} names no module: add a hmp-tested-by block"
        for page, (_title_, prefixes) in sorted(pages.items())
        if not prefixes and page not in indexes and page not in NOT_A_CALCULATION
    ]


def is_module(prefix: str) -> bool:
    """Whether *prefix* is a module or a package that Python can find."""
    try:
        return importlib.util.find_spec(prefix) is not None
    except (ImportError, ValueError):
        return False


def unknown_prefixes(pages: Pages, exists: Callable[[str], bool] = is_module) -> list[str]:
    """One warning per prefix of a block that is not a module of hydromodpy."""
    return [
        f"{prefix} in hmp-tested-by of {page} is not a module of hydromodpy"
        for page, (_title_, prefixes) in sorted(pages.items())
        for prefix in prefixes
        if not exists(prefix)
    ]


def _imports(modules: list[str], prefixes: list[str]) -> bool:
    return any(m == p or m.startswith(p + ".") for m in modules for p in prefixes)


def science_map(pages: Pages, tests: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row per page that names modules, with the tests that import them.

    *tests* is ``_data/tests.json``. ``kernel_tests`` are the files of the
    ``unit`` tier, ``scenarios`` those of the ``scenarios`` tier, and
    ``validation`` the files of the ``validation`` tier with the ids of the
    cases they run.
    """
    imports = tests.get("imports", {})
    cases = {e["file"]: [c["id"] for c in e.get("cases", [])] for e in tests.get("validation", [])}
    rows = []
    for page, (title, prefixes) in sorted(pages.items()):
        if not prefixes:
            continue
        hits = {
            f: info for f, info in sorted(imports.items()) if _imports(info["modules"], prefixes)
        }
        rows.append(
            {
                "page": page,
                "concept": title,
                "modules": list(prefixes),
                "kernel_tests": [f for f, i in hits.items() if i["tier"] == "unit"],
                "scenarios": [f for f, i in hits.items() if i["tier"] == "scenarios"],
                "validation": [
                    {"file": f, "cases": cases.get(f, [])}
                    for f, i in hits.items()
                    if i["tier"] == "validation"
                ],
            }
        )
    return rows
