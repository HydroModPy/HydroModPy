"""Every plugin surface resolves a name through ``core/plugin_registry.py``.

Three facts are read in the AST of ``hydromodpy/``. Only the shared engine scans
an entry-point group. Each table of in-tree classes, ``_BUILTIN_PATHS`` or
``_BUILTIN_EXTRACTOR_PATHS``, feeds a ``PluginRegistry`` of its own module. No
module discovers classes by walking a package with ``pkgutil.iter_modules`` or
keeps a dict of loaders, outside the exceptions named below. An exception whose
file no longer holds the pattern fails the gate, so it leaves as soon as it is
lifted.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"

ENGINE = "core/plugin_registry.py"
"""The one module allowed to scan an entry-point group."""

BUILTIN_TABLES: frozenset[str] = frozenset({"_BUILTIN_PATHS", "_BUILTIN_EXTRACTOR_PATHS"})
"""The module-level names of the ``id -> "module:Class"`` tables of a registry."""

EXCEPTIONS: dict[str, dict[str, str]] = {}
"""Files that still discover classes their own way, each with the reason and who lifts it."""


def _modules() -> Iterator[tuple[str, ast.Module]]:
    for path in sorted(PKG_ROOT.rglob("*.py")):
        relative = path.relative_to(PKG_ROOT).as_posix()
        yield relative, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _called_name(node: ast.Call) -> str | None:
    """The last name of a call: ``entry_points`` for ``metadata.entry_points(...)``."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node for node in ast.walk(tree) if isinstance(node, ast.Call) and _called_name(node) == name
    ]


def _module_assignments(tree: ast.Module) -> dict[str, int]:
    """Module-level names bound by an assignment, with their line."""
    names: dict[str, int] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                names[target.id] = node.lineno
    return names


def _own_discovery(tree: ast.Module) -> list[str]:
    """What in *tree* discovers classes outside the shared engine."""
    found = [f"pkgutil.iter_modules at line {call.lineno}" for call in _calls(tree, "iter_modules")]
    found += [
        f"{name} at line {line}"
        for name, line in _module_assignments(tree).items()
        if name.endswith("_LOADERS")
    ]
    return found


def _names_in(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


MODULES = dict(_modules())


def test_only_the_shared_engine_scans_an_entry_point_group() -> None:
    offenders = [
        f"{relative}:{call.lineno}"
        for relative, tree in MODULES.items()
        if relative != ENGINE
        for call in _calls(tree, "entry_points")
    ]
    assert offenders == [], (
        "a module scans an entry-point group itself. Declare the surface as a "
        f"PluginRegistry instance instead: {offenders}"
    )
    assert _calls(MODULES[ENGINE], "entry_points"), f"{ENGINE} no longer scans a group"


def test_each_table_of_in_tree_classes_feeds_a_registry_of_its_module() -> None:
    tables: list[tuple[str, str]] = []
    unfed: list[str] = []
    for relative, tree in MODULES.items():
        declared = BUILTIN_TABLES & set(_module_assignments(tree))
        if not declared:
            continue
        fed: set[str] = set()
        for call in _calls(tree, "PluginRegistry"):
            fed |= _names_in(call)
        for name in sorted(declared):
            tables.append((relative, name))
            if name not in fed:
                unfed.append(f"{relative}::{name}")
    assert tables, "no registry table found; the scan reads the wrong tree"
    assert unfed == [], f"a table of in-tree classes resolves outside PluginRegistry: {unfed}"


def test_no_module_discovers_classes_its_own_way() -> None:
    offenders = {
        relative: found
        for relative, tree in MODULES.items()
        if relative not in EXCEPTIONS
        if (found := _own_discovery(tree))
    }
    assert offenders == {}, (
        "a module discovers classes outside the shared registry engine. Declare them "
        f"in a PluginRegistry, or name the file in EXCEPTIONS with its reason: {offenders}"
    )


@pytest.mark.parametrize("relative", sorted(EXCEPTIONS))
def test_each_exception_still_serves(relative: str) -> None:
    entry = EXCEPTIONS[relative]
    assert entry["why"] and entry["lifted_by"], relative
    tree = MODULES.get(relative)
    assert tree is not None, f"{relative} is gone: drop it from EXCEPTIONS"
    assert _own_discovery(tree), (
        f"{relative} no longer discovers classes its own way: drop it from EXCEPTIONS"
    )
