"""Check the built site for what a strict Sphinx build lets through.

Pages written by the extensions are raw HTML, which Sphinx does not check:

- a link inside a link, which the browser splits apart;
- an internal link to a missing page or a missing anchor;
- markup shown as text: ``code``, **bold**, :role:`x`, {role}`x`;
- a UML diagram that was not rendered (PlantUML missing or failing).

Usage::

    python -m tools.docs.check_site docs/build/html
"""

from __future__ import annotations

import html
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

ARTICLE = re.compile(r'<article class="bd-article"[^>]*>(.*?)</article>', re.S)
TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>")
ID = re.compile(r'\sid="([^"]+)"')
HREF = re.compile(r'href="([^"]+)"')
HIDDEN = re.compile(r'<p class="hmp-search-text">.*?</p>', re.S)
VERBATIM = re.compile(r"<(pre|code|script|style|textarea)\b.*?</\1>", re.S | re.I)
LEAKS = {
    "double backticks": re.compile(r"``[^`\s][^`]*``"),
    "bold markers": re.compile(r"\*\*[A-Za-z][^*\n]*\*\*"),
    "rst role": re.compile(r":(?:class|func|meth|attr|mod|doc|ref|data|obj):`"),
    "myst role": re.compile(r"\{(?:toml|doc|ref|term)\}`"),
}
EXTERNAL = ("http:", "https:", "mailto:", "javascript:", "data:", "#!")


def nested_links(body: str) -> int:
    """Number of links opened inside another link."""
    depth = count = 0
    for m in TAG.finditer(body):
        if m.group(2).lower() != "a":
            continue
        if m.group(1):
            depth = max(0, depth - 1)
        else:
            count += depth > 0
            depth += 1
    return count


def check(root: Path) -> list[str]:
    problems: list[str] = []
    ids: dict[Path, set[str]] = {}

    def ids_of(page: Path) -> set[str]:
        if page not in ids:
            ids[page] = set(ID.findall(page.read_text(encoding="utf-8", errors="ignore")))
        return ids[page]

    for page in sorted(root.rglob("*.html")):
        rel = page.relative_to(root).as_posix()
        match = ARTICLE.search(page.read_text(encoding="utf-8", errors="ignore"))
        if match is None:
            continue
        body = match.group(1)
        if n := body.count("uml-diagram-unavailable"):
            problems.append(f"{rel}: {n} UML diagram(s) not rendered")
        if n := nested_links(body):
            problems.append(f"{rel}: {n} link(s) inside a link")
        visible = html.unescape(re.sub(r"<[^>]+>", " ", VERBATIM.sub(" ", HIDDEN.sub(" ", body))))
        for name, rx in LEAKS.items():
            if hit := rx.search(visible):
                problems.append(f"{rel}: {name} shown as text: {hit.group(0)[:60]}")
        dead = defaultdict(int)
        for href in HREF.findall(body):
            if href.startswith(EXTERNAL):
                continue
            parts = urlsplit(href)
            target = (page.parent / unquote(parts.path)).resolve() if parts.path else page
            if not target.exists():
                dead[href] += 1
            elif parts.fragment and target.suffix == ".html":
                if unquote(parts.fragment) not in ids_of(target):
                    dead[href] += 1
        for href, n in sorted(dead.items()):
            problems.append(f"{rel}: dead link {href}" + (f" (x{n})" if n > 1 else ""))
    return problems


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/build/html")
    problems = check(root)
    for line in problems:
        print(line)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
