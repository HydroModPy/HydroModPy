"""Rule 6: a science module imports numpy, the standard library and one neighbour of its folder.

The rule keeps a kernel readable on its own: a hydrogeologist opens one file and
finds numpy and at most one other file beside it. The gate reads the syntax tree
of every module of each folder in the table, ``TYPE_CHECKING`` blocks and
function bodies included, because an import hidden there is still a dependency.
A folder of rule 6 joins the table with one row.

Two folders hold the rule with exceptions, ``catchment/stream_network`` and
``core/scoring``. Their modules read the kernel, the receiver graph of
``catchment/drainage`` and Pydantic, and keeping them to numpy and one neighbour would
mean folding ``catchment/drainage`` into the folder, which is the work of lot 4.19.
``ALLOWED_OUTSIDE`` names each import that is let through, with its reason. The table
can only shrink: an import it does not list fails the gate, a line that no module
uses any more fails it too, and the table cannot grow past its ceiling.
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
    "hydromodpy/catchment/stream_network",
    "hydromodpy/core/scoring",
)
"""The folders that rule 6 holds, one per row."""

ALLOWED_THIRD_PARTY = frozenset({"numpy"})

_KERNEL = "the kernel, which every layer reads"
_DRAINAGE = (
    "the receiver graph, the distances and the flood live in catchment/drainage until lot 4.19"
)
_NEIGHBOUR = "the criterion modules read each other's types until lot 4.19 folds the folder"
_STREAM = "hydromodpy/catchment/stream_network/"
_SCORING = "hydromodpy/core/scoring/"
_CATCHMENT = "hydromodpy.catchment.stream_network."

ALLOWED_OUTSIDE: tuple[tuple[str, str, str], ...] = (
    (_STREAM + "cost.py", "hydromodpy.catchment.drainage.distance", _DRAINAGE),
    (_STREAM + "cost.py", _CATCHMENT + "geometry", _NEIGHBOUR),
    (_STREAM + "cost.py", _CATCHMENT + "network", _NEIGHBOUR),
    (_STREAM + "extent.py", "hydromodpy.catchment.drainage.distance", _DRAINAGE),
    (_STREAM + "extent.py", "hydromodpy.catchment.drainage.graph", _DRAINAGE),
    (_STREAM + "extent.py", "hydromodpy.catchment.drainage.routing", _DRAINAGE),
    (_STREAM + "extent.py", "hydromodpy.core.logging", _KERNEL),
    (_STREAM + "extent.py", "hydromodpy.core.scoring.stream_defaults", _KERNEL),
    (_STREAM + "extent.py", "hydromodpy.core.units.parse", _KERNEL),
    (
        _STREAM + "geometry.py",
        "hydromodpy.catchment.algorithms.network_heads",
        "the heads candidates come from catchment/algorithms",
    ),
    (_STREAM + "geometry.py", "hydromodpy.catchment.drainage.distance", _DRAINAGE),
    (_STREAM + "geometry.py", "hydromodpy.catchment.drainage.filling", _DRAINAGE),
    (_STREAM + "geometry.py", "hydromodpy.catchment.drainage.graph", _DRAINAGE),
    (_STREAM + "geometry.py", "hydromodpy.core.logging", _KERNEL),
    (_STREAM + "geometry.py", "hydromodpy.core.scoring.stream_defaults", _KERNEL),
    (_STREAM + "geometry.py", _CATCHMENT + "heads", _NEIGHBOUR),
    (_STREAM + "geometry.py", _CATCHMENT + "network", _NEIGHBOUR),
    (
        _STREAM + "heads.py",
        "hydromodpy.catchment.algorithms.network_heads",
        "the heads candidates come from catchment/algorithms",
    ),
    (_STREAM + "heads.py", "hydromodpy.catchment.drainage.distance", _DRAINAGE),
    (_STREAM + "heads.py", "hydromodpy.catchment.drainage.graph", _DRAINAGE),
    (_STREAM + "heads.py", "hydromodpy.core.logging", _KERNEL),
    (
        _STREAM + "heads.py",
        "scipy.spatial",
        "the nearest landing cell of a head is a KD-tree query",
    ),
    (_STREAM + "network.py", "hydromodpy.catchment.drainage.distance", _DRAINAGE),
    (_STREAM + "network.py", "hydromodpy.catchment.drainage.graph", _DRAINAGE),
    (_SCORING + "cost_margin.py", "hydromodpy.core.units.quantities", _KERNEL),
    (_SCORING + "stream_defaults.py", "pydantic", "the defaults are one Pydantic model"),
    (_SCORING + "stream_defaults.py", "hydromodpy.core.config_kit.base", _KERNEL),
    (_SCORING + "stream_defaults.py", "hydromodpy.core.config_kit.profile", _KERNEL),
    (_SCORING + "stream_defaults.py", "hydromodpy.core.units.quantities", _KERNEL),
)
"""``(module, import, reason)`` for each import of rule 6 that is let through.

``import`` is the module as the file writes it, for a neighbour too."""

ALLOWED_OUTSIDE_CEILING = 29
"""The table may shrink and never grow: lower this number with every line removed."""


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


def _scan(
    path: pathlib.Path,
    source: str,
    folder: str,
    allowed: frozenset[tuple[str, str]],
) -> tuple[list[str], set[tuple[str, str]]]:
    """What breaks rule 6 in one module of ``folder``, and which exemptions it used."""
    own = _dotted(path) if path.name != "__init__.py" else _dotted(path.parent)
    where = path.relative_to(REPO_ROOT).as_posix()
    tree = ast.parse(source)
    found: list[str] = []
    used: set[tuple[str, str]] = set()
    neighbours: set[str] = set()
    for line, module in _imported_modules(tree, package=folder):
        top = module.split(".")[0]
        if top == "hydromodpy":
            neighbour = _neighbours_named(module, folder)
            if neighbour is None:
                if (where, module) in allowed:
                    used.add((where, module))
                else:
                    found.append(f"line {line} imports {module}, outside {folder}")
            elif neighbour != own:
                if (where, neighbour) in allowed:
                    used.add((where, neighbour))
                else:
                    neighbours.add(neighbour)
        elif top in ALLOWED_THIRD_PARTY or top in sys.stdlib_module_names:
            continue
        elif (where, module) in allowed:
            used.add((where, module))
        else:
            found.append(f"line {line} imports {module}, a third-party module other than numpy")
    if len(neighbours) > 1:
        found.append(f"imports {len(neighbours)} neighbours: {', '.join(sorted(neighbours))}")
    return found, used


def violations_of(
    path: pathlib.Path,
    source: str,
    folder: str,
    allowed: frozenset[tuple[str, str]] = frozenset(),
) -> list[str]:
    """What breaks rule 6 in one module of ``folder``."""
    return _scan(path, source, folder, allowed)[0]


_DECLARED = frozenset((where, module) for where, module, _ in ALLOWED_OUTSIDE)


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
        for problem in violations_of(
            path, path.read_text(encoding="utf-8"), dotted_folder, _DECLARED
        )
    ]

    assert not offenders, "Rule 6 is broken:\n" + "\n".join(offenders)


def test_the_table_of_exceptions_only_shrinks() -> None:
    """Every line is used by a module, none is written twice, and the table stays under its ceiling."""
    used: set[tuple[str, str]] = set()
    for folder in SCIENCE_FOLDERS:
        dotted_folder = folder.replace("/", ".")
        for path in _modules(folder):
            used |= _scan(path, path.read_text(encoding="utf-8"), dotted_folder, _DECLARED)[1]

    assert len(_DECLARED) == len(ALLOWED_OUTSIDE), "a line of ALLOWED_OUTSIDE is written twice"
    stale = sorted(_DECLARED - used)
    assert not stale, (
        "Lines of ALLOWED_OUTSIDE no module uses any more, delete them:\n"
        + "\n".join(f"{where}: {module}" for where, module in stale)
    )
    assert len(ALLOWED_OUTSIDE) <= ALLOWED_OUTSIDE_CEILING, "ALLOWED_OUTSIDE grew past its ceiling"
    assert all(reason.strip() for _, _, reason in ALLOWED_OUTSIDE), "a line has no reason"


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


EXEMPTION_CASES = (
    (
        "a listed outside import",
        "from hydromodpy.core.logging import get_logger\n",
        "hydromodpy.core.logging",
        0,
    ),
    ("a listed third party", "from scipy.spatial import cKDTree\n", "scipy.spatial", 0),
    (
        "an outside import the table does not list",
        "from hydromodpy.core.units import x\n",
        "hydromodpy.core.logging",
        1,
    ),
    (
        "two neighbours, one of them listed",
        "from hydromodpy.model.initial.state import HeadRule\nfrom .other import x\n",
        "hydromodpy.model.initial.other",
        0,
    ),
)


@pytest.mark.parametrize(
    ("case", "source", "listed", "expected"),
    EXEMPTION_CASES,
    ids=[case for case, _, _, _ in EXEMPTION_CASES],
)
def test_the_table_lets_through_only_what_it_lists(
    case: str, source: str, listed: str, expected: int
) -> None:
    """A listed import passes for its own module, an unlisted one still fails."""
    del case
    allowed = frozenset({(HERE.relative_to(REPO_ROOT).as_posix(), listed)})
    assert len(violations_of(HERE, source, FOLDER, allowed)) == expected
