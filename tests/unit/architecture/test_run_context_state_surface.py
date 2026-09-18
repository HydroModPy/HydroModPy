"""What a solver adapter receives of the workflow runtime is what it reads.

``RunContext.state`` was typed ``Any`` and carried the whole
``WorkflowContext``: the loaded support data, the raw TOML, the data plan, the
post-processing runner. An adapter reads three scopes of it, so everything else
was reachable and nothing said it should not be. F8c replaced the field with
``RunState``, the view of those three scopes plus the run identity.

Two facts hold the boundary, and they are different in kind. The runtime one is
the view itself: ``RunState`` has ``slots``, so a read outside its four members
raises instead of returning something. The static one is this gate: a read of a
name the view does not declare fails here, in the unit tier, without running a
solver. It follows the ``RunContext`` annotation rather than a list of variable
names, so a function that names its parameter something new is covered the day
it is written.

A read through a local alias counts: ``state = ctx.state`` then ``state.setup``
is the majority spelling in the adapters, and a gate that only saw
``ctx.state.setup`` would have missed all of them. Both bindings count, ``=``
and ``:=`` - F8a shipped a gate blind to the majority spelling of what it
guarded, and the lesson was to pin the gate's own angles rather than the one
the code happens to use today.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.run_state import RunState
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "hydromodpy"

VIEW_MEMBERS = frozenset(
    {field.name for field in dataclasses.fields(RunState)}
    | {name for name in vars(RunState) if not name.startswith("_")}
)


def _context_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names this function binds to a ``RunContext``."""
    args = node.args
    all_args = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    return {
        arg.arg
        for arg in all_args
        if isinstance(arg.annotation, ast.Name)
        and arg.annotation.id == "RunContext"
        or isinstance(arg.annotation, ast.Constant)
        and arg.annotation.value == "RunContext"
    }


def _unwrap(value: ast.expr) -> ast.expr:
    """Look through a walrus binding at the expression it carries."""
    return value.value if isinstance(value, ast.NamedExpr) else value


def _binds_the_state(value: ast.expr, contexts: set[str]) -> bool:
    value = _unwrap(value)
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "state"
        and isinstance(value.value, ast.Name)
        and value.value.id in contexts
    )


def _state_aliases(node: ast.AST, contexts: set[str]) -> set[str]:
    """Locals bound to ``<context>.state`` inside this function, however bound."""
    aliases: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Assign):
            targets = child.targets
        elif isinstance(child, ast.AnnAssign | ast.NamedExpr):
            targets = [child.target]
        else:
            continue
        if child.value is not None and _binds_the_state(child.value, contexts):
            aliases.update(target.id for target in targets if isinstance(target, ast.Name))
    return aliases


def _view_reads(tree: ast.AST) -> list[tuple[int, str]]:
    """Every ``(line, member)`` this module reads off a run-context state."""
    reads: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        contexts = _context_parameters(node)
        if not contexts:
            continue
        aliases = _state_aliases(node, contexts)
        for child in ast.walk(node):
            if not isinstance(child, ast.Attribute):
                continue
            inner = _unwrap(child.value)
            through_context = _binds_the_state(inner, contexts)
            through_alias = isinstance(inner, ast.Name) and inner.id in aliases
            if through_context or through_alias:
                reads.append((child.lineno, child.attr))
    return reads


def _view_names(tree: ast.AST) -> set[str]:
    """Every local name this module binds to ``RunState``, alias included."""
    names = {"RunState"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.update(
                alias.asname or alias.name for alias in node.names if alias.name == "RunState"
            )
    return names


def _view_builds(tree: ast.AST) -> list[int]:
    """Lines where this module calls the view constructor, alias or not."""
    names = _view_names(tree)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in names)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "RunState")
        )
    ]


@pytest.fixture(scope="module")
def package_trees() -> dict[pathlib.Path, ast.AST]:
    return {
        path: ast.parse(path.read_text(encoding="utf-8")) for path in PACKAGE_ROOT.rglob("*.py")
    }


def test_the_package_reads_only_what_the_view_declares(package_trees) -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno} reads state.{member}"
        for path, tree in package_trees.items()
        for lineno, member in _view_reads(tree)
        if member not in VIEW_MEMBERS
    ]

    assert not offenders, (
        "A run context hands an adapter a RunState; these reach past it:\n"
        + "\n".join(sorted(offenders))
    )


def test_the_view_is_built_in_one_place(package_trees) -> None:
    """Production code asks ``RunState.of`` for the view, never assembles one.

    A hand-built view can quietly omit a scope: every member has a default, so
    the omission reads as an empty registry rather than as an error.
    """
    home = PACKAGE_ROOT / "core" / "state" / "run_state.py"
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}"
        for path, tree in package_trees.items()
        if path != home
        for lineno in _view_builds(tree)
    ]

    assert not offenders, "RunState is assembled outside RunState.of:\n" + "\n".join(
        sorted(offenders)
    )


def test_a_run_context_refuses_anything_but_the_view() -> None:
    run = ProcessRun(
        id="flow_main::modflow6",
        process_id="flow_main",
        process_type="flow",
        solver="modflow6",
    )
    plan = SimulationPlan(name="demo", description="demo", runs=(run,))

    with pytest.raises(TypeError, match="must be a RunState view"):
        RunContext(plan=plan, run=run, state=SimpleNamespace(setup=None))


OFFENDING_SPELLINGS = (
    ("direct", "def f(ctx: RunContext) -> None:\n    return ctx.state.raw_toml\n"),
    ("string annotation", 'def f(ctx: "RunContext") -> None:\n    return ctx.state.raw_toml\n'),
    (
        "assigned alias",
        "def f(ctx: RunContext) -> None:\n    s = ctx.state\n    return s.raw_toml\n",
    ),
    (
        "walrus alias",
        "def f(ctx: RunContext) -> None:\n"
        "    if (s := ctx.state) is not None:\n"
        "        return s.raw_toml\n",
    ),
    ("walrus read", "def f(ctx: RunContext) -> None:\n    return (s := ctx.state).raw_toml\n"),
    (
        "annotated alias",
        "def f(ctx: RunContext) -> None:\n    s: RunState = ctx.state\n    return s.raw_toml\n",
    ),
)


@pytest.mark.parametrize(
    ("spelling", "source"), OFFENDING_SPELLINGS, ids=[s for s, _ in OFFENDING_SPELLINGS]
)
def test_the_gate_sees_every_spelling_of_a_read(spelling: str, source: str) -> None:
    """The gate's own angles, pinned.

    F8a shipped a gate that saw one spelling of what it guarded and let the
    majority one through. Its blind spot was found by an adversarial pass, not
    by the gate. This test is that pass, kept.
    """
    del spelling
    assert [member for _, member in _view_reads(ast.parse(source))] == ["raw_toml"]


def test_the_gate_sees_an_aliased_import_of_the_view() -> None:
    source = "from hydromodpy.core.state.run_state import RunState as RS\n\n\ndef f():\n    return RS()\n"
    assert _view_builds(ast.parse(source)) == [5]


def test_the_view_carries_no_catalog_handle() -> None:
    """The handle reaches an adapter through ``RunContext.store``, and only there.

    F8b made the catalog of a run a handle opened by whoever writes and closed
    before the step returns. A view that carried one would put it back inside
    the state, where the process boundary cannot follow it.
    """
    assert "store" not in VIEW_MEMBERS
