"""Messages quoted in the "What can go wrong" tables of Get started.

A page tells the reader which message to look for. The message has to exist
in the code, or the table sends the reader after a text that is never printed.

``quoted_messages`` reads the first column of each table and returns the
fragments written between backticks that look like a message. A fragment is cut
at every placeholder (``<n>``, ``...``, ``[...]``) and each piece must be a
substring of a string literal of the package. ``code_strings`` collects those
literals from the syntax tree, so a message split over several source lines
(implicit concatenation) is one literal, and the text around an f-string value
is one literal per side of the value.

Usage: python -m tools.docs.quoted_messages   (prints the fragments not found)
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE_DIRS = ("docs/source/get-started",)
HEADING = re.compile(r"^##\s+What can go wrong\s*$")
NEXT_HEADING = re.compile(r"^##\s+")
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
# A placeholder stands for text the code computes.
PLACEHOLDER = re.compile(r"<[^<>\n]{1,40}>|\[\.\.\.\]|\.\.\.|…")
# A piece shorter than this is a word of the sentence, not a message to search.
MIN_PIECE = 12
# A span that starts like this is a command, a flag, a key or a path, not a message.
NOT_A_MESSAGE = re.compile(
    r"^(?:\$ |hmp |hydromodpy |pip |python |git |micromamba |conda |cd |mkdir |export |--?[a-z]|"
    r"\[|\{|/|~|\.|https?://|exit \d+|\d+$|\"\w+\": )"
)


@dataclass(frozen=True)
class Quoted:
    """One quoted fragment, with where it is written."""

    page: str
    line: int
    span: str
    pieces: tuple[str, ...]


def _table_first_cells(lines: list[str], start: int) -> list[tuple[int, str]]:
    """Return ``(line number, first cell)`` for each table row below ``start``."""
    cells: list[tuple[int, str]] = []
    for offset, text in enumerate(lines[start:], start=start):
        if NEXT_HEADING.match(text):
            break
        if not text.startswith("|") or set(text.replace("|", "").strip()) <= {"-", ":", " "}:
            continue
        body = text.strip().strip("|")
        # A pipe inside a code span would split the row: the docs escape it.
        first = re.split(r"(?<!\\)\|", body, maxsplit=1)[0]
        cells.append((offset + 1, first.strip()))
    return cells


def _pieces(span: str) -> tuple[str, ...]:
    pieces = [p.strip(" .,;:'\"") for p in PLACEHOLDER.split(span)]
    return tuple(p for p in pieces if len(p) >= MIN_PIECE)


def quoted_messages(page: Path) -> list[Quoted]:
    """Return the message-like fragments of the first column of a page's tables."""
    lines = page.read_text(encoding="utf-8").splitlines()
    rel = page.relative_to(ROOT).as_posix() if page.is_relative_to(ROOT) else page.as_posix()
    found: list[Quoted] = []
    for index, text in enumerate(lines):
        if not HEADING.match(text):
            continue
        for number, cell in _table_first_cells(lines, index + 1):
            for _ticks, span in CODE_SPAN.findall(cell):
                span = span.strip()
                if NOT_A_MESSAGE.match(span) or " " not in span:
                    continue
                pieces = _pieces(span)
                if pieces:
                    found.append(Quoted(rel, number, span, pieces))
    return found


def pages() -> list[Path]:
    """Return the pages that carry the table."""
    out: list[Path] = []
    for directory in PAGE_DIRS:
        out.extend(sorted((ROOT / directory).rglob("*.md")))
    return [p for p in out if any(HEADING.match(t) for t in p.read_text("utf-8").splitlines())]


# A run of this many words, at least MIN_RUN characters long, must be in the code.
RUN_WORDS = 4
MIN_RUN = 18
# A literal part shorter than this is a word of a sentence, not a message.
MIN_FRAGMENT = 14
# Parts around a value are shorter ("step ", " failed: "), so they are searched together.
MIN_WINDOW = 12
FORMAT_FIELD = re.compile(r"\{[^{}]*\}|%[-+# 0-9.]*[sdrfgx]")
VALUE = "\x00"


@dataclass(frozen=True)
class Corpus:
    """The messages the package can print, with a break where a value goes."""

    text: str
    fragments: tuple[str, ...]
    # Literal parts that sit side by side around values, from 2 to 4 of them.
    windows: tuple[tuple[str, ...], ...]


def code_corpus(package: Path | None = None) -> Corpus:
    """Collect the string literals of the package from the syntax tree.

    A message split over several source lines (implicit concatenation) is one
    literal. The value of an f-string, a ``str.format`` field or a ``%`` field is
    a break, and the literal parts around it are the fragments.
    """
    package = package or ROOT / "hydromodpy"
    messages: list[str] = []
    for path in sorted(package.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            # A file that does not parse cannot carry a message the user sees.
            continue
        nested: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                nested.update(id(v) for v in node.values)
                messages.append(
                    "".join(
                        v.value
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)
                        else VALUE
                        for v in node.values
                    )
                )
        messages.extend(
            FORMAT_FIELD.sub(VALUE, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in nested
        )
    text = re.sub(r"[ \t\r\f\v]+", " ", "\n".join(messages))
    parts = {p.strip() for m in messages for p in re.split(VALUE, m)}
    windows: set[tuple[str, ...]] = set()
    for message in messages:
        pieces = message.split(VALUE)
        for first in range(len(pieces) - 1):
            for size in range(2, 5):
                window = tuple(pieces[first : first + size])
                if len(window) == size and len("".join(window).strip()) >= MIN_WINDOW:
                    windows.add(window)
    return Corpus(text, tuple(p for p in parts if len(p) >= MIN_FRAGMENT), tuple(windows))


def _window_in(window: tuple[str, ...], span: str) -> bool:
    """Tell whether ``span`` holds the literal parts of ``window`` with a value between them."""
    literal = [part for part in window if part.strip()]
    if not all(part.strip() in span for part in literal):
        return False
    edges = list(window)
    edges[0], edges[-1] = edges[0].lstrip(), edges[-1].rstrip()
    regex = ".{0,80}?".join(re.escape(part) for part in edges)
    return re.search(regex, span, re.DOTALL) is not None


def unexplained(quoted: Quoted, corpus: Corpus) -> bool:
    """Tell whether nothing of the quote comes from a message of the code.

    A quote often writes real values where the code has a value, and cuts the
    message short. It comes from the code when a literal part of a message is
    inside it, when a run of four words of it is a run of words of the code, or
    when a piece of it between two placeholders is inside the code.
    """
    span = re.sub(r"\s+", " ", quoted.span)
    if any(part in span for part in corpus.fragments):
        return False
    if any(_window_in(window, span) for window in corpus.windows):
        return False
    words = span.split(" ")
    for start in range(len(words) - RUN_WORDS + 1):
        run = " ".join(words[start : start + RUN_WORDS]).strip(" .,;:")
        if len(run) >= MIN_RUN and run in corpus.text:
            return False
    return not any(piece in corpus.text for piece in quoted.pieces)


def all_quotes() -> list[Quoted]:
    """Return every message-like quote of the tables."""
    return [quoted for page in pages() for quoted in quoted_messages(page)]


def missing(allowed: tuple[str, ...] = ()) -> list[Quoted]:
    """Return the quotes the code does not explain."""
    corpus = code_corpus()
    return [
        quoted
        for quoted in all_quotes()
        if not any(a in quoted.span for a in allowed) and unexplained(quoted, corpus)
    ]


def main() -> int:
    """Print the fragments that the code does not hold."""
    bad = missing()
    for quoted in bad:
        print(f"{quoted.page}:{quoted.line}: not in the code: {quoted.span[:140]!r}")
    print(f"{len(bad)} fragment(s) not found")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
