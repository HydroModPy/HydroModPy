"""Static guard on the workflow package: no module imports pickle or the retired checkpoint.

The tests read the source with ``ast``, so they run in milliseconds.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

WORKFLOW_PACKAGE = Path(__file__).resolve().parents[3] / "hydromodpy" / "workflow"


def imported_names(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def modules_importing(is_banned: Callable[[str], bool]) -> list[str]:
    return [
        module.relative_to(WORKFLOW_PACKAGE).as_posix()
        for module in WORKFLOW_PACKAGE.rglob("*.py")
        if any(is_banned(name) for name in imported_names(module))
    ]


def test_no_module_imports_pickle() -> None:
    assert modules_importing(lambda name: name.split(".")[-1] == "pickle") == []


def test_no_module_imports_signed_pickle() -> None:
    assert modules_importing(lambda name: "signed_pickle" in name) == []


def test_no_module_imports_the_checkpoint() -> None:
    assert modules_importing(lambda name: name.endswith("internals.checkpoint")) == []
