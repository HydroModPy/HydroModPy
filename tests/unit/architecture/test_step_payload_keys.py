"""A pipeline step declares the payload keys it reads and the ones it writes.

``PipelineState.data`` is one mapping shared by twelve steps. Nothing used to say
which member belonged to which step, and the pair that claimed to - ``tin`` and
``tout``, naming eleven frozen payload classes - said something else entirely:
those classes had zero instantiations, ten of their sixteen fields named no key
any step ever wrote, and ``ctx``, the key eleven of the twelve write back, was in
none of them. F8e replaced them with ``reads`` and ``writes``, and with this gate,
because a declaration nobody checks drifts into exactly that.

The gate derives both sets from the step's own source and requires the
declaration to match **exactly**, in both directions: an undeclared key fails,
and so does a declared key the step no longer touches. A step that starts reading
a member of the shared payload has to say so in the same commit.

Scope, stated rather than implied: a step's keys are the ones its class body
touches, plus the ones touched by any module-level function in
``hydromodpy/workflow/`` that takes a ``PipelineState`` and that the step reaches,
transitively. ``ValidateStep`` is the case that forces it - it reads
``run_workspace`` only through ``_run_workspace_for`` and the resolved-config
payload only through ``state_config_payload`` in ``internals/manifest.py``.

A read counts when its receiver is a state: a parameter annotated
``PipelineState``, or a local bound to one - the successor returned by
``advance`` / ``with_data``, or a freshly constructed ``PipelineState``. Reading
``cfg.get("x")`` off a config mapping is not a payload read, and a gate that
counted every ``.get`` would have said it was.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKFLOW_ROOT = REPO_ROOT / "hydromodpy" / "workflow"
STEPS_ROOT = WORKFLOW_ROOT / "steps"

# ``advance`` carries the step position beside the payload; those four are the
# state's own fields, not payload keys.
_ADVANCE_FIELDS = frozenset({"step_index", "step_name", "elapsed_ms", "data"})

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _literal(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _annotation_name(annotation: ast.expr | None) -> str | None:
    """The annotation spelled as a bare name, through a string form too."""
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value.strip().lstrip("'\"").rstrip("'\"")
    if isinstance(annotation, ast.Subscript):
        return _annotation_name(annotation.value)
    return None


def _state_parameters(node: FunctionNode) -> set[str]:
    """Names this function binds to a ``PipelineState`` by annotation."""
    args = node.args
    return {
        arg.arg
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)
        if _annotation_name(arg.annotation) == "PipelineState"
    }


def _unwrap(value: ast.expr) -> ast.expr:
    """Look through a walrus binding at the expression it carries."""
    return value.value if isinstance(value, ast.NamedExpr) else value


def _produces_a_state(value: ast.expr, states: set[str]) -> bool:
    """Whether ``value`` evaluates to a pipeline state."""
    value = _unwrap(value)
    if isinstance(value, ast.Name):
        return value.id in states
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id == "PipelineState"
    if isinstance(func, ast.Attribute):
        if func.attr in ("advance", "with_data"):
            return True
        if func.attr in ("run", "rebuild_state"):
            # ``self.run(state)`` hands back the successor of a state.
            return True
    return False


def _state_locals(scope: ast.AST, states: set[str]) -> set[str]:
    """Grow ``states`` with every local this scope binds to a state."""
    known = set(states)
    # Two passes: ``b = a.advance(...)`` then ``c = b`` needs ``b`` known first.
    for _ in range(2):
        for child in ast.walk(scope):
            if isinstance(child, ast.Assign):
                targets = child.targets
            elif isinstance(child, ast.AnnAssign | ast.NamedExpr):
                targets = [child.target]
            else:
                continue
            if child.value is not None and _produces_a_state(child.value, known):
                known.update(t.id for t in targets if isinstance(t, ast.Name))
    return known


def _receiver_is_a_state(value: ast.expr, states: set[str]) -> bool:
    value = _unwrap(value)
    if isinstance(value, ast.Name):
        return value.id in states
    # ``state.data.get("k")`` and ``state.data["k"]`` reach through ``.data``.
    if isinstance(value, ast.Attribute) and value.attr == "data":
        return _receiver_is_a_state(value.value, states)
    return _produces_a_state(value, states)


def _scan(scope: ast.AST, states: set[str]) -> tuple[set[str], set[str], set[str]]:
    """Return ``(reads, writes, called_names)`` for one scope."""
    states = _state_locals(scope, states)
    reads: set[str] = set()
    writes: set[str] = set()
    called: set[str] = set()
    for child in ast.walk(scope):
        if isinstance(child, ast.Subscript):
            key = _literal(child.slice)
            if key is not None and _receiver_is_a_state(child.value, states):
                reads.add(key)
            continue
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            called.add(func.id)
            continue
        if not isinstance(func, ast.Attribute):
            continue
        called.add(func.attr)
        if func.attr == "get" and child.args and _receiver_is_a_state(func.value, states):
            key = _literal(child.args[0])
            if key is not None:
                reads.add(key)
        elif func.attr in ("advance", "with_data") and _receiver_is_a_state(func.value, states):
            writes.update(
                kw.arg for kw in child.keywords if kw.arg and kw.arg not in _ADVANCE_FIELDS
            )
    return reads, writes, called


class _Helper:
    """A module-level function of the workflow package that takes a state."""

    def __init__(self, name: str, node: FunctionNode) -> None:
        self.name = name
        self.reads, self.writes, self.called = _scan(node, _state_parameters(node))


def _workflow_helpers() -> dict[str, _Helper]:
    helpers: dict[str, _Helper] = {}
    for path in sorted(WORKFLOW_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, FunctionNode) and _state_parameters(node):
                helpers[node.name] = _Helper(node.name, node)
    return helpers


def _closure(called: set[str], helpers: dict[str, _Helper]) -> tuple[set[str], set[str]]:
    """Keys reached through the helpers a scope calls, transitively."""
    reads: set[str] = set()
    writes: set[str] = set()
    pending = list(called)
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        helper = helpers.get(name)
        if helper is None:
            continue
        reads |= helper.reads
        writes |= helper.writes
        pending.extend(helper.called)
    return reads, writes


def _step_classes() -> dict[str, ast.ClassDef]:
    """Every class under ``workflow/steps`` whose ``run`` takes a state.

    Structural on purpose: a step cannot leave the gate by deleting its own
    declaration.
    """
    found: dict[str, ast.ClassDef] = {}
    for path in sorted(STEPS_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if (
                    isinstance(item, FunctionNode)
                    and item.name == "run"
                    and _state_parameters(item)
                ):
                    found[node.name] = node
                    break
    return found


def _declared(cls: ast.ClassDef, attribute: str) -> tuple[str, ...] | None:
    for item in cls.body:
        target = item.target if isinstance(item, ast.AnnAssign) else None
        if target is None and isinstance(item, ast.Assign) and len(item.targets) == 1:
            target = item.targets[0]
        if not isinstance(target, ast.Name) or target.id != attribute:
            continue
        value = item.value
        if not isinstance(value, ast.Tuple):
            return None
        keys = [_literal(element) for element in value.elts]
        return tuple(key for key in keys if key is not None)
    return None


def _measured(cls: ast.ClassDef, helpers: dict[str, _Helper]) -> tuple[set[str], set[str]]:
    reads, writes, called = _scan(cls, _state_parameters_of_methods(cls))
    through_reads, through_writes = _closure(called, helpers)
    return reads | through_reads, writes | through_writes


def _state_parameters_of_methods(cls: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(cls):
        if isinstance(node, FunctionNode):
            names |= _state_parameters(node)
    return names


STEP_CLASSES = _step_classes()
HELPERS = _workflow_helpers()


def test_the_steps_package_holds_the_twelve_known_steps() -> None:
    """The set the gate covers is the set the pipeline runs, plus display."""
    assert set(STEP_CLASSES) == {
        "BuildGeographicStep",
        "BuildMeshStep",
        "DeriveStep",
        "DisplayStep",
        "ExportStep",
        "ExtractStep",
        "LoadDataStep",
        "PrepareSolverStep",
        "ResolveStep",
        "RunSolverStep",
        "SetupProcessStep",
        "ValidateStep",
    }


@pytest.mark.parametrize("step_name", sorted(STEP_CLASSES))
def test_a_step_declares_the_payload_keys_it_touches(step_name: str) -> None:
    cls = STEP_CLASSES[step_name]
    reads, writes = _measured(cls, HELPERS)
    declared_reads = _declared(cls, "reads")
    declared_writes = _declared(cls, "writes")

    assert declared_reads is not None, f"{step_name} declares no 'reads' tuple of literals"
    assert declared_writes is not None, f"{step_name} declares no 'writes' tuple of literals"
    assert sorted(declared_reads) == sorted(reads), (
        f"{step_name}.reads disagrees with its source: "
        f"undeclared {sorted(reads - set(declared_reads))}, "
        f"stale {sorted(set(declared_reads) - reads)}"
    )
    assert sorted(declared_writes) == sorted(writes), (
        f"{step_name}.writes disagrees with its source: "
        f"undeclared {sorted(writes - set(declared_writes))}, "
        f"stale {sorted(set(declared_writes) - writes)}"
    )


def test_every_step_but_the_first_reads_the_one_key_f8_removes() -> None:
    """The measurement F8 exists for, kept as a fact instead of a paragraph.

    Eleven of the twelve steps read ``ctx`` and write it back: the shared payload
    is a handle to ``WorkflowContext`` plus a dozen scalars. When this assertion
    starts failing because a step stopped needing ``ctx``, F8 has made progress,
    and the number here is the one to lower.
    """
    readers = {name for name, cls in STEP_CLASSES.items() if "ctx" in _measured(cls, HELPERS)[0]}
    writers = {name for name, cls in STEP_CLASSES.items() if "ctx" in _measured(cls, HELPERS)[1]}
    assert "ValidateStep" not in readers
    assert len(readers) == 11, sorted(readers)
    assert len(writers) == 11, sorted(writers)


# ---------------------------------------------------------------------------
# The gate's own angles, pinned. D194: a static gate that has not been made to
# fail on each spelling it claims to see is not delivered.
# ---------------------------------------------------------------------------

READ_SPELLINGS = (
    ("get on the parameter", 'def f(state: PipelineState):\n    return state.get("k")\n'),
    (
        "string annotation",
        'def f(state: "PipelineState"):\n    return state.get("k")\n',
    ),
    (
        "subscript through data",
        'def f(state: PipelineState):\n    return state.data["k"]\n',
    ),
    (
        "get through data",
        'def f(state: PipelineState):\n    return state.data.get("k")\n',
    ),
    (
        "keyword-only parameter",
        'def f(*, prior_state: PipelineState):\n    return prior_state.get("k")\n',
    ),
    (
        "successor of advance",
        "def f(state: PipelineState):\n"
        '    out = state.advance(step_index=0, step_name="x")\n'
        '    return out.get("k")\n',
    ),
    (
        "successor of with_data",
        'def f(state: PipelineState):\n    out = state.with_data(a=1)\n    return out.get("k")\n',
    ),
    (
        "alias of an alias",
        "def f(state: PipelineState):\n"
        '    out = state.advance(step_index=0, step_name="x")\n'
        "    other = out\n"
        '    return other.get("k")\n',
    ),
    (
        "walrus binding",
        "def f(state: PipelineState):\n"
        '    if (out := state.advance(step_index=0, step_name="x")) is not None:\n'
        '        return out.get("k")\n',
    ),
    (
        "freshly constructed state",
        'def f(state: PipelineState):\n    return PipelineState(run_id="r").get("k")\n',
    ),
    (
        "chained on the call",
        "def f(state: PipelineState):\n"
        '    return state.advance(step_index=0, step_name="x").get("k")\n',
    ),
)


@pytest.mark.parametrize("spelling,source", READ_SPELLINGS, ids=[s for s, _ in READ_SPELLINGS])
def test_the_gate_sees_every_spelling_of_a_read(spelling: str, source: str) -> None:
    del spelling
    node = ast.parse(source).body[0]
    reads, _, _ = _scan(node, _state_parameters(node))
    assert reads == {"k"}


WRITE_SPELLINGS = (
    (
        "advance kwarg",
        'def f(state: PipelineState):\n    return state.advance(step_index=0, step_name="x", k=1)\n',
    ),
    (
        "with_data kwarg",
        "def f(state: PipelineState):\n    return state.with_data(k=1)\n",
    ),
    (
        "advance beside an explicit payload",
        "def f(state: PipelineState):\n"
        '    return state.advance(step_index=0, step_name="x", data=state.data, k=1)\n',
    ),
)


@pytest.mark.parametrize("spelling,source", WRITE_SPELLINGS, ids=[s for s, _ in WRITE_SPELLINGS])
def test_the_gate_sees_every_spelling_of_a_write(spelling: str, source: str) -> None:
    del spelling
    node = ast.parse(source).body[0]
    _, writes, _ = _scan(node, _state_parameters(node))
    assert writes == {"k"}


NON_PAYLOAD_SOURCES = (
    (
        "get on a config mapping",
        'def f(state: PipelineState, cfg: dict):\n    return cfg.get("k")\n',
    ),
    (
        "subscript on an unrelated mapping",
        'def f(state: PipelineState, cfg: dict):\n    return cfg["k"]\n',
    ),
    (
        "subscript on an unrelated .data",
        'def f(state: PipelineState, rec: object):\n    return rec.data["k"]\n',
    ),
    (
        "advance on an unrelated object",
        "def f(state: PipelineState, bar: object):\n    return bar.advance(k=1)\n",
    ),
    (
        "non-literal key",
        "def f(state: PipelineState, key: str):\n    return state.get(key)\n",
    ),
)


@pytest.mark.parametrize(
    "spelling,source", NON_PAYLOAD_SOURCES, ids=[s for s, _ in NON_PAYLOAD_SOURCES]
)
def test_the_gate_counts_no_read_that_is_not_a_payload_read(spelling: str, source: str) -> None:
    del spelling
    node = ast.parse(source).body[0]
    reads, writes, _ = _scan(node, _state_parameters(node))
    assert reads == set()
    assert writes == set()


def test_the_gate_follows_a_helper_the_step_calls() -> None:
    """The ``ValidateStep`` case: a key reached only through a module function."""
    module = ast.parse(
        "def _helper(state: PipelineState):\n"
        '    return state.get("through_helper")\n'
        "\n\n"
        "class SomeStep:\n"
        "    def run(self, state: PipelineState):\n"
        "        _helper(state)\n"
        '        return state.get("direct")\n'
    )
    helper_node = module.body[0]
    assert isinstance(helper_node, FunctionNode)
    helpers = {"_helper": _Helper("_helper", helper_node)}
    cls = module.body[1]
    assert isinstance(cls, ast.ClassDef)
    reads, _ = _measured(cls, helpers)
    assert reads == {"direct", "through_helper"}


def test_the_gate_follows_a_helper_of_a_helper() -> None:
    module = ast.parse(
        'def _inner(state: PipelineState):\n    return state.get("deep")\n'
        "\n\n"
        "def _outer(state: PipelineState):\n    return _inner(state)\n"
        "\n\n"
        "class SomeStep:\n"
        "    def run(self, state: PipelineState):\n"
        "        return _outer(state)\n"
    )
    helpers = {
        node.name: _Helper(node.name, node)
        for node in module.body
        if isinstance(node, FunctionNode)
    }
    cls = module.body[2]
    assert isinstance(cls, ast.ClassDef)
    assert _measured(cls, helpers)[0] == {"deep"}


def test_the_gate_finds_a_step_that_declares_nothing() -> None:
    """Deleting the declaration is a failure, not an exemption."""
    cls = ast.parse(
        'class SomeStep:\n    def run(self, state: PipelineState):\n        return state.get("k")\n'
    ).body[0]
    assert isinstance(cls, ast.ClassDef)
    assert _declared(cls, "reads") is None
