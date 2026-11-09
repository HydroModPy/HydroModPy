"""A flow backend of the solver registry lives in its own folder.

For each flow backend the build ships, the home is the folder of its adapter
plus the family folders the solver layout gives it. No file outside the home
imports the backend's package, and no string constant outside a docstring
carries its name: a backend can be added, replaced or removed alone, and a
plugin reaches the seal without a patch to HydroModPy. The one exception is
the declaration itself, recognized where it sits in the tree and not by a
list of falling exemptions: the dotted paths the registry imports on first
lookup, the default backend it serves, the tables of the configuration
migration (a TOML key exactly as an older release wrote it), the refused
names of the root facade, the one table that keys the transport settings
by the backend that runs them, and the demo default of a run: the template the
workspace scaffold writes and the default of the two ``SimulationConfig``
factories, which name the backend a first run plays on.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

from hydromodpy.solver.base.registry import solvers

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
PACKAGE = ROOT / "hydromodpy"
SOLVER_LAYER = PACKAGE / "solver"

# The files a backend name may reach outside its home, and only as the
# declaration: a constant assigned by the module body of one of them names a
# TOML key or a dotted path, it never reads the backend. A constant written
# in the body of a function of one of these files is never a declaration
# site, so a fallback inside a call keeps the file flagged. The default of a
# keyword parameter is a declaration too: it is the demo default of a factory.
_DECLARATION_FILES = frozenset(
    {
        "hydromodpy/solver/base/registry.py",
        "hydromodpy/config/config_migration.py",
        "hydromodpy/_lazy.py",
        "hydromodpy/model/transport/transport_config.py",
        "hydromodpy/data/workspace/scaffold.py",
        "hydromodpy/solver/base/simulation_config.py",
    }
)


def _layout() -> dict:
    return yaml.safe_load((HERE / "solver_layout.yaml").read_text(encoding="utf-8"))


def _declared_backends() -> list[str]:
    """The shipped flow backends that passed the layout: the registry's key set."""
    families = dict(_layout().get("families", {}))
    return [
        name
        for name in solvers.names("flow", shipped_only=True)
        if (SOLVER_LAYER / name).is_dir() or name in families
    ]


def _home_folders(backend: str) -> frozenset[Path]:
    """The adapter folder of *backend*, plus the family folders its layout gives it."""
    families = dict(_layout().get("families", {})).get(backend, ())
    return frozenset({SOLVER_LAYER / backend, *(SOLVER_LAYER / family for family in families)})


def _module_table_constants(tree: ast.Module) -> set[int]:
    """Ids of the string constants a module-level assignment or a parameter default holds."""
    assigned: set[int] = set()
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = [*function.args.defaults, *function.args.kw_defaults]
            for default in defaults:
                if isinstance(default, ast.Constant) and isinstance(default.value, str):
                    assigned.add(id(default))
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            for node in ast.walk(statement):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    assigned.add(id(node))
    return assigned


def _mark_documentation(tree: ast.Module) -> None:
    """Docstrings, and docstrings lines beside a module constant, sit out."""
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


def _attach_module_tables(tree: ast.Module) -> None:
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            for node in ast.walk(statement):
                if isinstance(node, ast.Constant):
                    node._module_table = True


def _import_modules(node: ast.AST) -> list[str]:
    modules = []
    if isinstance(node, ast.ImportFrom) and node.module:
        modules.append(str(node.module))
    if isinstance(node, ast.Import):
        modules.extend(str(alias.name) for alias in node.names)
    return modules


def _constant_naming(node: ast.AST, backend: str) -> bool:
    """Whether one string constant holds *backend* as a whole token."""
    return backend in set(re.findall(r"[A-Za-z0-9_]+", node.value))


def _trees_of_the_package():
    for py in sorted(PACKAGE.rglob("*.py")):
        rel = py.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        _mark_documentation(tree)
        yield py, rel, tree


def _outside_home(py: Path, home: frozenset[Path]) -> bool:
    return not any(py.is_relative_to(folder) for folder in home)


def _declaration_site(rel: str, tree: ast.Module, node: ast.AST) -> bool:
    """Whether one constant sits in a module-level table of a declaration file."""
    return rel in _DECLARATION_FILES and id(node) in _module_table_constants(tree)


@pytest.mark.parametrize("backend", _declared_backends())
def test_no_file_outside_the_home_imports_the_backend(backend: str) -> None:
    home = _home_folders(backend)
    sites = []
    for py, rel, tree in _trees_of_the_package():
        if not _outside_home(py, home):
            continue
        for node in ast.walk(tree):
            for module in _import_modules(node):
                prefix = f"hydromodpy.solver.{backend}"
                if module == prefix or module.startswith(prefix + "."):
                    sites.append(f"{rel}:{node.lineno} imports {module}")
    assert sites == [], f"a file outside the home of {backend!r} imports it:\n  " + "\n  ".join(
        sites
    )


@pytest.mark.parametrize("backend", _declared_backends())
def test_no_string_outside_the_home_carries_the_backend_name(backend: str) -> None:
    home = _home_folders(backend)
    sites = []
    for py, rel, tree in _trees_of_the_package():
        if not _outside_home(py, home):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if not node.value.strip() or getattr(node, "_is_doc", False):
                continue
            if not _constant_naming(node, backend):
                continue
            if _declaration_site(rel, tree, node):
                continue
            sites.append(f"{rel}:{node.lineno} {node.value[:70]!r}")
    assert sites == [], (
        f"a string outside the home of {backend!r} carries its name:\n  " + "\n  ".join(sites)
    )


def test_the_global_backend_is_declared_by_its_two_registry_lines_alone() -> None:
    """The one-cell backend names no module outside its folder but its registration.

    The registry declares the in-tree adapters and extractors on two lines of
    two dotted-path tables. No table of the migration or the facade carries
    the backend, because no older release wrote it.
    """
    backend = "linear_reservoir"
    named = set()
    for py, rel, tree in _trees_of_the_package():
        del py
        for statement in tree.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            if not any(
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _constant_naming(node, backend)
                for node in ast.walk(statement)
            ):
                continue
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            names = "/".join(target.id for target in targets if isinstance(target, ast.Name))
            named.add(f"{rel}:{names or statement.lineno}")
    assert named == {
        "hydromodpy/solver/base/registry.py:_BUILTIN_PATHS",
        "hydromodpy/solver/base/registry.py:_BUILTIN_EXTRACTOR_PATHS",
    }, sorted(named)


def test_a_fallback_inside_a_function_of_a_declaration_file_is_flagged() -> None:
    """The module-table rule reads the statement it sits under, not its file alone.

    The name sits in the body of a function: no module-level table holds it,
    so the gate flags it. Its value comes from the constant the registry
    declares instead.
    """
    tree = ast.parse("def _section(name):\n    return _SECTIONS.get(name, 'modflow6')\n")
    _attach_module_tables(tree)
    constants = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]

    assert len(constants) == 1
    assert not _module_table_constants(tree)
    assert _constant_naming(constants[0], "modflow6")
