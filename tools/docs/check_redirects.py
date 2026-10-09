"""Check that every URL of the old site still leads to a page.

``tools/docs/old_site_urls.txt`` lists the paths of the site published before the
restructuring (the sitemaps of the main and dev versions). Each one is a page today
or has a line in ``docs/source/redirects.txt``, and that line goes to a page in one
hop. The checks that read the sources run anywhere::

    python -m tools.docs.check_redirects

Given the built site, it also checks that every old path is a file there and that
every redirect page points at a file that exists::

    python -m tools.docs.check_redirects docs/build/html

The pages under ``reference/parameters``, ``reference/python`` and ``reference/cli``
are written by the build and are not in the repository. Their redirects are checked
by the build itself: rediraffe warns when a target is missing and the strict build
fails on a warning.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "source"
REDIRECTS = SOURCE / "redirects.txt"
NOT_PAGES = SOURCE / "redirects-not-pages.txt"
OLD_URLS = ROOT / "tools" / "docs" / "old_site_urls.txt"

SUFFIX = re.compile(r"\.(rst|md)$")
TARGET = re.compile(r"url=([^\"]+)\"")
# Pages written by the build, absent from the repository.
WRITTEN_BY_THE_BUILD = ("reference/parameters/", "reference/python/", "reference/cli/")
# Pages Sphinx writes by itself.
BUILT_IN = {"genindex", "search"}


def lines(path: Path) -> list[str]:
    """The lines of a list file, without blanks and comments."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def docname(name: str) -> str:
    """A source file name or an old URL path without its extension."""
    return SUFFIX.sub("", name.removesuffix(".html"))


def redirects() -> tuple[dict[str, str], list[str]]:
    """The redirect table (old name -> new page) and the lines that are not valid."""
    table: dict[str, str] = {}
    problems: list[str] = []
    for line in lines(REDIRECTS):
        fields = line.split()
        if len(fields) != 2:
            problems.append(f"redirects.txt: expected 'old new', got {line!r}")
            continue
        old, new = fields
        if old in table:
            problems.append(f"redirects.txt: {old} is redirected twice")
        table[old] = new
    return table, problems


def pages() -> set[str]:
    """Document names of the pages written by hand, without extension."""
    files = [path.relative_to(SOURCE) for path in SOURCE.rglob("*") if path.is_file()]
    written = {
        SUFFIX.sub("", file.as_posix())
        for file in files
        if SUFFIX.search(file.name)
        and not file.parts[0].startswith("_")
        and not file.as_posix().startswith(WRITTEN_BY_THE_BUILD)
    }
    return written | BUILT_IN


def lost_urls() -> list[str]:
    """Old URLs that are neither a page nor redirected."""
    table, _ = redirects()
    known = pages() | {docname(old) for old in table}
    return [url for url in lines(OLD_URLS) if docname(url) not in known]


def bad_redirects() -> list[str]:
    """Redirect lines that break a rule: format, chain, missing target, hidden page."""
    table, problems = redirects()
    existing = pages()
    sources = {docname(old) for old in table}
    for old, new in table.items():
        if docname(old) in existing:
            problems.append(f"{old}: a page of that name exists, the redirect hides it")
        if new in sources:
            problems.append(f"{old} -> {new}: the target is itself redirected (a chain)")
        elif SUFFIX.search(new) or new.endswith(".html"):
            problems.append(f"{old} -> {new}: write the target without extension")
        elif new not in existing and not new.startswith(WRITTEN_BY_THE_BUILD):
            problems.append(f"{old} -> {new}: the target is not a page")
    for name in lines(NOT_PAGES):
        if docname(name) in sources:
            problems.append(f"{name}: listed as redirected and as never a page")
    return problems


def built_site_problems(built: Path) -> list[str]:
    """Old paths absent from the built site, and redirect pages with a missing target."""
    problems = [
        f"{url}: not in the built site" for url in lines(OLD_URLS) if not (built / url).is_file()
    ]
    table, _ = redirects()
    for old in table:
        stub = built / (docname(old) + ".html")
        if not stub.is_file():
            continue
        found = TARGET.search(stub.read_text(encoding="utf-8"))
        if not found:
            problems.append(f"{stub.relative_to(built)}: no target in the redirect page")
        elif not (stub.parent / found.group(1)).resolve().is_file():
            problems.append(f"{stub.relative_to(built)}: the target {found.group(1)} is missing")
    return problems


def main() -> int:
    problems = [f"no page and no redirect: {url}" for url in lost_urls()] + bad_redirects()
    if len(sys.argv) > 1:
        problems += built_site_problems(Path(sys.argv[1]))
    for line in problems:
        print(line)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
