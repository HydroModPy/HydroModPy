"""Who may reach the execution registries, and who receives a run's product.

``execution.models_by_run_id`` and ``execution.output_dirs_by_run_id`` were read
from nine packages, and every read outside the runner asked for the entry keyed
by the reader's own ``run.id``. That is not a registry lookup: it is a run
asking shared mutable state for something it produced itself. F8d routed those
reads through ``RunContext.model`` and ``RunContext.output_dir``, and left the
registries to their one real purpose - the runner resolving the models a later
run declares in ``depends_on``.

Two gates, different in kind. The runtime one is free: ``RunState`` no longer
declares ``execution``, and it has ``slots``, so ``ctx.state.execution`` raises
instead of returning an empty registry. The static one is here: it names every
module allowed to touch a registry, so a new consumer that reaches back into
one fails in the unit tier rather than at the next adversarial pass.

The allowlist is short on purpose. Three of its entries read a registry through
a ``WorkflowContext``, which is the pipeline's own scope and not an adapter's;
they are listed rather than silently tolerated so that growing the list is a
decision somebody takes, not a drift.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from hydromodpy.simulation.planning.plan import RunContext

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "hydromodpy"

REGISTRY_MEMBERS = frozenset({"models_by_run_id", "output_dirs_by_run_id"})

# Every module allowed to name a registry, and why. ``core/state/execution.py``
# is absent on purpose: it declares the two fields and reads neither, and a
# declaration is an annotated name, not an attribute this gate follows.
REGISTRY_READERS = {
    # The owner: it records what each run produced and resolves what the next
    # one declares in ``depends_on``.
    "simulation/execution/runner.py",
    # ``RunContext.of``, the one place that reads a run's product out of the
    # registry to hand it over explicitly.
    "simulation/planning/plan.py",
    # Releases the models before the derived stacks allocate; a transient flopy
    # model carries its whole stress-period data.
    "workflow/steps/derive.py",
    # Pipeline scope, not adapter scope: asks which dispatch the built flow
    # model resolved to, across the plan rather than for one run.
    "workflow/steps/prepare_solver/dispatch.py",
    # Pipeline scope: finds the trial's single flow run among the models.
    "calibration/metrics/solver_extract.py",
    # Pipeline scope: lists the scratch directories a trial has to clear.
    "calibration/runners/sandbox.py",
}

# ``RunContext.of`` is the construction path for every consumer that runs after
# the solver. The runner is the exception it documents: at the time it builds a
# context, the run has produced neither a model nor an output directory.
CONTEXT_BUILDERS = {"simulation/planning/plan.py", "simulation/execution/runner.py"}


@pytest.fixture(scope="module")
def package_trees() -> dict[pathlib.Path, ast.AST]:
    return {
        path: ast.parse(path.read_text(encoding="utf-8")) for path in PACKAGE_ROOT.rglob("*.py")
    }


def _registry_reads(tree: ast.AST) -> list[tuple[int, str]]:
    """Every ``(line, member)`` where this module names an execution registry."""
    reads: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in REGISTRY_MEMBERS:
            reads.append((node.lineno, node.attr))
        elif isinstance(node, ast.Constant) and node.value in REGISTRY_MEMBERS:
            # ``getattr(execution, "models_by_run_id", None)`` is the same read
            # with the name moved into a string, and it is the spelling the
            # defensive helpers used.
            reads.append((node.lineno, str(node.value)))
    return reads


def _context_names(tree: ast.AST) -> set[str]:
    """Every local name this module binds to the context class, alias included."""
    names = {"RunContext"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.update(
                alias.asname or alias.name for alias in node.names if alias.name == "RunContext"
            )
    return names


def _context_builds(tree: ast.AST) -> list[int]:
    """Lines where this module builds a context by hand, whatever the spelling.

    A direct call, an aliased import, a dotted call through the module, and a
    ``partial`` that defers the same call all reach the constructor. A gate that
    saw only the first would pass the day somebody renamed the import.
    """
    names = _context_names(tree)
    builds: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in names:
            builds.append(node.lineno)
        elif isinstance(func, ast.Attribute) and func.attr == "RunContext":
            builds.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id in {"partial", "partialmethod"}:
            deferred = node.args[0] if node.args else None
            named = isinstance(deferred, ast.Name) and deferred.id in names
            dotted = isinstance(deferred, ast.Attribute) and deferred.attr == "RunContext"
            if named or dotted:
                builds.append(node.lineno)
    return builds


def test_only_the_named_modules_reach_an_execution_registry(package_trees) -> None:
    offenders = [
        f"{path.relative_to(PACKAGE_ROOT)}:{lineno} names {member}"
        for path, tree in package_trees.items()
        if str(path.relative_to(PACKAGE_ROOT)) not in REGISTRY_READERS
        for lineno, member in _registry_reads(tree)
    ]

    assert not offenders, (
        "What one run produced reaches its consumer through RunContext.model and "
        "RunContext.output_dir; these reach into the registry instead:\n"
        + "\n".join(sorted(offenders))
    )


def test_every_allowed_reader_still_reads_a_registry(package_trees) -> None:
    """An allowlist that outlives its entries stops being a measurement.

    A module that no longer touches a registry has to leave this list, or the
    next reader added to that module inherits a permission nobody granted it.
    """
    by_name = {str(path.relative_to(PACKAGE_ROOT)): tree for path, tree in package_trees.items()}
    stale = [name for name in REGISTRY_READERS if not _registry_reads(by_name[name])]

    assert not stale, (
        "These modules no longer read a registry and must leave the list:\n"
        + "\n".join(sorted(stale))
    )


def test_a_run_context_carries_what_its_run_produced() -> None:
    fields = {field.name for field in dataclasses.fields(RunContext)}
    assert {"model", "output_dir"} <= fields


def test_a_post_solver_context_is_built_through_the_one_path(package_trees) -> None:
    """Only the runner builds a context by hand, and it builds one with no product.

    Every other consumer runs after the solver, so a hand-built context there
    would carry ``model=None`` and ``output_dir=None`` by default: the missing
    product would read as "this run produced nothing" rather than as an error.
    """
    offenders = [
        f"{path.relative_to(PACKAGE_ROOT)}:{lineno}"
        for path, tree in package_trees.items()
        if str(path.relative_to(PACKAGE_ROOT)) not in CONTEXT_BUILDERS
        for lineno in _context_builds(tree)
    ]

    assert not offenders, "RunContext is built outside RunContext.of:\n" + "\n".join(
        sorted(offenders)
    )


OFFENDING_SPELLINGS = (
    ("attribute", "models = ctx.execution.models_by_run_id\n"),
    ("getattr string", 'models = getattr(ctx.execution, "models_by_run_id", None)\n'),
    ("subscript through attribute", "d = state.execution.output_dirs_by_run_id[run.id]\n"),
    ("bare constant", 'KEY = "output_dirs_by_run_id"\n'),
)


@pytest.mark.parametrize(
    ("spelling", "source"), OFFENDING_SPELLINGS, ids=[s for s, _ in OFFENDING_SPELLINGS]
)
def test_the_gate_sees_every_spelling_of_a_registry_read(spelling: str, source: str) -> None:
    """The gate's own angles, pinned.

    F8a shipped a gate blind to the majority spelling of what it guarded, and
    F8c shipped one blind to the walrus and to an aliased import. A registry is
    reached by an attribute and by a name in a string, and both count.
    """
    del spelling
    assert _registry_reads(ast.parse(source))


OFFENDING_BUILDS = (
    ("direct call", "from x import RunContext\nctx = RunContext(plan=p, run=r, state=s)\n"),
    ("aliased import", "from x import RunContext as RC\nctx = RC(plan=p, run=r, state=s)\n"),
    ("dotted call", "import x\nctx = x.RunContext(plan=p, run=r, state=s)\n"),
    (
        "deferred through partial",
        "from x import RunContext\nbuild = partial(RunContext, plan=p, run=r)\n",
    ),
)


@pytest.mark.parametrize(
    ("spelling", "source"), OFFENDING_BUILDS, ids=[s for s, _ in OFFENDING_BUILDS]
)
def test_the_gate_sees_every_spelling_of_a_hand_built_context(spelling: str, source: str) -> None:
    """The construction gate's own angles, pinned, for the same reason."""
    del spelling
    assert _context_builds(ast.parse(source))
