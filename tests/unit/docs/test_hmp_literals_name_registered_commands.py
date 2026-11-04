"""Every ``hmp <verb> [<action>]`` written in the package or the docs is a real command.

A page or a message that names a command the CLI does not register sends the
reader to a usage error. The scan reads the files git tracks under
``hydromodpy/`` and ``docs/source/`` that the working tree still holds.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from hydromodpy.cli.commands import ALL_COMMANDS

REPO_ROOT = Path(__file__).resolve().parents[3]
SCAN_ROOTS = ("hydromodpy", "docs/source")
SUFFIXES = (".py", ".rst", ".md")
# A command is a delimited literal or the start of a code line. ".hmp archive"
# names the file format, and "conda create -n hmp python=3.12" an environment.
HMP_COMMAND = re.compile(
    r"(?:[`'\"]|^[ \t]*\$?[ \t]*)hmp[ \t]+([a-z][a-z0-9-]{1,30})(?:[ \t]+([a-z][a-z0-9-]{1,30}))?",
    re.MULTILINE,
)
# The scan matched about 1000 literals when this test was written. Far fewer
# means the pattern stopped matching, not that the text got cleaner.
FLOOR = 200
# The one file that names commands that left, so that each is refused by name.
RETIRED_FORMS = REPO_ROOT / "hydromodpy" / "cli" / "conventions.py"
# The history of the alphas records commands that existed then and left since.
HISTORY_PAGE = REPO_ROOT / "docs" / "source" / "about" / "changes-during-the-alphas.md"

requires_git = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists(),
    reason="the scanned files are listed by git ls-files",
)


def _tracked_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", *SCAN_ROOTS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    # A file deleted in the working tree and not yet in a commit is still listed.
    paths = (
        REPO_ROOT / entry for entry in completed.stdout.split("\0") if entry.endswith(SUFFIXES)
    )
    return [path for path in paths if path.is_file()]


def _registered_actions() -> dict[str, set[str]]:
    families: dict[str, set[str]] = {}
    for module in ALL_COMMANDS:
        name = getattr(module, "NAME", module.__name__.rsplit(".", 1)[-1])
        families[name] = {
            getattr(action, "NAME", action.__name__.rsplit(".", 1)[-1])
            for action in getattr(module, "ACTIONS", ())
        }
    return families


@requires_git
@pytest.mark.allow_subprocess
def test_every_hmp_literal_names_a_registered_command() -> None:
    families = _registered_actions()
    literals = [
        (path.relative_to(REPO_ROOT).as_posix(), match.group(1), match.group(2))
        for path in _tracked_files()
        if path not in (RETIRED_FORMS, HISTORY_PAGE)
        for match in HMP_COMMAND.finditer(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert len(literals) >= FLOOR, f"the scan matched only {len(literals)} hmp literals"

    unknown = sorted(
        {
            f"{rel}: hmp {verb}{' ' + action if action else ''}"
            for rel, verb, action in literals
            if verb not in families or (action and families[verb] and action not in families[verb])
        }
    )
    assert unknown == []
