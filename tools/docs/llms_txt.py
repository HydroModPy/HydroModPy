"""Write ``llms.txt`` and ``llms-full.txt`` from the built HTML pages.

An assistant that answers a question about HydroModPy should read the
reference, not guess it. Most of the parameter reference is written at build
time by the ``hmp_*`` directives, so the Markdown sources hold directive lines,
not the text a reader sees (this is why sphinx-llms-txt is not used: it copies
``_sources``). This script reads the built article of each page instead.

- ``llms.txt``: one line per page (title, link, description), grouped by door.
  The Contribute door comes last, under "Optional".
- ``llms-full.txt``: the text of every page outside Contribute and outside the
  generated indexes, in the same order.

Usage::

    python -m tools.docs.llms_txt docs/build/html
"""

from __future__ import annotations

import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ARTICLE = re.compile(r'<article class="bd-article"[^>]*>(.*?)</article>', re.S)
CANONICAL = re.compile(r'<link rel="canonical" href="([^"]+)"')
# Where a door starts, in the order of the site header.
DOORS = (
    ("understand", "Understand"),
    ("get-started", "Get started"),
    ("guides", "Guides"),
    ("reference", "Reference"),
    ("theory", "Theory"),
    ("about", "About"),
    ("contribute", "Contribute"),
)
NOT_LISTED = {"genindex.html", "search.html", "reference/parameters/explorer.html"}
SKIP_DIRS = {"_static", "_sources", "_images", "_downloads", "_plantuml", "pagefind"}
BLOCKS = {
    "p", "div", "section", "article", "ul", "ol", "dl", "table", "tr", "figure",
    "figcaption", "details", "summary", "blockquote", "dt", "dd", "li", "caption",
}  # fmt: skip
# Elements with no text a reader would quote.
DROPPED = {"script", "style", "button", "svg", "nav", "select", "input", "noscript"}
DROPPED_CLASSES = {
    "headerlink",
    "hmp-search-text",
    "hmp-copy",
    "hmp-adv-switch",
    "sd-sphinx-override",
}
CARD_ROW = "@card"
MIN_DESCRIPTION = 40
# A line that starts like this is not prose.
PREFIXES = ("#", "|", "-", "`", "!", "<", "**", "1.", "[")
HEADINGS = {f"h{n}": "#" * n for n in range(1, 7)}


class Text(HTMLParser):
    """The article as plain Markdown-like text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, bool, str]] = []
        self.skip = 0
        self.pre = 0
        self.inline = 0  # inside a table cell or a definition: no paragraph breaks
        self.lists: list[str] = []
        self.head_row = False
        self.card = 0  # inside the row that holds the card of a key

    def _put(self, text: str) -> None:
        if text:
            self.out.append(text)

    def _break(self, n: int = 1) -> None:
        """Open a new line, or a blank one, without stacking blank lines."""
        joined = "".join(self.out[-3:])
        have = len(joined) - len(joined.rstrip("\n"))
        if self.out and have < n:
            self.out.append("\n" * (n - have))

    def _block(self, n: int) -> None:
        """A block boundary: a line break, or one space inside a cell."""
        if self.inline:
            if self.out and not self.out[-1].endswith((" ", "\n")):
                self._put(" ")
        else:
            self._break(n)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        classes = set(a.get("class", "").split())
        drop = tag in DROPPED or bool(classes & DROPPED_CLASSES) or "hidden" in a
        # A void element has no end tag: it never goes on the stack.
        if tag in {"br", "img", "hr", "wbr", "input", "meta", "link"}:
            if not self.skip:
                if tag == "br":
                    self._put(" " if self.inline else "\n")
                elif tag == "hr":
                    self._break(2)
            return
        closer = "`" if "tl-code" in classes else ""
        if tag == "tr" and "hmp-known-card" in classes:
            closer = CARD_ROW
        self.stack.append((tag, drop, closer))
        if drop:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in HEADINGS:
            self._break(2)
            self._put(HEADINGS[tag] + " ")
        elif tag == "pre":
            self._break(2)
            self._put("```\n")
            self.pre += 1
        elif tag == "code" and not self.pre:
            self._put("`")
        elif "tl-code" in classes or "tl-note" in classes:
            # A line of a TOML view: the line itself, then what it says.
            self._put("`" if "tl-code" in classes else " : ")
        elif tag in {"ul", "ol"}:
            self._break()
            self.lists.append(tag)
        elif tag == "li":
            self.inline += 1
            self._break()
            self._put(
                "  " * max(0, len(self.lists) - 1) + ("1. " if self.lists[-1:] == ["ol"] else "- ")
            )
        elif tag == "tr" and closer == CARD_ROW:
            self.card += 1
            self._break(2)
        elif tag == "tr":
            self._break()
            self._put("|")
            self.inline += 1
        elif tag in {"td", "th"}:
            self._put("" if self.card else " ")
        elif tag == "thead":
            self.head_row = True
        elif tag == "dt":
            self._break()
            self._put("**")
        elif tag == "dd":
            self.inline += 1
            self._put(" ")
        elif tag in BLOCKS:
            self._block(2 if tag in {"p", "table", "figure", "details", "section"} else 1)

    def handle_endtag(self, tag: str) -> None:
        # Close back to the matching start tag: a stray end tag is ignored.
        if not any(entry[0] == tag for entry in self.stack):
            return
        while self.stack:
            top, drop, closer = self.stack.pop()
            if drop:
                self.skip -= 1
            elif closer == CARD_ROW:
                self.card -= 1
                self._break(2)
            elif not self.skip:
                self._close(top)
                self._put(closer)
            if top == tag:
                break

    def _close(self, tag: str) -> None:
        if tag == "pre":
            self.pre -= 1
            self._break()
            self._put("```")
            self._break(2)
        elif tag == "code" and not self.pre:
            self._put("`")
        elif tag in {"ul", "ol"}:
            if self.lists:
                self.lists.pop()
            self._break()
        elif tag in {"td", "th"}:
            self._put("" if self.card else " |")
        elif tag == "tr":
            self.inline -= 1
            if self.head_row:
                cells = "".join(self.out).rsplit("\n", 1)[-1].count("|") - 1
                self._put("\n|" + " --- |" * max(cells, 1))
                self.head_row = False
            self._break()
        elif tag == "dt":
            self._put("**:")
        elif tag == "dd":
            self.inline -= 1
            self._break()
        elif tag in HEADINGS or tag in {"p", "table", "figure", "details", "section"}:
            self._block(2)
        elif tag == "li":
            self.inline -= 1
            self._break()
        elif tag in {"figcaption", "summary", "caption"}:
            self._block(1)

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if not self.pre:
            data = re.sub(r"\s+", " ", data)
            if data == " " and (not self.out or self.out[-1].endswith(("\n", " ", "`"))):
                return
            if not self.out or self.out[-1].endswith("\n"):
                data = data.lstrip()
        self._put(data)

    def text(self) -> str:
        text = "".join(self.out)
        # Runs of spaces outside the code blocks come from the cell padding.
        parts = text.split("```")
        parts[::2] = [re.sub(r"(?<=\S) {2,}", " ", part) for part in parts[::2]]
        text = "```".join(parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def article_text(page_html: str) -> str:
    match = ARTICLE.search(page_html)
    if match is None:
        return ""
    parser = Text()
    parser.feed(match.group(1))
    parser.close()
    return parser.text()


def describe(text: str, limit: int = 200) -> str:
    """The sentence a link of llms.txt carries: the Task of a guide, else the first paragraph."""
    lines = [line.strip() for line in text.splitlines()]
    task = next((line for line in lines if line.startswith("**Task**:")), "")
    if task:
        paragraph = task[len("**Task**:") :].strip()
    else:
        plain = (line for line in lines if line and not line.startswith(PREFIXES))
        paragraph = next(plain, "")
    # Sentences up to a useful length ("Yes." says nothing), within the limit.
    first = ""
    for sentence in re.split(r"(?<=[.?!])\s", paragraph):
        candidate = f"{first} {sentence}".strip()
        if len(candidate) > limit:
            break
        first = candidate
        if len(first) >= MIN_DESCRIPTION:
            break
    if first or not paragraph:
        return first
    return paragraph[:limit].rsplit(" ", 1)[0] + "..."


def door_of(rel: str) -> str:
    head = rel.split("/", 1)[0]
    for key, title in DOORS:
        if head == key:
            return title
    return "Home" if rel == "index.html" else ""


def first_title(text: str, rel: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return re.sub(r"\s+", " ", line[2:]).strip()
    return rel


def base_url(root: Path) -> str:
    index = root / "index.html"
    if index.exists():
        match = CANONICAL.search(index.read_text(encoding="utf-8", errors="ignore"))
        if match:
            return match.group(1).rsplit("/", 1)[0] + "/"
    return ""


def pages(root: Path) -> list[tuple[str, str, str, str, str]]:
    """(door, rel path, title, description, text) of each listed page, in reading order."""
    order = {title: i for i, (_, title) in enumerate(DOORS)}
    found = []
    for page in root.rglob("*.html"):
        rel = page.relative_to(root).as_posix()
        if rel in NOT_LISTED or SKIP_DIRS & set(rel.split("/")[:-1]):
            continue
        raw = page.read_text(encoding="utf-8", errors="ignore")
        text = article_text(raw)
        if not text:
            continue
        description = describe(text)
        door = door_of(rel)
        key = (-1 if door == "Home" else order.get(door, 99), not rel.endswith("index.html"), rel)
        found.append((key, door, rel, first_title(text, rel), description, text))
    found.sort(key=lambda row: row[0])
    return [row[1:] for row in found]


def write(root: Path) -> tuple[Path, Path]:
    base = base_url(root)
    rows = pages(root)
    lines = [
        "# HydroModPy",
        "",
        "> HydroModPy computes where groundwater comes out of the ground and which streams "
        "it keeps alive, month by month, for a whole catchment. These are its documentation "
        "pages. Each line links to a page; llms-full.txt holds the text of all of them.",
        "",
    ]
    full = ["# HydroModPy documentation", ""]
    door = None
    optional = False
    for page_door, rel, title, description, text in rows:
        if page_door == "Contribute" and not optional:
            lines += ["", "## Optional", ""]
            optional = True
            door = "Contribute"
        elif page_door != door and page_door != "Contribute":
            lines += ["", f"## {page_door}", ""]
            door = page_door
        lines.append(f"- [{title}]({base}{rel})" + (f": {description}" if description else ""))
        if page_door == "Contribute":
            continue
        full += [f"<!-- {base}{rel} -->", text, ""]
    out_index = root / "llms.txt"
    out_full = root / "llms-full.txt"
    out_index.write_text(re.sub(r"\n{3,}", "\n\n", "\n".join(lines) + "\n"), encoding="utf-8")
    out_full.write_text("\n".join(full), encoding="utf-8")
    return out_index, out_full


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/build/html")
    index, full = write(root)
    print(f"{index} ({index.stat().st_size} bytes), {full} ({full.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
