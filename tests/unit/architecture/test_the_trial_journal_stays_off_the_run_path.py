"""Gate: the trial journal is written by the session, never on the path of a run.

``trials.jsonl`` is written in the parent process by the session. A step of the
pipeline, a solver adapter, the run storage, the evaluation port, a trial, a lane or
a process of the pool never imports ``hydromodpy.results.session.journal``, because
a trial that wrote its own line would write it from a worker, and ``hmp run`` has
no session to write it for.

The rule is a list of what may not import it and not a list of what may, because
the journal has many readers (the session, the display modules, the campaign
commands) that none of this concerns. The scan reads the syntax tree, so a
lazy import inside a function counts as much as one at the top of the module.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TREE = Path(__file__).resolve().parents[3]
PACKAGE = TREE / "hydromodpy"

JOURNAL = "hydromodpy.results.session.journal"

# A folder bans every module under it, a file bans that module alone.
FORBIDDEN = (
    "workflow",
    "solver",
    "results/storage",
    "calibration/evaluation",
    "calibration/runners/trial.py",
    "calibration/runners/lanes.py",
    "calibration/runners/pipeline_evaluator.py",
    "calibration/runners/worker_pool.py",
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(TREE).with_suffix("")
    parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
    return ".".join(parts)


def imports_the_journal(source: str, module: str, *, is_package: bool = False) -> list[int]:
    """Return the line of every import of the journal in ``source``, written as module ``module``."""
    found: list[int] = []
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(
                alias.name == JOURNAL or alias.name.startswith(JOURNAL + ".")
                for alias in node.names
            ):
                found.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join([*anchor, base]) if base else ".".join(anchor)
            if base == JOURNAL or base.startswith(JOURNAL + "."):
                found.append(node.lineno)
            elif base == JOURNAL.rpartition(".")[0] and any(
                alias.name == JOURNAL.rpartition(".")[2] for alias in node.names
            ):
                found.append(node.lineno)
    return found


def _forbidden_files() -> list[Path]:
    files: list[Path] = []
    for entry in FORBIDDEN:
        target = PACKAGE / entry
        if target.is_dir():
            files.extend(sorted(target.rglob("*.py")))
        elif target.is_file():
            files.append(target)
    return files


def test_no_module_of_the_run_path_imports_the_journal() -> None:
    files = _forbidden_files()
    assert files, "the scan found no module to read"
    offenders = []
    for path in files:
        module = _module_name(path)
        lines = imports_the_journal(
            path.read_text(encoding="utf-8"), module, is_package=path.name == "__init__.py"
        )
        offenders.extend(f"{path.relative_to(TREE)}:{line}" for line in lines)
    assert not offenders, (
        "these modules sit on the path of a run and import the trial journal, which only "
        f"the session writes: {offenders}"
    )


def test_the_scan_reads_the_modules_it_bans() -> None:
    names = {path.relative_to(PACKAGE).as_posix() for path in _forbidden_files()}
    for required in (
        "workflow/runner.py",
        "solver/base/runner.py",
        "calibration/runners/trial.py",
        "calibration/runners/pipeline_evaluator.py",
        "calibration/runners/worker_pool.py",
    ):
        assert required in names


def test_the_journal_is_still_imported_by_the_session() -> None:
    """A control: the scan finds the import where it belongs, so a silent scan is not a pass."""
    session = PACKAGE / "results" / "session"
    modules = [
        path
        for path in sorted(session.rglob("*.py"))
        if path.name != "journal.py"
        and imports_the_journal(
            path.read_text(encoding="utf-8"),
            _module_name(path),
            is_package=path.name == "__init__.py",
        )
    ]
    assert modules, "no module of results/session imports the journal, the detector is blind"


@pytest.mark.parametrize(
    ("source", "module", "is_package", "expected"),
    [
        ("import hydromodpy.results.session.journal\n", "hydromodpy.workflow.runner", False, [1]),
        (
            "import hydromodpy.results.session.journal as j\n",
            "hydromodpy.workflow.runner",
            False,
            [1],
        ),
        (
            "from hydromodpy.results.session.journal import read_trials\n",
            "hydromodpy.workflow.runner",
            False,
            [1],
        ),
        (
            "from hydromodpy.results.session import journal\n",
            "hydromodpy.workflow.runner",
            False,
            [1],
        ),
        (
            "def f():\n    from hydromodpy.results.session.journal import TrialLine\n",
            "hydromodpy.solver.base.runner",
            False,
            [2],
        ),
        (
            "from ...results.session.journal import read_trials\n",
            "hydromodpy.workflow.a.b",
            False,
            [1],
        ),
        ("from . import journal\n", "hydromodpy.results.session", True, [1]),
        ("from .journal import read_trials\n", "hydromodpy.results.session.view", False, [1]),
        ("from hydromodpy.results.session import descriptor\n", "hydromodpy.workflow.a", False, []),
        (
            "from hydromodpy.results.session.view import Session\n",
            "hydromodpy.workflow.a",
            False,
            [],
        ),
        ("import hydromodpy.results.session.journal_x\n", "hydromodpy.workflow.a", False, []),
    ],
)
def test_the_detector_reads_every_form_of_import(source, module, is_package, expected) -> None:
    assert imports_the_journal(source, module, is_package=is_package) == expected
