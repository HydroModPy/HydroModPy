"""A solver package does not read another one's private surface.

``python.md`` bans a ``_private`` attribute used outside its own package, and
nothing enforced it on the solver tree. F8a measured the cost of that: the
MODFLOW 6 build carried the stream/ocean role of its constant-head cells and
the dispatch of its exposed-band coupling as private attributes on the model
object, and the shared MODFLOW helpers read both. One was the only trace of
which CHD rows are a stream, and it existed nowhere on disk; the other was a
dispatch decision encoded as a leftover attribute.

The rule is per solver sub-package: a private name read inside
``hydromodpy/solver/<package>/`` must be declared somewhere in that same
sub-package. Both spellings of a read count, ``obj._name`` and
``getattr(obj, "_name")``, because a gate that only saw the second one would
have let the first walk straight through it. ``self`` and ``cls`` are a
module's own object and are not a read of somebody else's surface; dunders are
Python's own surface. The scope is ``solver/`` and not the repository: the rest
of the tree carries some fifty such reads that belong to other phases, and a
gate that is born red guards nothing.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SOLVER_ROOT = REPO_ROOT / "hydromodpy" / "solver"

OWN_OBJECT_NAMES = frozenset({"self", "cls"})


def _is_private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _sub_package(path: pathlib.Path) -> str:
    return path.relative_to(SOLVER_ROOT).parts[0]


def _declared_names(tree: ast.AST) -> set[str]:
    """Private names this module brings into existence, however it does it."""
    declared: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del):
            if _is_private(node.attr):
                declared.add(node.attr)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute):
            if _is_private(node.target.attr):
                declared.add(node.target.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if _is_private(node.name):
                declared.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if _is_private(node.id):
                declared.add(node.id)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if _is_private(bound):
                    declared.add(bound)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and _is_private(node.args[1].value)
        ):
            declared.add(node.args[1].value)
    return declared


def _read_names(tree: ast.AST) -> list[tuple[int, str]]:
    """Private names this module reads off an object that is not its own."""
    reads: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            own = isinstance(node.value, ast.Name) and node.value.id in OWN_OBJECT_NAMES
            if _is_private(node.attr) and not own:
                reads.append((node.lineno, node.attr))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and _is_private(node.args[1].value)
        ):
            reads.append((node.lineno, node.args[1].value))
    return reads


@pytest.fixture(scope="module")
def solver_trees() -> dict[pathlib.Path, ast.AST]:
    return {path: ast.parse(path.read_text(encoding="utf-8")) for path in SOLVER_ROOT.rglob("*.py")}


def test_a_solver_package_reads_only_the_private_names_it_declares(solver_trees) -> None:
    declared_by_package: dict[str, set[str]] = {}
    for path, tree in solver_trees.items():
        declared_by_package.setdefault(_sub_package(path), set()).update(_declared_names(tree))

    offenders: list[str] = []
    for path, tree in solver_trees.items():
        package = _sub_package(path)
        for lineno, name in _read_names(tree):
            if name not in declared_by_package[package]:
                relative = path.relative_to(REPO_ROOT)
                offenders.append(
                    f"{relative}:{lineno} reads {name}, which {package} never declares"
                )

    assert not offenders, "A solver package reads a private name it does not own:\n" + "\n".join(
        sorted(offenders)
    )


def test_the_shared_modflow_helpers_read_no_private_backend_name(solver_trees) -> None:
    """The regression F8a removed, stated as the narrow fact it was.

    ``modflow_common`` serves both MODFLOW 6 and MODFLOW-NWT, so every private
    name it reaches for belongs to one backend and is invisible to the other.
    """
    shared = SOLVER_ROOT / "modflow_common"
    declared: set[str] = set()
    for path, tree in solver_trees.items():
        if shared in path.parents:
            declared.update(_declared_names(tree))

    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno} reads {name}"
        for path, tree in solver_trees.items()
        if shared in path.parents
        for lineno, name in _read_names(tree)
        if name not in declared
    ]

    assert not offenders, "modflow_common reaches into a backend's private surface:\n" + "\n".join(
        sorted(offenders)
    )


def test_the_gate_sees_a_dotted_read_and_not_only_a_getattr() -> None:
    """The gate's own blind spot, pinned.

    A first draft only matched ``getattr(obj, "_name")``. A plain
    ``obj._name`` walked through it untouched, which is the spelling most of
    the repository actually uses.
    """
    tree = ast.parse(
        "value = model._stream_support_mask\nother = getattr(m, '_ocean_mask', None)\n"
    )

    assert [name for _, name in _read_names(tree)] == [
        "_stream_support_mask",
        "_ocean_mask",
    ]
    assert _read_names(ast.parse("value = self._cache\n")) == []
    assert _read_names(ast.parse("value = obj.__dict__\n")) == []
