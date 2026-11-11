"""Nothing in the reading and drawing layers names a solver backend.

A run is read, scored, drawn and compared through what a backend declared it
wrote, never through who wrote it: results, calibration, display and the run
comparison take every backend as it comes, the shipped ones and the plugins.
The gate scans the code of the four zones by its tree, for the names the
registry ships and the old spellings, and imports of a backend package. The
table of exemptions is empty at the close, and a row that no site serves any
more fails the test that reads it, so a retired row leaves in the same
change that retires it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from hydromodpy.solver.base.registry import solvers

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
PACKAGE = ROOT / "hydromodpy"

_ZONES = {
    "results": PACKAGE / "results",
    "calibration": PACKAGE / "calibration",
    "display": PACKAGE / "display",
    "project/compare": PACKAGE / "project" / "compare.py",
}

# The spellings an earlier release gave a backend name. With the aliases of
# ``hmp ls`` gone, a name is one name; a sentence that carries an old
# one is a sentence about a backend that no longer listens.
_OLD_SPELLINGS = ("modflownwt", "mf6", "nwt", "gr4j")

EXEMPTIONS: dict[str, str] = {}
"""Flagged sites the gate still reads a backend name at, by file, with why.

Empty since the lot retired the last writes of a backend name outside its
folder. A row whose file is gone, or whose sites are all gone, fails the
test that reads this table.
"""


def _backend_names() -> tuple[str, ...]:
    """The names the registry ships, plus the old spellings written here.

    A registry id is the process type and the name joined by one underscore,
    so the name is the part after its first: ``flow_modflow6`` gives
    ``modflow6``.
    """
    names = tuple(key.split("_", 1)[1] for key in solvers.names(shipped_only=True))
    return (*names, *_OLD_SPELLINGS)


def _zone_files():
    for label, path in _ZONES.items():
        files = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for py in files:
            yield label, py, py.relative_to(ROOT).as_posix()


def _mark_documentation(tree: ast.Module) -> None:
    """Docstrings, and docstring lines beside a module constant, sit out."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body[0].value._is_doc = True
        if isinstance(node, (ast.Module, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            for first, second in zip(body, body[1:]):
                if (
                    isinstance(first, (ast.Assign, ast.AnnAssign))
                    and isinstance(second, ast.Expr)
                    and isinstance(second.value, ast.Constant)
                    and isinstance(second.value.value, str)
                ):
                    second.value._is_doc = True


def _import_modules(node: ast.AST) -> list[str]:
    modules = []
    if isinstance(node, ast.ImportFrom) and node.module:
        modules.append(str(node.module))
    if isinstance(node, ast.Import):
        modules.extend(str(alias.name) for alias in node.names)
    return modules


def _scan() -> list[tuple[str, str, str]]:
    """Flagged sites of the four zones: a name token or a backend import."""
    names = _backend_names()
    sites: list[tuple[str, str, str]] = []
    for label, py, rel in _zone_files():
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        _mark_documentation(tree)
        for node in ast.walk(tree):
            for module in _import_modules(node):
                folder = module[len("hydromodpy.solver.") :].split(".", 1)
                if module.startswith("hydromodpy.solver.") and folder and folder[0] in names:
                    sites.append((label, f"{rel}:{node.lineno}", f"imports {module}"))
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if not node.value.strip() or getattr(node, "_is_doc", False):
                continue
            for name in names:
                if name in set(re.findall(r"[A-Za-z0-9_]+", node.value)):
                    sites.append((label, f"{rel}:{node.lineno}", f"{name} in {node.value[:70]!r}"))
    return sites


def test_the_four_reading_zones_name_no_backend() -> None:
    flagged = _scan()
    sites = [
        f"[{label}] {site} {detail}" for label, site, detail in flagged if site not in EXEMPTIONS
    ]
    assert sites == [], (
        "a reading zone carries a backend name that no exemption row serves:\n  "
        + "\n  ".join(sites)
    )


def test_an_exemption_row_that_no_site_serves_any_more_fails() -> None:
    """A retired row leaves with the change that retires it."""
    served = {site for _label, site, _detail in _scan()}
    stale = sorted(set(EXEMPTIONS) - served)
    assert stale == [], "an exemption row serves no flagged site any more:\n  " + "\n  ".join(stale)
