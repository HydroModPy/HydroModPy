"""Check the references to the documentation written outside the pages.

Usage: python -m tools.docs.check_refs [--site BUILT_HTML]

A README, a docstring, a workflow, a test or a page names a file of the
documentation (``docs/source/contribute/architecture/storage-layout.rst``) or a
page of the published site (``https://docs.hydromodpy.fr/main/guides/index.html``).
When the page moves, the reference stays and sends the reader nowhere. Two kinds
of reference are checked, in every file git tracks:

- a path that starts with ``docs/`` must exist in the tree, a folder included;
- a link to ``docs.hydromodpy.fr/<version>/<page>.html`` must name a page whose
  source exists under ``docs/source``.

A path that a build writes (the generated reference, the data of the build, the
build folder itself) is not in the tree: ``GENERATED`` lists those prefixes.
With ``--site``, a link must also exist in the built HTML, which covers the
generated pages. CHANGELOG.md is history and is not read. Exit code 1 when a
reference is dead.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUFFIXES = (".md", ".rst", ".py", ".toml", ".yml", ".yaml", ".txt", ".cff", ".cfg", ".ini", ".html")
# History, this file (it lists the paths it accepts) and the test that writes
# dead paths on purpose.
SKIP_FILES = (
    "CHANGELOG.md",
    "tools/docs/check_refs.py",
    "tests/unit/docs/test_check_refs.py",
)
SKIP_DIRS = ("docs/build/", "docs/_build/", "docs/_dev_notes/", "tools/vendor/")
# Written by the build or by a tool, never tracked.
GENERATED = (
    "docs/build",
    "docs/_build",
    "docs/source/_data",
    "docs/source/_generated",
    "docs/source/_autosummary",
    "docs/source/api/generated",
    "docs/source/reference/parameters",
    "docs/source/reference/python",
    "docs/source/reference/cli",
    "docs/source/reference/catalogs",
    "docs/source/theory/_generated",
)
# Written by a script of an example into its output folder.
WRITTEN_BY_SCRIPTS = ("docs/_dev_notes/diagnostics",)
# A path that is not a reference to a file: (file, text) -> why.
NOT_REFERENCES = {
    ("docs/source/contribute/handbook.rst", "docs/release-recipe"): "a branch name",
    (
        "docs/source/contribute/documentation/write-a-guide.md",
        "docs/source/guides/your-page.md",
    ): "the page the reader is about to write",
}
# A path in a text. The character before it must not belong to a longer path
# (``tools/docs/check_refs.py`` is not a path of ``docs/``).
DOCS_PATH = re.compile(r"(?<![\w/.~-])(docs/[A-Za-z0-9_./-]*[A-Za-z0-9_/-])")
SITE_LINK = re.compile(
    r"docs\.hydromodpy\.fr/(?:main|dev|stable|latest|v\d[\w.]*)/([A-Za-z0-9_./-]+?)\.html"
)
STATIC_LINK = re.compile(
    r"docs\.hydromodpy\.fr/(?:main|dev|stable|latest|v\d[\w.]*)/(_static/[\w./-]+)"
)
# A pattern, a placeholder or a sentence end is not a path.
NOT_A_PATH = re.compile(r"[*<>{}$]|\.\.\.")


def tracked_files(root: Path = ROOT) -> list[str]:
    """Return the tracked text files, relative to the repository root."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    files = [f for f in out.split("\0") if f.endswith(SUFFIXES)]
    return [
        f
        for f in files
        if f not in SKIP_FILES and not f.startswith(SKIP_DIRS) and (root / f).is_file()
    ]


def is_generated(path: str) -> bool:
    """Tell whether a build or a script writes ``path``."""
    return any(path == g or path.startswith(g + "/") for g in GENERATED + WRITTEN_BY_SCRIPTS)


def path_exists(path: str, root: Path = ROOT) -> bool:
    """Tell whether ``path`` exists in the tree, or is written by a build."""
    path = path.rstrip("/")
    if is_generated(path):
        return True
    return (root / path).exists()


def page_source_exists(page: str, root: Path = ROOT) -> bool:
    """Tell whether the site page ``page`` (no suffix) has a source under docs/source."""
    base = root / "docs" / "source" / page
    if is_generated("docs/source/" + page):
        return True
    return any(base.with_suffix(s).exists() for s in (".md", ".rst")) or (
        base.is_dir() and any((base / f"index{s}").exists() for s in (".md", ".rst"))
    )


def check(site: Path | None = None, root: Path = ROOT, files: list[str] | None = None) -> list[str]:
    """Return one line per dead reference, in ``files`` or in the files git tracks."""
    problems: list[str] = []
    for name in tracked_files(root) if files is None else files:
        try:
            text = (root / name).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # A tracked file that is not text holds no reference.
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for match in DOCS_PATH.finditer(line):
                path = match.group(1).rstrip(".")
                if NOT_A_PATH.search(line[match.start() : match.end() + 3]):
                    continue
                if (name, path) in NOT_REFERENCES:
                    continue
                if not path_exists(path, root):
                    problems.append(f"{name}:{number}: no such path: {path}")
            for match in SITE_LINK.finditer(line):
                page = match.group(1)
                if not page_source_exists(page, root):
                    problems.append(f"{name}:{number}: no page for the link: {page}.html")
                elif site is not None and not (site / f"{page}.html").exists():
                    problems.append(f"{name}:{number}: not in the built site: {page}.html")
            if site is not None:
                for match in STATIC_LINK.finditer(line):
                    if not (site / match.group(1)).exists():
                        problems.append(f"{name}:{number}: not in the built site: {match.group(1)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Print the dead references and return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--site", type=Path, help="the built HTML folder, to check the links against"
    )
    args = parser.parse_args(argv)
    problems = check(args.site)
    for problem in problems:
        print(problem)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
