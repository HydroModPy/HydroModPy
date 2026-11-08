"""Rule 6: a science module imports numpy, the standard library and one neighbour of its folder.

The rule keeps a kernel readable on its own: a hydrogeologist opens one file and
finds numpy and at most one other file beside it. The gate reads the syntax tree
of every module of each folder in the table, ``TYPE_CHECKING`` blocks and
function bodies included, because an import hidden there is still a dependency.
A folder of rule 6 joins the table with one row.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

SCIENCE_FOLDERS = (
    "hydromodpy/model/soil",
    "hydromodpy/model/initial",
)
"""The folders that rule 6 holds, one per row."""

ALLOWED_THIRD_PARTY = frozenset({"numpy"})


def _dotted(path: pathlib.Path) -> str:
    return ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)


def _imported_modules(tree: ast.AST, *, package: str) -> list[tuple[int, str]]:
    """Every ``(line, absolute module)`` the tree imports, relative imports resolved."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                module = f"{base}.{node.module}" if node.module else base
                if node.module is None:
                    found.extend((node.lineno, f"{base}.{alias.name}") for alias in node.names)
                    continue
            else:
                module = node.module or ""
                if module == package:
                    found.extend((node.lineno, f"{module}.{alias.name}") for alias in node.names)
                    continue
            if module == "__future__":
                continue
            found.append((node.lineno, module))
    return found


def _neighbours_named(module: str, folder: str) -> str | None:
    """The neighbour module ``module`` names in ``folder``, or ``None`` when it is outside."""
    if module == folder:
        return module
    prefix = folder + "."
    if not module.startswith(prefix):
        return None
    return prefix + module[len(prefix) :].split(".")[0]


def violations_of(path: pathlib.Path, source: str, folder: str) -> list[str]:
    """What breaks rule 6 in one module of ``folder``."""
    own = _dotted(path) if path.name != "__init__.py" else _dotted(path.parent)
    tree = ast.parse(source)
    found: list[str] = []
    neighbours: set[str] = set()
    for line, module in _imported_modules(tree, package=folder):
        top = module.split(".")[0]
        if top == "hydromodpy":
            neighbour = _neighbours_named(module, folder)
            if neighbour is None:
                found.append(f"line {line} imports {module}, outside {folder}")
            elif neighbour != own:
                neighbours.add(neighbour)
        elif top in ALLOWED_THIRD_PARTY or top in sys.stdlib_module_names:
            continue
        else:
            found.append(f"line {line} imports {module}, a third-party module other than numpy")
    if len(neighbours) > 1:
        found.append(f"imports {len(neighbours)} neighbours: {', '.join(sorted(neighbours))}")
    return found


def _modules(folder: str) -> list[pathlib.Path]:
    return sorted((REPO_ROOT / folder).glob("*.py"))


@pytest.mark.parametrize("folder", SCIENCE_FOLDERS)
def test_every_module_of_a_science_folder_keeps_rule_6(folder: str) -> None:
    modules = _modules(folder)
    assert modules, f"{folder} holds no module"
    dotted_folder = folder.replace("/", ".")
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {problem}"
        for path in modules
        for problem in violations_of(path, path.read_text(encoding="utf-8"), dotted_folder)
    ]

    assert not offenders, "Rule 6 is broken:\n" + "\n".join(offenders)


FOLDER = "hydromodpy.model.initial"
HERE = REPO_ROOT / "hydromodpy" / "model" / "initial" / "heads.py"

GATE_CASES = (
    ("numpy and the standard library", "import numpy as np\nfrom dataclasses import field\n", 0),
    ("one neighbour", "from hydromodpy.model.initial.state import HeadRule\n", 0),
    ("one neighbour, relative", "from .state import HeadRule\n", 0),
    ("the package itself", "from hydromodpy.model.initial import state\n", 0),
    ("pandas", "import pandas as pd\n", 1),
    ("pydantic in a function", "def f():\n    from pydantic import BaseModel\n", 1),
    (
        "a sibling package under TYPE_CHECKING",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from hydromodpy.model.flow import Flow\n",
        1,
    ),
    ("the kernel package", "from hydromodpy.core.units import FluxDensityMPerS\n", 1),
    (
        "two neighbours",
        "from hydromodpy.model.initial.state import HeadRule\nfrom .other import x\n",
        1,
    ),
)


@pytest.mark.parametrize(
    ("case", "source", "expected"), GATE_CASES, ids=[case for case, _, _ in GATE_CASES]
)
def test_the_gate_sees_each_kind_of_import(case: str, source: str, expected: int) -> None:
    """The gate's own angles, so a blind spot shows here before it shows in the tree."""
    del case
    assert len(violations_of(HERE, source, FOLDER)) == expected
