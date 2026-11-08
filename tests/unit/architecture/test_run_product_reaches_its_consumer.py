"""Who may reach the execution registry, and who receives a run's product.

``execution.models_by_run_id`` and ``execution.output_dirs_by_run_id`` were read
from nine packages, and every read outside the runner asked for the entry keyed
by the reader's own ``run.id``. That is not a registry lookup: it is a run
asking shared mutable state for something it produced itself. F8d routed those
reads through the run context. The two registries are now one,
``execution.solver_runs``, which maps a run id to its ``SolverRun``, and a
consumer receives the product of its own run as ``RunContext.solver_run``. The
registry keeps its one real purpose, the runner handing a later run the runs it
declares in ``depends_on``.

Two gates, different in kind. The runtime one is free: ``RunState`` does not
declare ``execution``, and it has ``slots``, so ``ctx.state.execution`` raises
instead of returning an empty registry. The static one is here: it names every
module allowed to touch the registry, so a new consumer that reaches back into
it fails in the unit tier rather than at the next adversarial pass.

The allowlist is short on purpose. Several of its entries read the registry
through a ``WorkflowContext``, which is the pipeline's own scope and not an
adapter's; they are listed rather than silently tolerated so that growing the
list is a decision somebody takes, not a drift.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from hydromodpy.solver.base.plan import RunContext

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "hydromodpy"

REGISTRY_MEMBERS = frozenset({"solver_runs"})

# Every module allowed to name the registry, and why. ``core/state/run_state.py``
# is absent on purpose: it declares the field and reads it nowhere, and a
# declaration is an annotated name, not an attribute this gate follows.
REGISTRY_READERS = {
    # The owner: it records what each run produced and hands a later run the
    # runs it declares in ``depends_on``.
    "solver/base/runner.py",
    # ``RunContext.of``, the one place that reads a run's product out of the
    # registry to hand it over explicitly.
    "solver/base/plan.py",
    # Releases the solver models before the derived stacks allocate; a
    # transient flopy model carries its whole stress-period data.
    "workflow/steps/derive.py",
    # A resume past the solver: puts back a SolverRun without a solver model,
    # with the folder the run solved in read from its facts, so
    # ``RunContext.of`` finds it as it does after a solve.
    "workflow/steps/run_solver.py",
    # Pipeline scope, not adapter scope: asks which dispatch the built flow
    # model resolved to, across the plan rather than for one run.
    "workflow/steps/prepare_solver/dispatch.py",
    # Pipeline scope: finds the trial's single flow run among the runs.
    "calibration/metrics/solver_extract.py",
    # Pipeline scope: lists the scratch directories a trial has to clear.
    "calibration/runners/sandbox.py",
    # A launcher, the runner's own role: a promotion hands over the solve its
    # trial kept, recording each run's SolverRun as the runner does.
    "calibration/runners/kept_solves.py",
}

# ``RunContext.of`` is the construction path for every consumer that runs after
# the solver. The runner is the exception it documents: at the time it builds a
# context, the run has produced nothing.
CONTEXT_BUILDERS = {"solver/base/plan.py", "solver/base/runner.py"}


@pytest.fixture(scope="module")
def package_trees() -> dict[str, ast.AST]:
    """Each module of the package, keyed by its path in POSIX form on every OS."""
    return {
        path.relative_to(PACKAGE_ROOT).as_posix(): ast.parse(path.read_text(encoding="utf-8"))
        for path in PACKAGE_ROOT.rglob("*.py")
    }


def _registry_reads(tree: ast.AST) -> list[tuple[int, str]]:
    """Every ``(line, member)`` where this module names the execution registry."""
    reads: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in REGISTRY_MEMBERS:
            reads.append((node.lineno, node.attr))
        elif isinstance(node, ast.Constant) and node.value in REGISTRY_MEMBERS:
            # ``getattr(execution, "solver_runs", None)`` is the same read
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
        f"{name}:{lineno} names {member}"
        for name, tree in package_trees.items()
        if name not in REGISTRY_READERS
        for lineno, member in _registry_reads(tree)
    ]

    assert not offenders, (
        "What one run produced reaches its consumer through RunContext.solver_run; "
        "these reach into the registry instead:\n" + "\n".join(sorted(offenders))
    )


def test_every_allowed_reader_still_reads_a_registry(package_trees) -> None:
    """An allowlist that outlives its entries stops being a measurement.

    A module that no longer touches a registry has to leave this list, or the
    next reader added to that module inherits a permission nobody granted it.
    """
    stale = [name for name in REGISTRY_READERS if not _registry_reads(package_trees[name])]

    assert not stale, (
        "These modules no longer read a registry and must leave the list:\n"
        + "\n".join(sorted(stale))
    )


def test_a_run_context_carries_what_its_run_produced() -> None:
    fields = {field.name for field in dataclasses.fields(RunContext)}
    assert {"solver_run", "upstream"} <= fields
    assert not fields & {"model", "output_dir", "dependency_models"}


def test_a_post_solver_context_is_built_through_the_one_path(package_trees) -> None:
    """Only the runner builds a context by hand, and it builds one with no product.

    Every other consumer runs after the solver, so a hand-built context there
    would carry ``solver_run=None`` by default: the missing product would read
    as "this run produced nothing" rather than as an error.
    """
    offenders = [
        f"{name}:{lineno}"
        for name, tree in package_trees.items()
        if name not in CONTEXT_BUILDERS
        for lineno in _context_builds(tree)
    ]

    assert not offenders, "RunContext is built outside RunContext.of:\n" + "\n".join(
        sorted(offenders)
    )


OFFENDING_SPELLINGS = (
    ("attribute", "runs = ctx.execution.solver_runs\n"),
    ("getattr string", 'runs = getattr(ctx.execution, "solver_runs", None)\n'),
    ("subscript through attribute", "d = state.execution.solver_runs[run.id].output_dir\n"),
    ("bare constant", 'KEY = "solver_runs"\n'),
)


@pytest.mark.parametrize(
    ("spelling", "source"), OFFENDING_SPELLINGS, ids=[s for s, _ in OFFENDING_SPELLINGS]
)
def test_the_gate_sees_every_spelling_of_a_registry_read(spelling: str, source: str) -> None:
    """The gate's own angles, pinned.

    F8a shipped a gate blind to the majority spelling of what it guarded, and
    F8c shipped one blind to the walrus and to an aliased import. The registry is
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
