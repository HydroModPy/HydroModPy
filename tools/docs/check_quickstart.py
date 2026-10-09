"""Run the Quick start of the Get started page and check the line it promises.

Usage:
    python -m tools.docs.check_quickstart [--workspace HOME] [--only-demo]

The page ``docs/source/get-started/index.md`` lists the commands of the Quick
start and shows how a run ends:

    Run completed: <name> [<id>] <n>s
    next: hmp catalog show <name> | hmp catalog diff <name> <other> | hmp export <name> --list

This tool reads both from the page, so a change to the page is a change to the
check. It runs each command after the ``pip install`` line, with ``HOME`` and
``HMP_STATE_HOME`` in a scratch folder so ``~/hydromodpy`` is the scratch workspace, and with
``hmp`` run as ``python -m hydromodpy`` from the current environment. For each
``hmp run`` the last two lines of output must have the shape the page shows,
with the same run name on both lines. Exit code 1 when a command fails or a
line differs.

``--only-demo`` stops after the first ``hmp run``: the demo needs no download
except the solver itself. The rest fetches example 04 (92 MiB) and needs the
network.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "source" / "get-started" / "index.md"
QUICK_START = re.compile(r"^## Quick start\s*$", re.MULTILINE)
FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def quick_start_commands(text: str) -> list[list[str]]:
    """Return the commands of the first shell block of the Quick start, split like a shell."""
    start = QUICK_START.search(text)
    if start is None:
        raise ValueError("the page has no '## Quick start' heading")
    for fence in FENCE.finditer(text, start.end()):
        if fence.group(1) in ("bash", "sh", "console"):
            return [shlex.split(line) for line in fence.group(2).splitlines() if line.strip()]
    raise ValueError("the Quick start has no shell block")


def promised_lines(text: str) -> tuple[str, str]:
    """Return the two lines the page shows at the end of a run."""
    for fence in FENCE.finditer(text):
        if fence.group(1) != "text":
            continue
        lines = [line for line in fence.group(2).splitlines() if line.strip()]
        if (
            len(lines) == 2
            and lines[0].startswith("Run completed:")
            and lines[1].startswith("next:")
        ):
            return lines[0], lines[1]
    raise ValueError("the page shows no 'Run completed' block")


def line_patterns(first: str, second: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """Turn the two promised lines into patterns.

    The run name, the eight-character id and the duration are the reader's. The
    name on the second line stands where the page writes the name of the first,
    and ``<other>`` stands for any run. Every name group must hold the same text.
    """
    match = re.match(r"Run completed: (\S+) \[[0-9a-f]+\] \d+s$", first)
    if match is None:
        raise ValueError(f"cannot read the promised line: {first!r}")
    shown = match.group(1)
    head = r"Run completed: (\S+) \[[0-9a-f]{8}\] \d+(?:\.\d+)?s"
    tail = re.escape(second).replace(re.escape(shown), r"(\S+)").replace(r"<other>", r"\S+")
    tail = tail.replace(r"\<other\>", r"\S+")
    return re.compile(f"^{head}$"), re.compile(f"^{tail}$")


def lines_match(done: re.Pattern[str], following: re.Pattern[str], last: list[str]) -> bool:
    """Tell whether two output lines have the shape of the page and name the same run."""
    if len(last) < 2:
        return False
    first, second = done.match(last[0]), following.match(last[1])
    if first is None or second is None:
        return False
    return all(name == first.group(1) for name in second.groups())


def expand(command: list[str], home: Path) -> list[str]:
    """Return the argument list that runs a page command in this environment.

    ``~`` is the scratch ``home``, never the home of the user who runs the check:
    the shell of the page would expand it in the child, and so does this.
    """
    if command[0] == "hmp":
        command = [sys.executable, "-m", "hydromodpy", *command[1:]]
    return [
        str(home) + part[1:] if part == "~" or part.startswith("~/") else part for part in command
    ]


KEPT_HMP_VARIABLES = frozenset({"HMP_CACHE_HOME", "HMP_BIN"})
"""The ``HMP_*`` variables the page commands inherit: caches, never user state."""


def scratch_env(workspace: Path) -> dict[str, str]:
    """Return the environment of the page commands: everything they write stays in ``workspace``.

    ``HOME`` makes ``~/hydromodpy`` the scratch workspace. The state folder (the
    index of runs) is scratch too: a run an earlier check left in it would answer
    "nothing to do" instead of ending as the page shows. A fresh user has no
    ``HMP_*`` variable: ``HMP_WORKSPACE`` or ``HMP_PROJECT_ROOT`` would point the
    commands at a real project, so none is passed on but the download cache and
    the solver folder (``KEPT_HMP_VARIABLES``), which only save a download.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("HMP_") or key in KEPT_HMP_VARIABLES
    }
    env.update(
        HOME=str(workspace),
        USERPROFILE=str(workspace),
        HMP_STATE_HOME=str(workspace / ".hmp-state"),
        # The commands import the hydromodpy of this tree, whatever the folder they run from.
        PYTHONPATH=os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")])),
    )
    return env


def check(workspace: Path, only_demo: bool) -> list[str]:
    """Run the Quick start and return one line per problem."""
    text = PAGE.read_text(encoding="utf-8")
    commands = quick_start_commands(text)
    done_pattern, next_pattern = line_patterns(*promised_lines(text))
    env = scratch_env(workspace)
    # An empty folder of the scratch home: the workspace itself is named
    # hydromodpy and would shadow the package from its parent folder.
    cwd = workspace / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    for command in commands:
        if command[0] in ("pip", "python") and "install" in command:
            continue
        shown = " ".join(command)
        # The commands run inside the scratch home, so no workspace above the
        # folder of the caller is found.
        completed = subprocess.run(
            expand(command, workspace),
            env=env,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        print(f"$ {shown} -> exit {completed.returncode}", flush=True)
        if completed.returncode != 0:
            problems.append(f"{shown}: exit {completed.returncode}\n{completed.stderr[-800:]}")
            break
        if command[:2] == ["hmp", "run"]:
            lines = [ln for ln in (completed.stdout + completed.stderr).splitlines() if ln.strip()]
            last = lines[-2:]
            if not lines_match(done_pattern, next_pattern, last):
                problems.append(f"{shown}: the last lines differ from the page: {last!r}")
            if only_demo:
                break
    return problems


def main(argv: list[str] | None = None) -> int:
    """Parse the command line, run the check and return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", type=Path, default=None, help="the scratch HOME")
    parser.add_argument("--only-demo", action="store_true", help="stop after the first run")
    args = parser.parse_args(argv)
    if args.workspace is None:
        with tempfile.TemporaryDirectory(prefix="hmp-quickstart-") as tmp:
            problems = check(Path(tmp), args.only_demo)
    else:
        args.workspace.mkdir(parents=True, exist_ok=True)
        problems = check(args.workspace, args.only_demo)
    for problem in problems:
        print(problem)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
