"""Every member of ``WorkflowContext`` is read through a receiver typed as one.

The target of F8 said ``WorkflowContext`` no longer exists. Measured, that was a
formula and not a contract: 130 occurrences over 29 files, 91 of them type
annotations and **three** instantiations. It is not an object everyone builds,
it is a typed parameter threaded from step to step, and the coupling that
matters is the mutable ``SetupContext`` reached through it, not the name - a
narrow view does not stop ``view.setup.domain = ...``. D233 settles the phase on
the honest reading: the class stays, and every member it carries has a reader
this gate measures.

What the gate caught the day it was written: ``postprocess_runner``. Zero reads
and zero writes anywhere in ``hydromodpy/``, two lines in one test assigning it
``None`` that nothing read back, and two declarations calling it "used by the
workflow layer". A field a dataclass carries costs nothing at runtime, which is
exactly why a dead one survives.

A read counts only when its **receiver** is a context, the way
``test_step_payload_keys`` binds a receiver to ``PipelineState``: a parameter or
annotated local declared ``WorkflowContext`` (``| None`` and string forms
included), a local assigned from the constructor, or one of the two attributes
that hold a context by convention, ``x.ctx`` and ``x._ctx``. Names bind per
function and are inherited by nested functions, because the closures in this
package capture the context from their enclosing scope.

Binding the receiver is the whole gate, and the first version of it did not.
Counting any ``<anything>.<name>`` in a file that mentions ``WorkflowContext``
seems equivalent and is not: ``ctx.setup.time_grid`` then counts as a read of a
top-level member named ``time_grid``, and ``ctx.cfg.simulation.results`` as one
of ``results``. Measured on that first version, **ten of fifteen** plausible
dead member names came back green - ``workspace``, ``domain``, ``run_id``,
``time_grid``, ``solver``, ``results``, ``name``, ``store``, ``metadata``,
``path`` - every one of them riding on a namesake in a nested scope. The
forty-eight field names of ``SetupContext``, ``LoadedDataContext`` and
``ExecutionRegistry`` were all free passes. On this version, zero of the fifteen
pass.

The blind spot this gate cannot close, stated rather than discovered later: a
member consumed only by a reflexive read - ``for f in dataclasses.fields(ctx):
getattr(ctx, f.name)`` - is invisible here, and the gate would call it dead. The
idiom is already written twice in this package against a sibling scope. So it is
gated too, by :func:`test_no_module_reads_a_workflow_context_reflexively`: while
that one holds, a literal-name scan is the whole truth.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

import hydromodpy
from hydromodpy.core.state.run_state import WorkflowContext

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "hydromodpy"
DECLARATION = PACKAGE_ROOT / "core" / "state" / "run_state.py"

# The two attribute names that hold a context by convention: ``project._ctx``,
# the one a facade keeps, and ``trial_ctx.ctx``, the one a calibration trial
# carries. Neither is annotated at the access site, and both are real receivers.
HOLDER_ATTRIBUTES = frozenset({"_ctx", "ctx"})

# Reflexive readers. A member reached through one of these is not reached by
# name, so no name-based scan can see it.
REFLEXIVE_READERS = frozenset({"fields", "asdict", "astuple", "vars"})

# Floor. 1583 modules live under the package today; a scan that reads a fraction
# of that is anchored on the wrong tree, and every assertion below would pass for
# want of anything to read. The largest single sub-package is 328 modules, so
# this floor catches an anchor that collapsed onto one of them.
MIN_MODULES_SCANNED = 1200


def _annotation_mentions_context(node: ast.expr | None) -> bool:
    """True when an annotation names ``WorkflowContext``, in any spelling."""
    if node is None:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == "WorkflowContext":
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == "WorkflowContext":
            return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if "WorkflowContext" in sub.value:
                return True
    return False


class _ContextReads(ast.NodeVisitor):
    """Collect member reads whose receiver is bound to a ``WorkflowContext``."""

    def __init__(self, members: frozenset[str]) -> None:
        self._members = members
        self.reads: dict[str, int] = {}
        self.reflexive: list[int] = []
        self._receivers: list[set[str]] = [set()]

    def _bound_names(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        names = set(self._receivers[-1])
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            if _annotation_mentions_context(arg.annotation):
                names.add(arg.arg)
        for sub in ast.walk(node):
            if isinstance(sub, ast.AnnAssign) and _annotation_mentions_context(sub.annotation):
                if isinstance(sub.target, ast.Name):
                    names.add(sub.target.id)
            elif isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call):
                called = sub.value.func
                name = called.id if isinstance(called, ast.Name) else getattr(called, "attr", None)
                if name == "WorkflowContext":
                    names.update(t.id for t in sub.targets if isinstance(t, ast.Name))
        return names

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._receivers.append(self._bound_names(node))
        self.generic_visit(node)
        self._receivers.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def _is_receiver(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self._receivers[-1]
        if isinstance(node, ast.Attribute):
            return node.attr in HOLDER_ATTRIBUTES
        return False

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.ctx, ast.Load)
            and node.attr in self._members
            and self._is_receiver(node.value)
        ):
            self.reads.setdefault(node.attr, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        called = node.func
        name = called.id if isinstance(called, ast.Name) else getattr(called, "attr", None)
        if name == "getattr" and len(node.args) >= 2 and self._is_receiver(node.args[0]):
            # ``getattr(ctx, "effective_results_config", None)`` is a read, and
            # every reader that member has is spelled this way.
            requested = node.args[1]
            if isinstance(requested, ast.Constant) and requested.value in self._members:
                self.reads.setdefault(str(requested.value), node.lineno)
        if name in REFLEXIVE_READERS and node.args and self._is_receiver(node.args[0]):
            self.reflexive.append(node.lineno)
        self.generic_visit(node)


def _members() -> tuple[str, ...]:
    return tuple(field.name for field in dataclasses.fields(WorkflowContext))


def _scan() -> tuple[dict[str, list[str]], list[str], int]:
    """Return readers per member, reflexive reads, and modules scanned."""
    members = frozenset(_members())
    readers: dict[str, list[str]] = {name: [] for name in members}
    reflexive: list[str] = []
    scanned = 0
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path == DECLARATION or "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        scanned += 1
        # A module that never spells the name can neither import it nor annotate
        # a receiver with it, so it holds no reader this gate would count. The
        # skip is what keeps the most frequently run suite of the repository
        # from parsing fifteen hundred modules for twelve assertions.
        if "WorkflowContext" not in source:
            continue
        visitor = _ContextReads(members)
        visitor.visit(ast.parse(source, filename=str(path)))
        relative = str(path.relative_to(REPO_ROOT))
        for name, line in visitor.reads.items():
            readers[name].append(f"{relative}:{line}")
        reflexive.extend(f"{relative}:{line}" for line in visitor.reflexive)
    return readers, reflexive, scanned


@pytest.fixture(scope="module")
def scan() -> tuple[dict[str, list[str]], list[str], int]:
    return _scan()


def test_the_scan_reads_the_package_that_declares_the_context(scan) -> None:
    """The floor, and the identity of the tree being measured.

    Members come from the imported class, sources from a path built off this
    file. Nothing guarantees the two are the same checkout unless it is
    asserted: a second worktree, or a non-editable install, silently measures
    one tree's declaration against another tree's sources.
    """
    _, _, scanned = scan
    imported = pathlib.Path(hydromodpy.__file__).resolve().parent
    assert imported == PACKAGE_ROOT, (
        f"the imported package lives at {imported}, the scan reads {PACKAGE_ROOT}: "
        f"the declaration and the sources are not the same checkout."
    )
    assert scanned >= MIN_MODULES_SCANNED, (
        f"only {scanned} modules scanned under {PACKAGE_ROOT}, expected at least "
        f"{MIN_MODULES_SCANNED}: the scan is anchored on the wrong tree."
    )
    assert dataclasses.is_dataclass(WorkflowContext) and _members(), (
        "WorkflowContext carries no readable field declaration."
    )


def test_no_module_reads_a_workflow_context_reflexively(scan) -> None:
    """The premise of the member gate, gated in its turn.

    ``for f in dataclasses.fields(ctx): getattr(ctx, f.name)`` consumes every
    member without naming one. The member gate below cannot see it, and would
    call a member fed only that way dead. The idiom is already written twice in
    this package against ``ctx.loaded_data``; the day it is written against the
    context itself, the gate below stops being a measurement.
    """
    _, reflexive, _ = scan
    assert not reflexive, (
        "a WorkflowContext is read reflexively at "
        + ", ".join(reflexive)
        + ". The member gate reads literal names only, so a member consumed this way "
        "looks dead to it. Either name the members this code consumes, or replace the "
        "member gate with one that understands the reflexive read."
    )


@pytest.mark.parametrize("member", _members())
def test_every_workflow_context_member_has_a_reader(member: str, scan) -> None:
    readers, _, _ = scan
    if readers[member]:
        return
    pytest.fail(
        f"WorkflowContext.{member} is read by no receiver typed as a WorkflowContext. "
        f"A member nothing consumes is a promise the declaration keeps making to no one. "
        f"Two ways out, and the measurement tells them apart: if a reader exists but takes "
        f"the context through an untyped parameter, type that parameter - that is the phase, "
        f"not a workaround. If there is genuinely no reader, remove the member in the same "
        f"commit as this line."
    )
