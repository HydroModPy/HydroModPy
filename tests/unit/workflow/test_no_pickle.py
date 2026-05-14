"""Static guards: pickle must not creep back into the workflow package.

These tests are pure AST scans so they run in milliseconds and provide a
loud alarm if a future contributor reintroduces a pickle dependency.
"""

from __future__ import annotations

import ast
from pathlib import Path

WORKFLOW_PACKAGE = Path(__file__).resolve().parents[3] / "hydromodpy" / "workflow"

ALLOWED_MODULES_WITH_PICKLE: frozenset[str] = frozenset()


def _imports(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_no_workflow_module_imports_pickle() -> None:
    offenders: list[str] = []
    for module in WORKFLOW_PACKAGE.rglob("*.py"):
        rel = module.relative_to(WORKFLOW_PACKAGE).as_posix()
        if rel in ALLOWED_MODULES_WITH_PICKLE:
            continue
        if "pickle" in {name.split(".")[-1] for name in _imports(module)}:
            offenders.append(rel)
    assert offenders == [], f"pickle imported in: {offenders}"


def test_no_workflow_module_imports_signed_pickle() -> None:
    offenders: list[str] = []
    for module in WORKFLOW_PACKAGE.rglob("*.py"):
        names = _imports(module)
        if any("signed_pickle" in name for name in names):
            offenders.append(module.relative_to(WORKFLOW_PACKAGE).as_posix())
    assert offenders == [], f"signed_pickle imported in: {offenders}"


def test_no_checkpoint_module_imports() -> None:
    offenders: list[str] = []
    for module in WORKFLOW_PACKAGE.rglob("*.py"):
        names = _imports(module)
        if any(name.endswith("internals.checkpoint") for name in names):
            offenders.append(module.relative_to(WORKFLOW_PACKAGE).as_posix())
    assert offenders == [], f"internals.checkpoint imported in: {offenders}"
