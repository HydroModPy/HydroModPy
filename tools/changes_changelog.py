"""Write the ``Numbers`` bullets of ``CHANGELOG.md`` from the register of changes.

A fix, a default or a rule that moves a number is one row of
``hydromodpy/schema/changes.toml``. The changelog lists it once, under ``### Numbers``
of ``## [Unreleased]``, between two comments::

    <!-- numbers:begin -->
    - <the text of the row>
    <!-- numbers:end -->

The bullets come from every ``[[bug]]`` and ``[[default]]`` row, and from each
``[[recipe]]`` row of effect ``numbers``, whose ``since`` is after the last published
section. They come in that order of tables, each in the order of the file. A section
that was published keeps the bullets it was written with. The other kinds of rows
(refusals, labels, layouts, migrations) are not changelog bullets: the page
``docs/source/reference/changes-register.md`` lists them all.

Check::

    python -m tools.changes_changelog

It prints the diff and exits with 1 when the block differs from the register. Write::

    python -m tools.changes_changelog --write

It creates the section at the end of ``[Unreleased]`` when the comments are not there yet.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

from packaging.version import Version

from hydromodpy.schema.changes import REGISTER, Register

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
BEGIN = "<!-- numbers:begin -->"
END = "<!-- numbers:end -->"
HEADING = "### Numbers"

_UNRELEASED = re.compile(r"^## \[Unreleased\][^\n]*\n", re.MULTILINE)
_NEXT_SECTION = re.compile(r"^## \[", re.MULTILINE)
_PUBLISHED = re.compile(r"^## \[v(\d[^\]]*)\]", re.MULTILINE)


def last_release(changelog: str) -> str:
    """Return the version of the newest published section, the first one under ``[Unreleased]``."""
    found = _PUBLISHED.search(changelog)
    if found is None:
        raise ValueError("CHANGELOG.md has no published section '## [vX.Y.Z]'")
    return found.group(1)


def bullets(register: Register, after: str) -> list[str]:
    """Return the bullets of the rows that moved a number since the release *after*."""
    rows = [
        *register.bugs,
        # A default that moves no quantity only changes what is written.
        *(default for default in register.defaults if default.quantities),
        *(recipe for recipe in register.recipes if recipe.effect == "numbers"),
    ]
    return [f"- {row.text.strip()}" for row in rows if Version(row.since) > Version(after)]


def _unreleased_span(changelog: str) -> tuple[int, int]:
    """Return the start and the end of the ``[Unreleased]`` section, heading included."""
    head = _UNRELEASED.search(changelog)
    if head is None:
        raise ValueError("CHANGELOG.md has no '## [Unreleased]' section")
    following = _NEXT_SECTION.search(changelog, head.end())
    return head.start(), following.start() if following else len(changelog)


def rewrite(changelog: str, register: Register = REGISTER) -> str:
    """Return *changelog* with the block between the comments written from *register*."""
    lines = bullets(register, last_release(changelog))
    block = "\n".join(lines)
    start, end = _unreleased_span(changelog)
    section = changelog[start:end]
    begins, ends = section.count(BEGIN), section.count(END)
    if (begins, ends) == (1, 1) and section.index(BEGIN) < section.index(END):
        before, _, rest = section.partition(BEGIN)
        _, _, after = rest.partition(END)
        inner = f"\n{block}\n" if block else "\n"
        return changelog[:start] + before + BEGIN + inner + END + after + changelog[end:]
    if (begins, ends) != (0, 0):
        raise ValueError(f"[Unreleased] must hold one {BEGIN} then one {END}, or neither")
    if not lines:
        return changelog
    kept = section.rstrip("\n")
    created = f"{kept}\n\n{HEADING}\n\n{BEGIN}\n{block}\n{END}\n\n"
    return changelog[:start] + created + changelog[end:]


def diff(changelog: str, register: Register = REGISTER) -> str:
    """Return the unified diff of the block, empty when the changelog says what the register says."""
    rewritten = rewrite(changelog, register)
    return "".join(
        difflib.unified_diff(
            changelog.splitlines(keepends=True),
            rewritten.splitlines(keepends=True),
            "CHANGELOG.md",
            "CHANGELOG.md (from changes.toml)",
        )
    )


def main(argv: list[str] | None = None, register: Register = REGISTER) -> int:
    """Check the block, or write it with ``--write``. Exit 1 when a check finds a difference."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write the block into the changelog")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    text = args.changelog.read_text(encoding="utf-8")
    try:
        rewritten = rewrite(text, register)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if rewritten == text:
        print(f"{args.changelog.name}: the Numbers block follows changes.toml.")
        return 0
    if args.write:
        args.changelog.write_text(rewritten, encoding="utf-8")
        print(f"{args.changelog.name}: the Numbers block is written.")
        return 0
    print(diff(text, register), file=sys.stderr)
    print(
        f"{args.changelog.name}: the Numbers block differs from changes.toml. "
        "Run python -m tools.changes_changelog --write.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
