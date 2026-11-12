"""What the path of a run reads and writes.

A backend lives in its folder and reads the frozen ``Model``. What a run
produces reaches its consumer through the run context, a step names the
payload keys it touches, and a solver never knows a calibration trial. No run
writes the state of the process, reads the environment for its bounds, opens a
global HTTP client, or calls a POSIX-only function. Every rule written as a
syntax-tree pattern is a row of ``RULES`` with a bad example it must flag. The
tables of process state and environment reads are checked against the tree in
both directions.
"""

from __future__ import annotations

import ast
import dataclasses
import functools
import pathlib
import re
import subprocess
import sys
from collections import Counter
from types import SimpleNamespace

import pytest
import yaml

import hydromodpy
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.io.filesystem import (
    PROJECT_TREE_DEPTH,
    WINDOWS_PATH_LIMIT,
    check_project_root,
)
from hydromodpy.core.state.run_state import RunState, WorkflowContext
from hydromodpy.solver.base.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.base.registry import solvers
from tests.unit.architecture import _scan
from tests.unit.architecture._scan import (
    PKG_ROOT,
    REPO_ROOT,
    FunctionNode,
    Rule,
    called_name,
    calls,
    member_read,
    offences,
    parse,
    rel,
    unwrap,
)

HERE = pathlib.Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# A flow backend lives in its folder and reads the frozen Model
# ---------------------------------------------------------------------------
#
# A backend can be added, replaced or removed alone: no file outside its home
# imports its package or carries its name in a string, and the reading and
# drawing layers name no backend at all. Under the solver folders a backend
# reads the frozen ``Model``, its options and its slot, never the setup, the
# configuration or the run context around it, and it writes nothing below an
# expression that ends in ``inputs``. A read through a local alias counts, and
# so does ``getattr``.

SOLVER = PKG_ROOT / "solver"
SOLVER_FOLDERS = ("modflow6", "modflow_nwt", "boussinesq", "modflow_common", "modflow_grid")

DECLARATION_FILES = frozenset(
    {
        "hydromodpy/solver/base/registry.py",
        "hydromodpy/config/config_migration.py",
        "hydromodpy/_lazy.py",
        "hydromodpy/project/old_paths.py",
        "hydromodpy/model/transport/transport_config.py",
        "hydromodpy/data/workspace/scaffold.py",
        "hydromodpy/solver/base/simulation_config.py",
    }
)
"""Where a backend name may sit outside its home, only in a module-level table or a default.

A constant of one of them names a TOML key or a dotted path, it never reads the
backend. A constant written in the body of a function is never a declaration."""

ZONES = (
    "hydromodpy/results/",
    "hydromodpy/calibration/",
    "hydromodpy/display/",
    "hydromodpy/project/compare.py",
)
OLD_SPELLINGS = ("modflownwt", "mf6", "nwt", "gr4j")
"""The spellings an earlier release gave a backend name: a sentence that carries one is stale."""

OUTPUT_EXEMPTIONS: dict[str, str] = {}
"""Sites of the four reading zones that may name a backend, by ``file:line``, with why. Empty."""


def _layout() -> dict:
    return yaml.safe_load((HERE / "solver_layout.yaml").read_text(encoding="utf-8"))


def _declared_backends() -> list[str]:
    families = dict(_layout().get("families", {}))
    return [
        name
        for name in solvers.names("flow", shipped_only=True)
        if (SOLVER / name).is_dir() or name in families
    ]


def _home(backend: str) -> tuple[pathlib.Path, ...]:
    families = dict(_layout().get("families", {})).get(backend, ())
    return (SOLVER / backend, *(SOLVER / family for family in families))


def named_backends(tree: ast.Module, names, *, declaration: bool = False) -> list[tuple[int, str]]:
    """``(line, name)`` for each string that holds a backend name as a whole token."""
    return [
        (s.line, name)
        for s in _scan.strings(tree)
        if s.value.strip() and not (declaration and s.in_table)
        for name in names
        if name in set(re.findall(r"[A-Za-z0-9_]+", s.value))
    ]


def imports_of(tree: ast.Module, prefix: str) -> list[tuple[int, str]]:
    return [
        (node.lineno, module)
        for node in ast.walk(tree)
        for module in _scan.imported_modules(node)
        if module == prefix or module.startswith(prefix + ".")
    ]


@pytest.mark.parametrize("backend", _declared_backends())
def test_no_file_outside_the_home_imports_or_names_the_backend(backend: str) -> None:
    home = _home(backend)
    sites = []
    for path in _scan.files():
        if any(path.is_relative_to(folder) for folder in home):
            continue
        tree, where = _scan.tree(path), rel(path)
        sites += [
            f"{where}:{line} imports {module}"
            for line, module in imports_of(tree, f"hydromodpy.solver.{backend}")
        ]
        sites += [
            f"{where}:{line} names {backend}"
            for line, _ in named_backends(tree, [backend], declaration=where in DECLARATION_FILES)
        ]
    assert sites == [], f"a file outside the home of {backend!r} reaches it:\n  " + "\n  ".join(
        sites
    )


def test_the_global_backend_is_declared_by_its_two_registry_lines_alone() -> None:
    """The one-cell backend names no module outside its folder but its registration."""
    named = set()
    for path in _scan.files():
        for statement in _scan.tree(path).body:
            if isinstance(statement, ast.Assign | ast.AnnAssign) and named_backends(
                ast.Module([statement], []), ["linear_reservoir"]
            ):
                targets = (
                    statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                )
                names = "/".join(t.id for t in targets if isinstance(t, ast.Name))
                named.add(f"{rel(path)}:{names or statement.lineno}")
    assert named == {
        "hydromodpy/solver/base/registry.py:_BUILTIN_PATHS",
        "hydromodpy/solver/base/registry.py:_BUILTIN_EXTRACTOR_PATHS",
    }, sorted(named)


def test_a_fallback_inside_a_function_of_a_declaration_file_is_flagged() -> None:
    """The module-table rule reads the statement a name sits under, not its file alone."""
    tree = parse("def _section(name):\n    return _SECTIONS.get(name, 'modflow6')\n")
    assert named_backends(tree, ["modflow6"], declaration=True) == [(2, "modflow6")]
    table = parse("_SECTIONS = {'a': 'modflow6'}\n")
    assert named_backends(table, ["modflow6"], declaration=True) == []


def _output_sites() -> list[tuple[str, str]]:
    names = (*(k.split("_", 1)[1] for k in solvers.names(shipped_only=True)), *OLD_SPELLINGS)
    sites = []
    for path in _scan.scoped_files(ZONES):
        tree, where = _scan.tree(path), rel(path)
        for line, module in imports_of(tree, "hydromodpy.solver"):
            if module.split(".")[2:3] and module.split(".")[2] in names:
                sites.append((f"{where}:{line}", f"imports {module}"))
        sites += [
            (f"{where}:{line}", f"names {name}") for line, name in named_backends(tree, names)
        ]
    return sites


def test_the_four_reading_zones_name_no_backend() -> None:
    """A run is read, scored, drawn and compared through what a backend declared it wrote."""
    sites = [f"{site} {what}" for site, what in _output_sites() if site not in OUTPUT_EXEMPTIONS]
    assert sites == [], "a reading zone carries a backend name:\n  " + "\n  ".join(sites)
    served = {site for site, _ in _output_sites()}
    assert sorted(set(OUTPUT_EXEMPTIONS) - served) == [], "an exemption row serves no site"


# --- A backend reads the Model, not the setup it is built from.

RUN_SETUP_MEMBERS = frozenset(
    {"workspace", "run_id", "mesh_bundle", "mesh_summary", "slot_request", "transport"}
)
"""What the runner hands a backend in its ``RunSlot``: forbidden to a flow and to a transport."""
SETUP_MEMBERS = (
    frozenset({"flow", "domain", "cell_mesh", "geographic", "time_grid"}) | RUN_SETUP_MEMBERS
)
CONFIG_MEMBERS = frozenset({"solver", "domain", "geographic", "flow"})
CONTEXT_MEMBERS = frozenset({"state", "store", "plan"})
SETUP_NAMES = frozenset({"setup", "setup_state"})
CONFIG_NAMES = frozenset({"cfg"})
CONTEXT_NAMES = frozenset({"ctx", "run_ctx", "context"})
FORBIDDEN_MODULES = ("hydromodpy.model.flow", "hydromodpy.model.transport.transport")
MODEL_EXEMPTIONS: dict[str, set[str]] = {}
"""Reads a solver file may keep, by file. Empty: the Model, the slot and the options serve them all."""


def _is_scope(node: ast.expr, scope: str, names: frozenset[str], aliases: set[str]) -> bool:
    """Whether ``node`` is the ``scope`` object: ``x.scope``, ``getattr(x, "scope")`` or a name."""
    node = unwrap(node)
    if isinstance(node, ast.Name):
        return node.id in names or node.id in aliases
    read = member_read(node)
    return read is not None and read[1] == scope


def _aliases(t: ast.AST, scope: str, names: frozenset[str]) -> set[str]:
    """Local names bound to the ``scope`` object anywhere in the module."""
    aliases: set[str] = set()
    for node in ast.walk(t):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign | ast.NamedExpr):
            targets, value = [node.target], node.value
        else:
            continue
        if value is not None and _is_scope(value, scope, names, set()):
            aliases.update(x.id for x in targets if isinstance(x, ast.Name))
    return aliases


def forbidden_reads(t: ast.Module, path: str = "") -> list[tuple[int, str]]:
    """Every ``(line, label)`` the module reads of the setup, the configuration or the context."""
    setup_aliases = _aliases(t, "setup", SETUP_NAMES)
    config_aliases = _aliases(t, "cfg", CONFIG_NAMES)
    parents = {child: node for node in ast.walk(t) for child in ast.iter_child_nodes(node)}
    found: list[tuple[int, str]] = []
    for node in ast.walk(t):
        read = member_read(node)
        if read is None:
            continue
        receiver, member = read
        if member in SETUP_MEMBERS and _is_scope(receiver, "setup", SETUP_NAMES, setup_aliases):
            found.append((node.lineno, f"setup.{member}"))
        elif member in CONFIG_MEMBERS and _is_scope(receiver, "cfg", CONFIG_NAMES, config_aliases):
            outer = parents.get(node)
            outer_read = None if outer is None else member_read(outer)
            options = (
                member == "solver" and outer_read is not None and outer_read[1] == "options_of"
            )
            found.append((node.lineno, "cfg.solver.options_of" if options else f"cfg.{member}"))
        elif (
            member in CONTEXT_MEMBERS
            and isinstance(receiver, ast.Name)
            and receiver.id in CONTEXT_NAMES
        ):
            found.append((node.lineno, f"ctx.{member}"))
    return found


def forbidden_imports(t: ast.Module, path: str = "") -> list[tuple[int, str]]:
    """Every ``(line, label)`` the module imports of a module the solver folders refuse."""

    def refused(module: str) -> bool:
        return any(module == one or module.startswith(one + ".") for one in FORBIDDEN_MODULES)

    found: list[tuple[int, str]] = []
    for node in ast.walk(t):
        if isinstance(node, ast.Import):
            hits = [a.name for a in node.names if refused(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module:
            joined = [f"{node.module}.{a.name}" for a in node.names]
            hits = joined if refused(node.module) else [j for j in joined if refused(j)]
        else:
            continue
        found += [(node.lineno, f"import {hit}") for hit in hits]
    return found


def _ends_in_inputs(node: ast.expr) -> bool:
    node = unwrap(node)
    return (isinstance(node, ast.Attribute) and node.attr == "inputs") or (
        isinstance(node, ast.Name) and node.id == "inputs"
    )


def _below_inputs(target: ast.expr) -> bool:
    node = target
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
        if _ends_in_inputs(node):
            return True
    return False


def writes_on_the_model(t: ast.Module, path: str = "") -> list[tuple[int, str]]:
    """Every ``(line, label)`` that writes an attribute or an item of a solver's ``Model``."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(t):
        if isinstance(node, ast.Assign | ast.Delete):
            targets = node.targets
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        elif (
            isinstance(node, ast.Call)
            and called_name(node) in {"setattr", "delattr"}
            and isinstance(node.func, ast.Name)
            and node.args
            and (_ends_in_inputs(node.args[0]) or _below_inputs(node.args[0]))
        ):
            found.append((node.lineno, f"{node.func.id} on inputs"))
            continue
        else:
            continue
        for target in targets:
            for item in target.elts if isinstance(target, ast.Tuple | ast.List) else [target]:
                if _below_inputs(item):
                    found.append((node.lineno, "write below inputs"))
    return found


def _model_findings(tree_: ast.Module, path: str) -> list[str]:
    allowed = MODEL_EXEMPTIONS.get(path, set())
    found = forbidden_reads(tree_) + forbidden_imports(tree_) + writes_on_the_model(tree_)
    return [f"{line} {label}" for line, label in found if label not in allowed]


READ_CASES = (
    ("direct", "def f(ctx):\n    return ctx.state.setup.flow\n", ["setup.flow", "ctx.state"]),
    ("getattr", 'def f(s):\n    return getattr(s.setup, "domain", None)\n', ["setup.domain"]),
    (
        "getattr on both",
        'def f(s):\n    return getattr(getattr(s, "setup", None), "cell_mesh", None)\n',
        ["setup.cell_mesh"],
    ),
    (
        "assigned alias",
        "def f(s):\n    here = s.setup\n    return here.geographic\n",
        ["setup.geographic"],
    ),
    (
        "walrus alias",
        "def f(s):\n    if (here := s.setup) is not None:\n        return here.time_grid\n",
        ["setup.time_grid"],
    ),
    ("setup parameter", "def f(setup):\n    return setup.flow\n", ["setup.flow"]),
    ("config", "def f(s):\n    return s.cfg.solver.sink_fill\n", ["cfg.solver"]),
    (
        "config getattr",
        'def f(s):\n    return getattr(s.cfg, "geographic", None)\n',
        ["cfg.geographic"],
    ),
    ("config flow", "def f(cfg):\n    return cfg.flow.restart_from\n", ["cfg.flow"]),
    ("config flow runtime", "def f(cfg):\n    return cfg.flow.runtime\n", ["cfg.flow"]),
    (
        "config solver options",
        "def f(self, s):\n    return s.cfg.solver.options_of(self.name)\n",
        ["cfg.solver.options_of"],
    ),
    (
        "allowed members",
        "def f(s, ctx):\n    return s.setup.model, s.cfg.simulation, ctx.run.id\n",
        [],
    ),
    ("workspace", "def f(s):\n    return s.setup.workspace\n", ["setup.workspace"]),
    ("run id", "def f(setup):\n    return setup.run_id\n", ["setup.run_id"]),
    (
        "mesh summary",
        'def f(s):\n    return getattr(s.setup, "mesh_summary", None)\n',
        ["setup.mesh_summary"],
    ),
    ("mesh bundle", "def f(setup):\n    return setup.mesh_bundle\n", ["setup.mesh_bundle"]),
    ("slot request", "def f(setup):\n    return setup.slot_request\n", ["setup.slot_request"]),
    ("the transport object", "def f(setup):\n    return setup.transport\n", ["setup.transport"]),
    ("context state", "def f(ctx):\n    return ctx.state.cfg\n", ["ctx.state"]),
    ("context store", 'def f(ctx):\n    return getattr(ctx, "store", None)\n', ["ctx.store"]),
    ("context plan", "def f(run_ctx):\n    return run_ctx.plan.runs\n", ["ctx.plan"]),
    (
        "setup through the context",
        "def f(ctx):\n    return ctx.state.setup.workspace\n",
        ["setup.workspace", "ctx.state"],
    ),
    ("the model", "def f(s):\n    return s.setup.model.geometry.domain\n", []),
)
IMPORT_CASES = (
    ("from module", "from hydromodpy.model.flow import Flow\n", 1),
    ("plain import", "import hydromodpy.model.flow\n", 1),
    ("from package", "from hydromodpy.model import flow\n", 1),
    ("the model module", "from hydromodpy.model.model import Model\n", 0),
    ("flow_config", "from hydromodpy.model.flow_config import FlowConfig\n", 0),
    ("the transport runtime", "from hydromodpy.model.transport.transport import Transport\n", 1),
    ("the transport config", "from hydromodpy.model.transport.transport_config import X\n", 0),
)
WRITE_CASES = (
    ("attribute", "self.inputs.time = 1\n", 1),
    ("item", 'self.inputs.lakes["a"] = 1\n', 1),
    ("nested item", 'model.inputs.lakes["a"]["b"] = 1\n', 1),
    ("augmented", "self.inputs.x += 1\n", 1),
    ("annotated", "self.inputs.x: int = 1\n", 1),
    ("tuple target", "a, self.inputs.x = 1, 2\n", 1),
    ("delete", "del self.inputs.x\n", 1),
    ("setattr", 'setattr(self.inputs, "x", 1)\n', 1),
    ("bare name", "inputs.x = 1\n", 1),
    ("binding the model", "self.inputs = model\n", 0),
    ("reading", "value = self.inputs.lakes['a']\n", 0),
    ("another attribute", "self.outputs.x = 1\n", 0),
)


@pytest.mark.parametrize(("case", "source", "expected"), READ_CASES, ids=[c[0] for c in READ_CASES])
def test_the_model_gate_sees_every_spelling_of_a_read(
    case: str, source: str, expected: list
) -> None:
    assert [label for _, label in forbidden_reads(parse(source))] == expected


@pytest.mark.parametrize(
    ("case", "source", "expected"), IMPORT_CASES, ids=[c[0] for c in IMPORT_CASES]
)
def test_the_model_gate_sees_every_import_of_the_flow(
    case: str, source: str, expected: int
) -> None:
    assert len(forbidden_imports(parse(source))) == expected


@pytest.mark.parametrize(
    ("case", "source", "expected"), WRITE_CASES, ids=[c[0] for c in WRITE_CASES]
)
def test_the_model_gate_sees_every_write_on_the_model(
    case: str, source: str, expected: int
) -> None:
    assert len(writes_on_the_model(parse(source))) == expected


# ---------------------------------------------------------------------------
# What a run produces reaches its consumer through the run context
# ---------------------------------------------------------------------------
#
# ``execution.solver_runs`` maps a run id to its ``SolverRun``. Only the runner
# and the modules named below touch it, and a consumer receives the product of
# its own run as ``RunContext.solver_run``. ``RunContext.state`` is a
# ``RunState`` with ``slots``: a read outside its members raises at run time,
# and the rule below fails the same read before any solver runs. A read through
# a local alias counts, with ``=`` and with ``:=``, and so does ``getattr``.

REGISTRY_MEMBERS = frozenset({"solver_runs"})
REGISTRY_READERS = frozenset(
    "hydromodpy/" + name
    for name in (
        "solver/base/runner.py",  # the owner: records what each run produced
        "solver/base/plan.py",  # RunContext.of hands a run's product over explicitly
        "workflow/steps/derive.py",  # releases the solver models before derived stacks allocate
        "workflow/steps/run_solver.py",  # a resume puts a SolverRun back without a model
        "workflow/steps/prepare_solver/dispatch.py",  # asks which dispatch the flow resolved to
        "calibration/metrics/solver_extract.py",  # finds the trial's single flow run
        "calibration/runners/sandbox.py",  # lists the scratch directories a trial clears
        "calibration/runners/kept_solves.py",  # a promotion records each run's SolverRun
    )
)
"""Every module allowed to name the registry. ``core/state/run_state.py`` only declares the field."""
CONTEXT_BUILDERS = frozenset({"hydromodpy/solver/base/plan.py", "hydromodpy/solver/base/runner.py"})
"""``RunContext.of`` builds every post-solver context. The runner builds one before the run has a product."""
VIEW_HOME = "hydromodpy/core/state/run_state.py"
VIEW_MEMBERS = frozenset(
    {f.name for f in dataclasses.fields(RunState)}
    | {n for n in vars(RunState) if not n.startswith("_")}
)


def _registry_reads(t: ast.AST) -> list[tuple[int, str]]:
    """Every ``(line, member)`` where a module names the execution registry, by name or string."""
    return [
        (n.lineno, n.attr if isinstance(n, ast.Attribute) else str(n.value))
        for n in ast.walk(t)
        if (isinstance(n, ast.Attribute) and n.attr in REGISTRY_MEMBERS)
        or (isinstance(n, ast.Constant) and n.value in REGISTRY_MEMBERS)
    ]


def _bound_names(t: ast.AST, class_name: str) -> set[str]:
    """Every local name a module binds to a class, an alias included."""
    names = {class_name}
    for node in ast.walk(t):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.update(a.asname or a.name for a in node.names if a.name == class_name)
    return names


def _builds(t: ast.AST, class_name: str, *, deferred: bool = False) -> list[int]:
    """Lines where a module calls a class constructor, whatever the spelling.

    A direct call, an aliased import and a dotted call all reach the
    constructor. With ``deferred``, a ``partial`` of it does too.
    """
    names, lines = _bound_names(t, class_name), []
    for node in ast.walk(t):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id in names) or (
            isinstance(func, ast.Attribute) and func.attr == class_name
        ):
            lines.append(node.lineno)
        elif deferred and called_name(node) in {"partial", "partialmethod"} and node.args:
            first = node.args[0]
            if (isinstance(first, ast.Name) and first.id in names) or (
                isinstance(first, ast.Attribute) and first.attr == class_name
            ):
                lines.append(node.lineno)
    return lines


def _context_parameters(node: FunctionNode) -> set[str]:
    """Names a function binds to a ``RunContext`` by annotation, string form included."""
    args = node.args
    return {
        a.arg
        for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]
        if (isinstance(a.annotation, ast.Name) and a.annotation.id == "RunContext")
        or (isinstance(a.annotation, ast.Constant) and a.annotation.value == "RunContext")
    }


def _binds_the_state(value: ast.expr, contexts: set[str]) -> bool:
    """Whether ``value`` reads ``state`` off a run context, as ``ctx.state`` or ``getattr``."""
    read = member_read(unwrap(value))
    return (
        read is not None
        and read[1] == "state"
        and isinstance(read[0], ast.Name)
        and read[0].id in contexts
    )


def _reads_the_view(inner: ast.expr, contexts: set[str], aliases: set[str]) -> bool:
    inner = unwrap(inner)
    return _binds_the_state(inner, contexts) or (
        isinstance(inner, ast.Name) and inner.id in aliases
    )


def view_reads(t: ast.AST) -> list[tuple[int, str]]:
    """Every ``(line, member)`` a module reads off a run-context state."""
    reads: list[tuple[int, str]] = []
    for fn in ast.walk(t):
        contexts = _context_parameters(fn) if isinstance(fn, FunctionNode) else set()
        if not contexts:
            continue
        aliases: set[str] = set()
        for child in ast.walk(fn):
            if isinstance(child, ast.Assign | ast.AnnAssign | ast.NamedExpr):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                if child.value is not None and _binds_the_state(child.value, contexts):
                    aliases.update(x.id for x in targets if isinstance(x, ast.Name))
        for child in ast.walk(fn):
            read = member_read(child)
            if read is not None and _reads_the_view(read[0], contexts, aliases):
                reads.append((child.lineno, read[1]))
    return reads


def _unless(allowed: frozenset[str], judge):
    return lambda t, path: [] if path in allowed else judge(t, path)


def test_every_allowed_registry_reader_still_reads_a_registry() -> None:
    """A module that no longer touches the registry leaves the list, or its next reader inherits it."""
    stale = [p for p in REGISTRY_READERS if not _registry_reads(_scan.tree(REPO_ROOT / p))]
    assert stale == [], f"these modules no longer read a registry: {sorted(stale)}"


def test_a_run_context_carries_what_its_run_produced() -> None:
    fields = {f.name for f in dataclasses.fields(RunContext)}
    assert {"solver_run", "upstream"} <= fields
    assert not fields & {"model", "output_dir", "dependency_models"}


def test_a_run_context_refuses_anything_but_the_view() -> None:
    run = ProcessRun(
        id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
    )
    plan = SimulationPlan(name="demo", description="demo", runs=(run,))
    with pytest.raises(TypeError, match="must be a RunState view"):
        RunContext(plan=plan, run=run, state=SimpleNamespace(setup=None))


def test_the_view_carries_no_catalog_handle() -> None:
    """The handle reaches an adapter through ``RunContext.store``, and only there."""
    assert "store" not in VIEW_MEMBERS


REGISTRY_SPELLINGS = (
    ("attribute", "runs = ctx.execution.solver_runs\n"),
    ("getattr string", 'runs = getattr(ctx.execution, "solver_runs", None)\n'),
    ("subscript through attribute", "d = state.execution.solver_runs[run.id].output_dir\n"),
    ("bare constant", 'KEY = "solver_runs"\n'),
)
BUILD_SPELLINGS = (
    ("direct call", "from x import RunContext\nctx = RunContext(plan=p, run=r, state=s)\n"),
    ("aliased import", "from x import RunContext as RC\nctx = RC(plan=p, run=r, state=s)\n"),
    ("dotted call", "import x\nctx = x.RunContext(plan=p, run=r, state=s)\n"),
    ("through partial", "from x import RunContext\nbuild = partial(RunContext, plan=p, run=r)\n"),
)
_C = "def f(ctx: RunContext) -> None:\n"
VIEW_SPELLINGS = (
    ("direct", _C + "    return ctx.state.raw_toml\n"),
    ("string annotation", 'def f(ctx: "RunContext") -> None:\n    return ctx.state.raw_toml\n'),
    ("assigned alias", _C + "    s = ctx.state\n    return s.raw_toml\n"),
    ("walrus alias", _C + "    if (s := ctx.state) is not None:\n        return s.raw_toml\n"),
    ("walrus read", _C + "    return (s := ctx.state).raw_toml\n"),
    ("annotated alias", _C + "    s: RunState = ctx.state\n    return s.raw_toml\n"),
    ("getattr on the context", _C + '    s = getattr(ctx, "state", None)\n    return s.raw_toml\n'),
    ("getattr on the view", _C + '    return getattr(ctx.state, "raw_toml", None)\n'),
    ("getattr on both", _C + '    return getattr(getattr(ctx, "state", None), "raw_toml", None)\n'),
    ("walrus inside getattr", _C + '    return getattr((c := ctx), "state", None).raw_toml\n'),
)


@pytest.mark.parametrize(
    ("case", "source"), REGISTRY_SPELLINGS, ids=[c[0] for c in REGISTRY_SPELLINGS]
)
def test_the_gate_sees_every_spelling_of_a_registry_read(case: str, source: str) -> None:
    assert _registry_reads(parse(source))


@pytest.mark.parametrize(("case", "source"), BUILD_SPELLINGS, ids=[c[0] for c in BUILD_SPELLINGS])
def test_the_gate_sees_every_spelling_of_a_hand_built_context(case: str, source: str) -> None:
    assert _builds(parse(source), "RunContext", deferred=True)


@pytest.mark.parametrize(("case", "source"), VIEW_SPELLINGS, ids=[c[0] for c in VIEW_SPELLINGS])
def test_the_gate_sees_every_spelling_of_a_state_read(case: str, source: str) -> None:
    assert [member for _, member in view_reads(parse(source))] == ["raw_toml"]


def test_the_gate_sees_an_aliased_import_of_the_view() -> None:
    source = "from hydromodpy.core.state.run_state import RunState as RS\n\n\ndef f():\n    return RS()\n"
    assert _builds(parse(source), "RunState") == [5]


# ---------------------------------------------------------------------------
# Every member of WorkflowContext is read through a receiver typed as one
# ---------------------------------------------------------------------------
#
# A field a dataclass carries costs nothing at run time, which is why a dead
# one survives. A read counts only when its receiver is a context: a parameter
# or annotated local declared ``WorkflowContext`` (``| None`` and string forms
# included), a local assigned from the constructor, or one of the two
# attributes that hold a context by convention, ``x.ctx`` and ``x._ctx``.
# Names bind per function and nested functions inherit them. Counting any
# ``<anything>.<name>`` instead would let ``ctx.setup.time_grid`` read as a
# member named ``time_grid``. The blind spot, stated: a member read only
# reflexively, ``getattr(ctx, f.name)``, looks dead, so that idiom is refused.

WORKFLOW_DECLARATION = "hydromodpy/core/state/run_state.py"
HOLDER_ATTRIBUTES = frozenset({"_ctx", "ctx"})
"""``project._ctx`` and ``trial_ctx.ctx``: neither is annotated where it is read."""
REFLEXIVE_READERS = frozenset({"fields", "asdict", "astuple", "vars"})
MIN_MODULES_SCANNED = 1200
"""A scan that reads a fraction of the tree is anchored on the wrong one."""


def _mentions_context(node: ast.expr | None) -> bool:
    if node is None:
        return False
    return any(
        (isinstance(s, ast.Name) and s.id == "WorkflowContext")
        or (isinstance(s, ast.Attribute) and s.attr == "WorkflowContext")
        or (
            isinstance(s, ast.Constant)
            and isinstance(s.value, str)
            and "WorkflowContext" in s.value
        )
        for s in ast.walk(node)
    )


class _ContextReads(ast.NodeVisitor):
    """Collect member reads whose receiver is bound to a ``WorkflowContext``."""

    def __init__(self, members: frozenset[str]) -> None:
        self._members = members
        self.reads: dict[str, int] = {}
        self.reflexive: list[int] = []
        self._receivers: list[set[str]] = [set()]

    def _bound(self, node: FunctionNode) -> set[str]:
        names = set(self._receivers[-1])
        args = node.args
        names |= {
            a.arg
            for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]
            if _mentions_context(a.annotation)
        }
        for sub in ast.walk(node):
            if isinstance(sub, ast.AnnAssign) and _mentions_context(sub.annotation):
                if isinstance(sub.target, ast.Name):
                    names.add(sub.target.id)
            elif isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call):
                if called_name(sub.value) == "WorkflowContext":
                    names.update(t.id for t in sub.targets if isinstance(t, ast.Name))
        return names

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._receivers.append(self._bound(node))
        self.generic_visit(node)
        self._receivers.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def _is_receiver(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self._receivers[-1]
        return isinstance(node, ast.Attribute) and node.attr in HOLDER_ATTRIBUTES

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.ctx, ast.Load)
            and node.attr in self._members
            and self._is_receiver(node.value)
        ):
            self.reads.setdefault(node.attr, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = called_name(node)
        if name == "getattr" and len(node.args) >= 2 and self._is_receiver(node.args[0]):
            requested = node.args[1]
            if isinstance(requested, ast.Constant) and requested.value in self._members:
                self.reads.setdefault(str(requested.value), node.lineno)
        if name in REFLEXIVE_READERS and node.args and self._is_receiver(node.args[0]):
            self.reflexive.append(node.lineno)
        self.generic_visit(node)


def _members() -> tuple[str, ...]:
    return tuple(f.name for f in dataclasses.fields(WorkflowContext))


@functools.cache
def _workflow_scan() -> tuple[dict[str, list[str]], list[str], int]:
    """Readers per member, reflexive reads, and the number of modules scanned."""
    members = frozenset(_members())
    readers: dict[str, list[str]] = {name: [] for name in members}
    reflexive: list[str] = []
    files_ = [p for p in _scan.files() if rel(p) != WORKFLOW_DECLARATION]
    for path in files_:
        # A module that never spells the name holds no reader this gate would count.
        if "WorkflowContext" not in path.read_text(encoding="utf-8"):
            continue
        visitor = _ContextReads(members)
        visitor.visit(_scan.tree(path))
        for name, line in visitor.reads.items():
            readers[name].append(f"{rel(path)}:{line}")
        reflexive += [f"{rel(path)}:{line}" for line in visitor.reflexive]
    return readers, reflexive, len(files_)


def test_the_workflow_scan_reads_the_package_that_declares_the_context() -> None:
    """The floor, and the identity of the tree measured: one checkout, not two."""
    imported = pathlib.Path(hydromodpy.__file__).resolve().parent
    assert imported == PKG_ROOT, f"imported {imported}, scanned {PKG_ROOT}"
    assert _workflow_scan()[2] >= MIN_MODULES_SCANNED
    assert dataclasses.is_dataclass(WorkflowContext) and _members()


def test_no_module_reads_a_workflow_context_reflexively() -> None:
    """The premise of the member gate: ``getattr(ctx, f.name)`` would make a member look dead."""
    reflexive = _workflow_scan()[1]
    assert not reflexive, f"a WorkflowContext is read reflexively at {reflexive}"


@pytest.mark.parametrize("member", _members())
def test_every_workflow_context_member_has_a_reader(member: str) -> None:
    """A member nothing consumes is a promise the declaration keeps making to no one.

    If a reader exists behind an untyped parameter, type that parameter. If there
    is none, remove the member in the same commit.
    """
    assert _workflow_scan()[0][member], f"WorkflowContext.{member} has no typed reader"


# ---------------------------------------------------------------------------
# A pipeline step declares the payload keys it reads and the ones it writes
# ---------------------------------------------------------------------------
#
# The gate derives both sets from the step's own source and requires the
# declaration to match exactly, in both directions. A step's keys are those its
# class body touches, plus those of any module-level function of ``workflow/``
# that takes a ``PipelineState`` and that the step reaches, transitively. A
# read counts when its receiver is a state: a parameter annotated
# ``PipelineState``, or a local bound to one (the successor of ``advance`` or
# ``with_data``, or a fresh ``PipelineState``).

WORKFLOW = PKG_ROOT / "workflow"
ADVANCE_FIELDS = frozenset({"step_index", "step_name", "elapsed_ms", "data"})
"""``advance`` carries the step position beside the payload: not payload keys."""


def _literal(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _annotation_name(annotation: ast.expr | None) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value.strip().strip("'\"")
    return _annotation_name(annotation.value) if isinstance(annotation, ast.Subscript) else None


def _state_parameters(node: FunctionNode) -> set[str]:
    args = node.args
    return {
        a.arg
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
        if _annotation_name(a.annotation) == "PipelineState"
    }


def _produces_a_state(value: ast.expr, states: set[str]) -> bool:
    value = unwrap(value)
    if isinstance(value, ast.Name):
        return value.id in states
    if not isinstance(value, ast.Call):
        return False
    if isinstance(value.func, ast.Name):
        return value.func.id == "PipelineState"
    # ``self.run(state)`` hands back the successor of a state.
    return isinstance(value.func, ast.Attribute) and value.func.attr in (
        "advance",
        "with_data",
        "run",
        "rebuild_state",
    )


def _receiver_is_a_state(value: ast.expr, states: set[str]) -> bool:
    value = unwrap(value)
    if isinstance(value, ast.Name):
        return value.id in states
    if isinstance(value, ast.Attribute) and value.attr == "data":
        return _receiver_is_a_state(value.value, states)
    return _produces_a_state(value, states)


def _scan_keys(scope: ast.AST, states: set[str]) -> tuple[set[str], set[str], set[str]]:
    """``(reads, writes, called_names)`` for one scope."""
    states = set(states)
    for _ in range(2):  # ``b = a.advance(...)`` then ``c = b`` needs ``b`` known first
        for child in ast.walk(scope):
            if isinstance(child, ast.Assign | ast.AnnAssign | ast.NamedExpr):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                if child.value is not None and _produces_a_state(child.value, states):
                    states.update(t.id for t in targets if isinstance(t, ast.Name))
    reads: set[str] = set()
    writes: set[str] = set()
    called: set[str] = set()
    for child in ast.walk(scope):
        if isinstance(child, ast.Subscript):
            key = _literal(child.slice)
            if key is not None and _receiver_is_a_state(child.value, states):
                reads.add(key)
        elif isinstance(child, ast.Call):
            name = called_name(child)
            if name:
                called.add(name)
            func = child.func
            if not isinstance(func, ast.Attribute) or not _receiver_is_a_state(func.value, states):
                continue
            if func.attr == "get" and child.args and _literal(child.args[0]) is not None:
                reads.add(_literal(child.args[0]))  # type: ignore[arg-type]
            elif func.attr in ("advance", "with_data"):
                writes.update(
                    k.arg for k in child.keywords if k.arg and k.arg not in ADVANCE_FIELDS
                )
    return reads, writes, called


class _Helper:
    """A module-level function of the workflow package that takes a state."""

    def __init__(self, node: FunctionNode) -> None:
        self.reads, self.writes, self.called = _scan_keys(node, _state_parameters(node))


@functools.cache
def _helpers() -> dict[str, _Helper]:
    return {
        node.name: _Helper(node)
        for path in _scan.files(WORKFLOW)
        for node in _scan.tree(path).body
        if isinstance(node, FunctionNode) and _state_parameters(node)
    }


@functools.cache
def _step_classes() -> dict[str, ast.ClassDef]:
    """Every class under ``workflow/steps`` whose ``run`` takes a state, so no step can leave."""
    return {
        node.name: node
        for path in _scan.files(WORKFLOW / "steps")
        for node in ast.walk(_scan.tree(path))
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(i, FunctionNode) and i.name == "run" and _state_parameters(i)
            for i in node.body
        )
    }


def _declared(cls: ast.ClassDef, attribute: str) -> tuple[str, ...] | None:
    for item in cls.body:
        target = item.target if isinstance(item, ast.AnnAssign) else None
        if target is None and isinstance(item, ast.Assign) and len(item.targets) == 1:
            target = item.targets[0]
        if isinstance(target, ast.Name) and target.id == attribute:
            if not isinstance(item.value, ast.Tuple):
                return None
            return tuple(k for k in map(_literal, item.value.elts) if k is not None)
    return None


def _measured(cls: ast.ClassDef, helpers: dict[str, _Helper]) -> tuple[set[str], set[str]]:
    states = {p for n in ast.walk(cls) if isinstance(n, FunctionNode) for p in _state_parameters(n)}
    reads, writes, pending = _scan_keys(cls, states)
    seen: set[str] = set()
    todo = list(pending)
    while todo:
        name = todo.pop()
        helper = helpers.get(name)
        if name in seen or helper is None:
            continue
        seen.add(name)
        reads |= helper.reads
        writes |= helper.writes
        todo.extend(helper.called)
    return reads, writes


def test_the_steps_package_holds_the_thirteen_known_steps() -> None:
    assert set(_step_classes()) == {
        "BuildGeographicStep", "BuildMeshStep", "DeriveStep", "DisplayStep", "ExportStep",
        "ExtractStep", "LoadDataStep", "PrepareSolverStep", "ResolveStep", "RunSolverStep",
        "SealStep", "SetupProcessStep", "ValidateStep",
    }  # fmt: skip


@pytest.mark.parametrize("step_name", sorted(_step_classes()))
def test_a_step_declares_the_payload_keys_it_touches(step_name: str) -> None:
    cls = _step_classes()[step_name]
    reads, writes = _measured(cls, _helpers())
    for label, measured in (("reads", reads), ("writes", writes)):
        declared = _declared(cls, label)
        assert declared is not None, f"{step_name} declares no {label!r} tuple of literals"
        assert sorted(declared) == sorted(measured), (
            f"{step_name}.{label} disagrees with its source: "
            f"undeclared {sorted(measured - set(declared))}, stale {sorted(set(declared) - measured)}"
        )


def test_every_step_but_the_first_reads_the_one_key_that_remains() -> None:
    """Twelve of thirteen steps read ``ctx`` and write it back: lower the number when one stops."""
    measured = {name: _measured(cls, _helpers()) for name, cls in _step_classes().items()}
    readers = {n for n, (r, _) in measured.items() if "ctx" in r}
    writers = {n for n, (_, w) in measured.items() if "ctx" in w}
    assert "ValidateStep" not in readers
    assert (len(readers), len(writers)) == (12, 12), (sorted(readers), sorted(writers))


_S = "def f(state: PipelineState):\n"
_ADV = '    out = state.advance(step_index=0, step_name="x")\n'
READ_SPELLINGS = (
    ("get on the parameter", _S + '    return state.get("k")\n'),
    ("string annotation", 'def f(state: "PipelineState"):\n    return state.get("k")\n'),
    ("subscript through data", _S + '    return state.data["k"]\n'),
    ("get through data", _S + '    return state.data.get("k")\n'),
    (
        "keyword-only parameter",
        'def f(*, prior_state: PipelineState):\n    return prior_state.get("k")\n',
    ),
    ("successor of advance", _S + _ADV + '    return out.get("k")\n'),
    ("successor of with_data", _S + '    out = state.with_data(a=1)\n    return out.get("k")\n'),
    ("alias of an alias", _S + _ADV + '    other = out\n    return other.get("k")\n'),
    (
        "walrus binding",
        _S + '    if (out := state.advance(step_index=0, step_name="x")) is not None:\n'
        '        return out.get("k")\n',
    ),
    ("freshly constructed state", _S + '    return PipelineState(run_id="r").get("k")\n'),
    (
        "chained on the call",
        _S + '    return state.advance(step_index=0, step_name="x").get("k")\n',
    ),
)
WRITE_SPELLINGS = (
    ("advance kwarg", _S + '    return state.advance(step_index=0, step_name="x", k=1)\n'),
    ("with_data kwarg", _S + "    return state.with_data(k=1)\n"),
    (
        "advance beside an explicit payload",
        _S + '    return state.advance(step_index=0, step_name="x", data=state.data, k=1)\n',
    ),
)
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
    ("non-literal key", "def f(state: PipelineState, key: str):\n    return state.get(key)\n"),
)


def _scan_function(source: str) -> tuple[set[str], set[str], set[str]]:
    node = parse(source).body[0]
    return _scan_keys(node, _state_parameters(node))  # type: ignore[arg-type]


@pytest.mark.parametrize(("case", "source"), READ_SPELLINGS, ids=[c[0] for c in READ_SPELLINGS])
def test_the_payload_gate_sees_every_spelling_of_a_read(case: str, source: str) -> None:
    assert _scan_function(source)[0] == {"k"}


@pytest.mark.parametrize(("case", "source"), WRITE_SPELLINGS, ids=[c[0] for c in WRITE_SPELLINGS])
def test_the_payload_gate_sees_every_spelling_of_a_write(case: str, source: str) -> None:
    assert _scan_function(source)[1] == {"k"}


@pytest.mark.parametrize(
    ("case", "source"), NON_PAYLOAD_SOURCES, ids=[c[0] for c in NON_PAYLOAD_SOURCES]
)
def test_the_payload_gate_counts_no_read_that_is_not_a_payload_read(case: str, source: str) -> None:
    assert _scan_function(source)[:2] == (set(), set())


def test_the_payload_gate_follows_a_helper_and_a_helper_of_a_helper() -> None:
    """The ``ValidateStep`` case: a key reached only through a module function."""
    module = parse(
        'def _inner(state: PipelineState):\n    return state.get("deep")\n\n\n'
        "def _outer(state: PipelineState):\n    return _inner(state)\n\n\n"
        'def _helper(state: PipelineState):\n    return state.get("through_helper")\n\n\n'
        "class SomeStep:\n    def run(self, state: PipelineState):\n"
        '        _helper(state)\n        _outer(state)\n        return state.get("direct")\n'
    )
    helpers = {n.name: _Helper(n) for n in module.body if isinstance(n, FunctionNode)}
    assert _measured(module.body[-1], helpers)[0] == {"direct", "through_helper", "deep"}  # type: ignore[arg-type]


def test_the_payload_gate_finds_a_step_that_declares_nothing() -> None:
    """Deleting the declaration is a failure, not an exemption."""
    cls = parse(
        'class S:\n    def run(self, state: PipelineState):\n        return state.get("k")\n'
    ).body[0]
    assert _declared(cls, "reads") is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Rules of the run path written as a syntax-tree pattern
# ---------------------------------------------------------------------------

# --- A solver never recognises a calibration trial, and no untyped dictionary tells it about one.

TRIAL_WORD = "trial"
GONE_NAME = "flow_runtime_overrides"


def trial_keys(t: ast.Module) -> list[tuple[int, str]]:
    """Every ``(line, constant)`` that is a key, a pattern or a name holding ``trial``.

    A sentence of a message may name a trial and a docstring is no constant, so a
    constant with white space is left alone.
    """
    return [
        (s.line, s.value)
        for s in _scan.strings(t)
        if TRIAL_WORD in s.value.lower() and not any(c.isspace() for c in s.value)
    ]


def names_of_the_gone_dictionary(t: ast.Module) -> list[int]:
    """Every line that names ``flow_runtime_overrides`` in code, strings included."""
    named = []
    for node in ast.walk(t):
        if isinstance(node, ast.Name):
            named.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute):
            named.append((node.lineno, node.attr))
        elif isinstance(node, ast.arg):
            named.append((node.lineno, node.arg))
        elif isinstance(node, ast.keyword):
            named.append((node.value.lineno, node.arg or ""))
        elif isinstance(node, FunctionNode | ast.ClassDef):
            named.append((node.lineno, node.name))
    named += [(s.line, s.value) for s in _scan.strings(t)]
    return [line for line, name in named if GONE_NAME in name]


# --- The basin of D is computed in one place, called from one place.

BASIN_CALLS: dict[str, dict[str, int]] = {
    "descent_basin": {"solver/modflow_common/catchment_basin.py": 1},
    "basin": {"catchment/drainage/descent.py": 1},
    "resolve_outlet": {
        "catchment/drainage/descent.py": 1,
        "solver/modflow_common/flow_directions.py": 1,
        "catchment/stream_network/geometry.py": 1,  # the stream criterion keeps its own flood on T
    },
}
"""Call sites of each name, by module relative to ``hydromodpy/``, and their count."""
BASIN_REMOVED = frozenset({"watershed_drainage_cell_mask", "_drainage_basin"})


def basin_calls(t: ast.Module) -> list[str]:
    """The names of ``BASIN_CALLS`` a module calls. ``x.basin("literal")`` is the soil budget."""
    found = []
    for node in ast.walk(t):
        if isinstance(node, ast.Call) and called_name(node) in BASIN_CALLS:
            literal = node.args and isinstance(node.args[0], ast.Constant)
            if not (
                called_name(node) == "basin" and literal and isinstance(node.args[0].value, str)
            ):  # type: ignore[union-attr]
                found.append(called_name(node))
    return found  # type: ignore[return-value]


def _old_basin_copies(t: ast.Module, path: str) -> list[str]:
    return [
        f"{getattr(n, 'lineno', '?')} {ident}"
        for n in ast.walk(t)
        if (ident := getattr(n, "name", None) or getattr(n, "id", None) or getattr(n, "attr", None))
        in BASIN_REMOVED
    ]


def test_the_basin_is_computed_and_called_from_one_place_each() -> None:
    sites: dict[str, Counter[str]] = {name: Counter() for name in BASIN_CALLS}
    for path in _scan.files():
        for name in basin_calls(_scan.tree(path)):
            sites[name][path.relative_to(PKG_ROOT).as_posix()] += 1
    for name, allowed in BASIN_CALLS.items():
        assert dict(sites[name]) == allowed, (
            f"{name}( is called from {dict(sites[name])}, not {allowed}"
        )


def test_the_basin_gate_skips_the_soil_budget_basin() -> None:
    assert basin_calls(parse("a.basin('annual')\nb.basin(x)\nresolve_outlet(y)\n")) == [
        "basin",
        "resolve_outlet",
    ]


# --- Every site that calls a flow builder passes the engine on.

BUILDERS = (
    "build_regional_flow_products",
    "extract_catchment_from_point",
    "build_solver_routing_context",
)
"""The two builders that turn a configuration into a terrain engine, and the frame both solvers call."""
BUILDER_CALL_FLOOR = 5


def _builder_calls(t: ast.Module) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(t)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in BUILDERS
    ]


def _drops_the_engine(t: ast.Module, path: str) -> list[str]:
    return [
        f"{c.lineno} calls {c.func.id} without engine_id"  # type: ignore[attr-defined]
        for c in _builder_calls(t)
        if not any(k.arg == "engine_id" for k in c.keywords)
    ]


def test_enough_builder_call_sites_are_scanned() -> None:
    sites = sum(len(_builder_calls(_scan.tree(p))) for p in _scan.files())
    assert sites >= BUILDER_CALL_FLOOR, f"found {sites} call sites: the scan read the wrong tree"


# --- The trial journal is written by the session, never on the path of a run.

JOURNAL = "hydromodpy.results.session.journal"
JOURNAL_FORBIDDEN = tuple(
    "hydromodpy/" + p
    for p in (
        "workflow/",
        "solver/",
        "results/storage/",
        "calibration/evaluation/",
        "calibration/runners/trial.py",
        "calibration/runners/lanes.py",
        "calibration/runners/pipeline_evaluator.py",
        "calibration/runners/worker_pool.py",
    )
)
"""A folder bans every module under it, a file bans that module alone."""


def imports_the_journal(t: ast.Module, module: str, *, is_package: bool = False) -> list[int]:
    """The line of every import of the journal in a module written as ``module``."""
    package = module if is_package else module.rpartition(".")[0]
    parent, _, leaf = JOURNAL.rpartition(".")
    found: list[int] = []
    for node in ast.walk(t):
        if isinstance(node, ast.Import):
            hit = any(a.name == JOURNAL or a.name.startswith(JOURNAL + ".") for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join([*anchor, base]) if base else ".".join(anchor)
            hit = (
                base == JOURNAL
                or base.startswith(JOURNAL + ".")
                or (base == parent and any(a.name == leaf for a in node.names))
            )
        else:
            continue
        if hit:
            found.append(node.lineno)
    return found


def _module_name(path: str) -> str:
    parts = pathlib.PurePosixPath(path).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _journal_offences(t: ast.Module, path: str) -> list[str]:
    lines = imports_the_journal(t, _module_name(path), is_package=path.endswith("__init__.py"))
    return [f"{line} imports the trial journal" for line in lines]


JOURNAL_CASES = (
    ("import hydromodpy.results.session.journal\n", "hydromodpy.workflow.runner", False, [1]),
    ("import hydromodpy.results.session.journal as j\n", "hydromodpy.workflow.runner", False, [1]),
    (
        "from hydromodpy.results.session.journal import read_trials\n",
        "hydromodpy.workflow.runner",
        False,
        [1],
    ),
    ("from hydromodpy.results.session import journal\n", "hydromodpy.workflow.runner", False, [1]),
    (
        "def f():\n    from hydromodpy.results.session.journal import T\n",
        "hydromodpy.solver.base.runner",
        False,
        [2],
    ),
    ("from ...results.session.journal import read_trials\n", "hydromodpy.workflow.a.b", False, [1]),
    ("from . import journal\n", "hydromodpy.results.session", True, [1]),
    ("from .journal import read_trials\n", "hydromodpy.results.session.view", False, [1]),
    ("from hydromodpy.results.session import descriptor\n", "hydromodpy.workflow.a", False, []),
    ("from hydromodpy.results.session.view import Session\n", "hydromodpy.workflow.a", False, []),
    ("import hydromodpy.results.session.journal_x\n", "hydromodpy.workflow.a", False, []),
)


@pytest.mark.parametrize(("source", "module", "is_package", "expected"), JOURNAL_CASES)
def test_the_journal_detector_reads_every_form_of_import(
    source, module, is_package, expected
) -> None:
    assert imports_the_journal(parse(source), module, is_package=is_package) == expected


def test_the_journal_scan_reads_the_modules_it_bans_and_the_session_still_imports_it() -> None:
    names = {rel(p) for p in _scan.scoped_files(JOURNAL_FORBIDDEN)}
    for required in ("workflow/runner.py", "solver/base/runner.py", "calibration/runners/trial.py"):
        assert f"hydromodpy/{required}" in names
    session = [
        p
        for p in _scan.files(PKG_ROOT / "results/session")
        if p.name != "journal.py" and _journal_offences(_scan.tree(p), rel(p))
    ]
    assert session, "no module of results/session imports the journal: the detector is blind"


# --- The trial pipeline is the only global the library keeps.

INSTALL_SITE = ("hydromodpy/calibration/runners/trial.py", "install_trial_pipeline")
RETIRED_FILES = (
    "hydromodpy/_bootstrap.py",
    "hydromodpy/core/runtime/bootstrap_hook.py",
    "hydromodpy/core/config_kit/root_config_protocol.py",
    "hydromodpy/core/toml_io/dynamic_examples_protocol.py",
    "hydromodpy/catchment/protocols.py",
    "hydromodpy/calibration/runners/contracts.py",
    "hydromodpy/core/contracts/solver_registry.py",
    "hydromodpy/results/run/rerun_contract.py",
)
RETIRED_NAMES = frozenset(
    {"ensure_bootstrapped", "bootstrap_hook", "get_root_config_provider", "get_root_config", "set_root_config"}
    | {f"get_{n}_provider" for n in (
        "trial_pipeline", "calibration", "data_source", "worker_pool", "display", "run", "fetch",
        "observation", "state", "signal", "overview", "worker",
    )}
    | {"set_trial_pipeline_provider"}
    | {f"register_{n}_provider" for n in (
        "calibrate", "pipeline", "signal", "state", "observation", "display", "fetch", "run",
        "overview", "worker",
    )}
)  # fmt: skip


def injection_sites(t: ast.Module) -> list[str]:
    """Public module-level functions that write a bare parameter into a module global."""
    found = []
    for node in t.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        params = {a.arg for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
        declared = {n for sub in ast.walk(node) if isinstance(sub, ast.Global) for n in sub.names}
        if any(
            isinstance(sub, ast.Assign)
            and isinstance(sub.value, ast.Name)
            and sub.value.id in params
            and any(isinstance(x, ast.Name) and x.id in declared for x in sub.targets)
            for sub in ast.walk(node)
        ):
            found.append(node.name)
    return found


def _injection_offences(t: ast.Module, path: str) -> list[str]:
    return [
        f"{n} writes a parameter into a global"
        for n in injection_sites(t)
        if (path, n) != INSTALL_SITE
    ]


def _install_callers(t: ast.Module, path: str) -> list[str]:
    if path.startswith("hydromodpy/project/"):
        return []
    return [
        f"{c.lineno} calls install_trial_pipeline outside project/"
        for c in calls(t, "install_trial_pipeline")
    ]


def _retired_names(t: ast.Module, path: str) -> list[str]:
    if path == rel(__file__):
        return []
    used = set()
    for node in ast.walk(t):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.ClassDef):
            used.add(node.name)
        elif isinstance(node, ast.alias):
            used.add(node.name)
    return [f"uses the retired name {n}" for n in sorted(used & RETIRED_NAMES)]


def test_the_one_injection_site_and_its_caller_exist() -> None:
    roots = ("hydromodpy", "hydromodpy_annex", "hydromodpy_server")
    found = {(rel(p), n) for p in _scan.scoped_files(roots) for n in injection_sites(_scan.tree(p))}
    assert found == {INSTALL_SITE}
    callers = [
        p for p in _scan.scoped_files(roots) if calls(_scan.tree(p), "install_trial_pipeline")
    ]
    assert callers, "install_trial_pipeline is called nowhere"


def test_retired_provider_files_do_not_exist() -> None:
    assert [f for f in RETIRED_FILES if (REPO_ROOT / f).exists()] == []


# --- A warning a document can raise goes through ``say``, so ``check`` collects it.

VALIDATORS = frozenset(
    {"field_validator", "model_validator", "BeforeValidator", "AfterValidator", "WrapValidator"}
)
SAY_FOLDERS = ("hydromodpy/config/", "hydromodpy/core/config_kit/")
REACHED_BY_CHECK = (
    "hydromodpy/calibration/parameter_resolution.py",
    "hydromodpy/core/time/window.py",
)
THE_SINK = "hydromodpy/core/config_kit/said.py"


def _say_in_scope(t: ast.Module, path: str) -> bool:
    if path in REACHED_BY_CHECK or path.startswith(SAY_FOLDERS):
        return True
    names = {n.id for n in ast.walk(t) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(t) if isinstance(n, ast.Attribute)
    }
    names |= {a.name for n in ast.walk(t) if isinstance(n, ast.ImportFrom) for a in n.names}
    return bool(names & VALIDATORS)


def _warns(t: ast.Module) -> list[int]:
    return [
        c.lineno
        for c in ast.walk(t)
        if isinstance(c, ast.Call)
        and (
            (
                isinstance(c.func, ast.Attribute)
                and c.func.attr == "warn"
                and ast.unparse(c.func.value) == "warnings"
            )
            or (isinstance(c.func, ast.Name) and c.func.id == "warn")
        )
    ]


def _unsaid_warnings(t: ast.Module, path: str) -> list[str]:
    if path == THE_SINK or not _say_in_scope(t, path):
        return []
    return [f"{line} calls warn: use core.config_kit.said.say" for line in _warns(t)]


def test_the_say_rule_reads_enough_modules_and_sees_a_validator() -> None:
    scoped = [
        p for p in _scan.files() if rel(p) != THE_SINK and _say_in_scope(_scan.tree(p), rel(p))
    ]
    assert len(scoped) > 20, "the scan found too few modules"
    tree_ = parse(
        "import warnings\nfrom pydantic import field_validator\nwarnings.warn('a')\nwarn('b')\n"
    )
    assert _say_in_scope(tree_, "hydromodpy/model/x.py") and _warns(tree_) == [3, 4]
    assert not _say_in_scope(
        parse("import warnings\nwarnings.warn('a')\n"), "hydromodpy/model/x.py"
    )
    assert all((REPO_ROOT / p).is_file() for p in REACHED_BY_CHECK)


# --- No global HTTP client, ad-hoc session or urllib: every download passes ``core/io/fetch.py``.

FETCH_PY = "hydromodpy/core/io/fetch.py"


def _http_offences(t: ast.Module, path: str) -> list[str]:
    if path == FETCH_PY:
        return []
    found = []
    for node in ast.walk(t):
        text = ast.unparse(node.func) if isinstance(node, ast.Call) else ""
        if isinstance(node, ast.Name | ast.Attribute | ast.alias):
            name = (
                getattr(node, "id", None)
                or getattr(node, "attr", None)
                or getattr(node, "name", "")
            )
            if name == "get_default_client":
                found.append(f"{node.lineno} names get_default_client")
        if text == "requests.Session":
            found.append(f"{node.lineno} calls requests.Session()")
        elif text in ("urllib.request.urlopen", "urllib.request.urlretrieve"):
            found.append(f"{node.lineno} calls {text}")
    return found


# --- The package runs on Windows: the source holds no call that only POSIX has.
#
# Seven rules, each with its table of allowed files and the reason of each.
# ``fcntl``, ``pwd`` and ``grp`` enter ``sys.modules`` through the standard
# library anyway, so the rules read the source and not the loaded modules.

Finding = tuple[int, str]
POSIX_ONLY_MODULES = frozenset({"fcntl", "msvcrt", "termios", "pwd", "grp"})
GUARDED_MODULES = frozenset({"resource"})
POSIX_ONLY_CALLS = frozenset(
    {("os", n) for n in ("setsid", "killpg", "fork", "getuid", "geteuid", "getpgid")}
    | {("signal", "SIGKILL"), ("signal", "SIGHUP")}
)
WINDOWS_LENGTHS = frozenset({240, 247, 248, 255, 259, 260})
SHELLS = frozenset({"bash", "sh", "cmd", "powershell", "pwsh"})
SUBPROCESS_CALLS = frozenset({"run", "Popen", "call", "check_call", "check_output"})
RUN_PATH_MODULES = (
    "hydromodpy",
    "hydromodpy.project.api",
    "hydromodpy.project.runner",
    "hydromodpy.project.dispatch.workflow",
    "hydromodpy.cli.commands.run",
)
SLURM_MODULES = frozenset({"slurm", "sacct", "slurm_script"})
WINDOWS_SCOPE = ("hydromodpy/", "hydromodpy_server/", "validation_cases/")
ALLOWED_HOST_NAME = {"hydromodpy/core/state/host.py": "the one reader of the host name"}
ALLOWED_HARD_LINKS = {
    "hydromodpy/core/io/filesystem.py": "link_or_copy falls back to a copy that never overwrites"
}
ALLOWED_LENGTH_LIMITS = {
    "hydromodpy/core/io/filesystem.py": "the one module that knows the Windows path limit"
}
ALLOWED_SHELLS = {
    "hydromodpy/project/launch/slurm.py": "the SLURM launcher submits its .sh scripts",
    "hydromodpy/project/launch/sacct.py": "the SLURM accounting reader of the launcher",
    "hydromodpy/project/launch/slurm_script.py": "writes the .sh scripts SLURM runs",
}


def _dotted(node: ast.AST) -> tuple[str, str] | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id, node.attr
    return None


def _ancestors(node: ast.AST, parents: dict[ast.AST, ast.AST]):
    """Each ancestor with the child of it on the way to ``node``."""
    while node in parents:
        yield parents[node], node
        node = parents[node]


def _parents(t: ast.Module) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(t) for child in ast.iter_child_nodes(parent)}


def posix_imports(t: ast.Module) -> list[Finding]:
    """Rule 1: POSIX-only imports, and ``resource`` outside ``try ... except ImportError``."""
    parents, found = _parents(t), []

    def catches(handler: ast.ExceptHandler) -> bool:
        caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        return any(
            isinstance(n, ast.Name) and n.id in {"ImportError", "ModuleNotFoundError"}
            for n in caught
        )

    for node in ast.walk(t):
        modules = (
            [a.name.split(".")[0] for a in node.names]
            if isinstance(node, ast.Import)
            else [node.module.split(".")[0]]
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
            else []
        )
        for module in modules:
            if module in POSIX_ONLY_MODULES:
                found.append((node.lineno, f"import {module}"))
            elif module in GUARDED_MODULES and not any(
                isinstance(p, ast.Try) and c in p.body and any(catches(h) for h in p.handlers)
                for p, c in _ancestors(node, parents)
            ):
                found.append((node.lineno, f"import {module} outside try/except ImportError"))
    return found


def unguarded_posix_calls(t: ast.Module) -> list[Finding]:
    """Rule 2: POSIX-only names outside an ``if`` on ``os.name`` or ``sys.platform``."""
    parents, found = _parents(t), []
    for node in ast.walk(t):
        if isinstance(node, ast.ImportFrom) and node.module in {"os", "signal"}:
            found += [
                (node.lineno, f"from {node.module} import {a.name}")
                for a in node.names
                if (node.module, a.name) in POSIX_ONLY_CALLS
            ]
        elif _dotted(node) in POSIX_ONLY_CALLS and not any(
            isinstance(p, ast.If | ast.IfExp)
            and c is not p.test
            and any(_dotted(n) in {("os", "name"), ("sys", "platform")} for n in ast.walk(p.test))
            for p, c in _ancestors(node, parents)
        ):
            found.append((node.lineno, ".".join(_dotted(node))))  # type: ignore[arg-type]
    return found


def _uses(t: ast.Module, module: str, name: str, method: str = "") -> list[Finding]:
    found: list[Finding] = []
    for node in ast.walk(t):
        if _dotted(node) == (module, name):
            found.append((node.lineno, f"{module}.{name}"))
        elif method and isinstance(node, ast.Attribute) and node.attr == method:
            found.append((node.lineno, f".{method}"))
        elif isinstance(node, ast.ImportFrom) and node.module == module:
            found += [
                (node.lineno, f"from {module} import {name}") for a in node.names if a.name == name
            ]
    return found


def host_name_reads(t: ast.Module) -> list[Finding]:
    """Rule 3: reads of ``socket.gethostname``."""
    return _uses(t, "socket", "gethostname")


def hard_links(t: ast.Module) -> list[Finding]:
    """Rule 4: ``os.link`` and ``.hardlink_to``."""
    return _uses(t, "os", "link", "hardlink_to")


def symlinks(t: ast.Module) -> list[Finding]:
    """Rule 4: ``os.symlink`` and ``.symlink_to``."""
    return _uses(t, "os", "symlink", "symlink_to")


def length_limits(t: ast.Module) -> list[Finding]:
    """Rule 5: a comparison of ``len(...)`` with a Windows path limit."""
    found = []
    for node in ast.walk(t):
        if not isinstance(node, ast.Compare):
            continue
        ops = [node.left, *node.comparators]
        holds_len = any(
            isinstance(c, ast.Call) and called_name(c) == "len" for o in ops for c in ast.walk(o)
        )
        if holds_len and any(
            isinstance(o, ast.Constant) and type(o.value) is int and o.value in WINDOWS_LENGTHS
            for o in ops
        ):
            found.append((node.lineno, ast.unparse(node)))
    return found


def shell_calls(t: ast.Module) -> list[Finding]:
    """Rule 6: ``shell=True``, a shell program, or a ``.sh`` literal in a subprocess call."""
    bound = {
        a.asname or a.name
        for n in ast.walk(t)
        if isinstance(n, ast.ImportFrom) and n.module == "subprocess"
        for a in n.names
        if a.name in SUBPROCESS_CALLS
    }
    found: list[Finding] = []
    for node in ast.walk(t):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted(node.func)
        is_call = (dotted and dotted[0] == "subprocess" and dotted[1] in SUBPROCESS_CALLS) or (
            isinstance(node.func, ast.Name) and node.func.id in bound
        )
        if not is_call:
            continue
        found += [
            (node.lineno, "shell=True")
            for k in node.keywords
            if k.arg == "shell"
            and not (isinstance(k.value, ast.Constant) and k.value.value is False)
        ]
        if node.args:
            first = node.args[0]
            first = (
                first.elts[0] if isinstance(first, ast.List | ast.Tuple) and first.elts else first
            )
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and first.value.strip()
            ):
                program = first.value.split()[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
                if program.removesuffix(".exe") in SHELLS:
                    found.append((node.lineno, f"runs {program}"))
        found += [
            (node.lineno, f"runs {s.value}")
            for s in ast.walk(node)
            if isinstance(s, ast.Constant) and isinstance(s.value, str) and s.value.endswith(".sh")
        ]
    return found


WINDOWS_DETECTORS = (
    ("posix_imports", posix_imports, {}, "import fcntl\n"),
    ("posix_calls", unguarded_posix_calls, {}, "import os\nos.setsid()\n"),
    ("host_name", host_name_reads, ALLOWED_HOST_NAME, "import socket\nsocket.gethostname()\n"),
    ("hard_links", hard_links, ALLOWED_HARD_LINKS, "import os\nos.link('a', 'b')\n"),
    ("symlinks", symlinks, {}, "import os\nos.symlink('a', 'b')\n"),
    ("length_limits", length_limits, ALLOWED_LENGTH_LIMITS, "x = len(p) > 259\n"),
    (
        "shells",
        shell_calls,
        ALLOWED_SHELLS,
        "import subprocess\nsubprocess.run('ls', shell=True)\n",
    ),
)


def _windows(detector, allowed: dict[str, str]):
    return lambda t, path: [] if path in allowed else [f"{n} {what}" for n, what in detector(t)]


WINDOWS_CASES = [
    (posix_imports, "import fcntl", 1),
    (posix_imports, "from pwd import getpwuid", 1),
    (posix_imports, "import grp, termios, msvcrt", 3),
    (posix_imports, "import resource", 1),
    (posix_imports, "try:\n    import resource\nexcept ImportError:\n    resource = None", 0),
    (posix_imports, "try:\n    import resource\nexcept OSError:\n    resource = None", 1),
    (posix_imports, "from importlib import resources", 0),
    (unguarded_posix_calls, "import os\nos.setsid()", 1),
    (unguarded_posix_calls, "import os, signal\nos.killpg(1, signal.SIGKILL)", 2),
    (unguarded_posix_calls, "from os import fork", 1),
    (unguarded_posix_calls, "import os\nif os.name == 'nt':\n    pass\nelse:\n    os.setsid()", 0),
    (unguarded_posix_calls, "import os, sys\nif sys.platform != 'win32':\n    os.getuid()", 0),
    (unguarded_posix_calls, "import os\nif os.getuid():\n    pass", 1),
    (unguarded_posix_calls, "import os\nx = os.geteuid() if os.name != 'nt' else 0", 0),
    (host_name_reads, "import socket\nsocket.gethostname()", 1),
    (host_name_reads, "from socket import gethostname", 1),
    (host_name_reads, "import socket\nsocket.getfqdn()", 0),
    (hard_links, "import os\nos.link('a', 'b')", 1),
    (hard_links, "from pathlib import Path\nPath('b').hardlink_to('a')", 1),
    (hard_links, "import os\nos.unlink('a')", 0),
    (symlinks, "import os\nos.symlink('a', 'b')", 1),
    (symlinks, "from pathlib import Path\nPath('b').symlink_to('a')", 1),
    (symlinks, "import os\nos.readlink('a')", 0),
    (length_limits, "x = len(p) > 259", 1),
    (length_limits, "x = 240 <= len(str(p))", 1),
    (length_limits, "x = len(p) + 1 > 260", 1),
    (length_limits, "x = len(p) > LIMIT", 0),
    (length_limits, "x = code == 259", 0),
    (length_limits, "x = len(p) > 100", 0),
    (shell_calls, "import subprocess\nsubprocess.run('ls', shell=True)", 1),
    (shell_calls, "import subprocess\nsubprocess.run(['bash', '-c', 'ls'])", 1),
    (shell_calls, "import subprocess\nsubprocess.Popen(['/bin/sh', 'x'])", 1),
    (shell_calls, "import subprocess\nsubprocess.run(['powershell.exe', '-c', 'x'])", 1),
    (shell_calls, "import subprocess\nsubprocess.check_call(['cmd', '/c', 'dir'])", 1),
    (shell_calls, "from subprocess import run\nrun(['sbatch', 'array.sh'])", 1),
    (shell_calls, "import subprocess\nsubprocess.run(['taskkill', '/F', '/T'], check=False)", 0),
    (shell_calls, "import subprocess\nsubprocess.run(['mf6'], shell=False)", 0),
]


@pytest.mark.parametrize(
    ("detector", "source", "count"),
    WINDOWS_CASES,
    ids=[f"{d.__name__}-{i}" for i, (d, _, _) in enumerate(WINDOWS_CASES)],
)
def test_each_windows_detector_flags_what_it_must(detector, source: str, count: int) -> None:
    assert len(detector(parse(source))) == count


def test_the_windows_scan_reads_the_package_and_each_allowed_file_exists() -> None:
    scanned = {rel(p) for p in _scan.scoped_files(WINDOWS_SCOPE)}
    assert {"hydromodpy/core/io/filesystem.py", "hydromodpy/core/state/host.py"} <= scanned
    assert any(p.startswith("validation_cases/") for p in scanned)
    for _, _, allowed, _ in WINDOWS_DETECTORS:
        assert [p for p in allowed if not (REPO_ROOT / p).is_file()] == []


@pytest.mark.allow_subprocess
def test_the_run_path_does_not_load_the_slurm_launcher() -> None:
    code = (
        "import sys, importlib\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        f"for name in {RUN_PATH_MODULES!r}:\n"
        "    importlib.import_module(name)\n"
        "print('\\n'.join(sorted(n for n in sys.modules if n.startswith('hydromodpy') and "
        f"n.rsplit('.', 1)[-1] in {sorted(SLURM_MODULES)!r})))\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=240, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.split() == []


@pytest.mark.parametrize(
    ("length", "refused"),
    [
        (WINDOWS_PATH_LIMIT - PROJECT_TREE_DEPTH, False),
        (WINDOWS_PATH_LIMIT - PROJECT_TREE_DEPTH + 1, True),
        (WINDOWS_PATH_LIMIT, True),
    ],
    ids=["at-the-limit", "one-past", "the-whole-limit"],
)
def test_a_project_root_past_the_windows_budget_is_refused(length: int, refused: bool) -> None:
    root = "/" + "r" * (length - 1) if sys.platform != "win32" else "C:\\" + "r" * (length - 3)
    if refused:
        with pytest.raises(ConfigError, match=f"is {length} characters long"):
            check_project_root(root, windows=True)
    else:
        check_project_root(root, windows=True)


# --- The table of every rule above.

SOLVER_SCOPE = tuple(f"hydromodpy/solver/{f}/" for f in SOLVER_FOLDERS)
PKG = ("hydromodpy/",)

RULES = (
    Rule(
        "a_backend_reads_the_model",
        SOLVER_SCOPE,
        _model_findings,
        READ_CASES[0][1],
        "hydromodpy/solver/modflow6/x.py",
    ),
    Rule(
        "the_registry_is_named_by_its_readers_only",
        PKG,
        _unless(REGISTRY_READERS, lambda t, p: [f"{n} names {m}" for n, m in _registry_reads(t)]),
        REGISTRY_SPELLINGS[0][1],
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "a_run_context_is_built_through_the_one_path",
        PKG,
        _unless(
            CONTEXT_BUILDERS,
            lambda t, p: [
                f"{n} builds a RunContext by hand" for n in _builds(t, "RunContext", deferred=True)
            ],
        ),
        BUILD_SPELLINGS[0][1],
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "a_run_context_state_is_read_through_its_view",
        PKG,
        lambda t, p: [f"{n} reads state.{m}" for n, m in view_reads(t) if m not in VIEW_MEMBERS],
        VIEW_SPELLINGS[0][1],
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "the_view_is_built_in_one_place",
        PKG,
        _unless(
            frozenset({VIEW_HOME}),
            lambda t, p: [f"{n} assembles a RunState" for n in _builds(t, "RunState")],
        ),
        "state = RunState(setup=None)\n",
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "a_solver_holds_no_trial_key",
        ("hydromodpy/solver/",),
        lambda t, p: [f"{n} holds {v!r}" for n, v in trial_keys(t)],
        'MARK = r"_trial\\d{6}$"\n',
        "hydromodpy/solver/x.py",
    ),
    Rule(
        "no_module_names_the_untyped_overrides",
        PKG,
        lambda t, p: [f"{n} names {GONE_NAME}" for n in names_of_the_gone_dictionary(t)],
        "x = setup.flow_runtime_overrides\n",
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "the_old_basin_copies_are_gone",
        PKG,
        _old_basin_copies,
        "def _drainage_basin():\n    pass\n",
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "a_flow_builder_call_passes_the_engine_on",
        PKG,
        _drops_the_engine,
        "build_regional_flow_products(cfg)\n",
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "the_run_path_never_imports_the_trial_journal",
        JOURNAL_FORBIDDEN,
        _journal_offences,
        "import hydromodpy.results.session.journal\n",
        "hydromodpy/workflow/x.py",
    ),
    Rule(
        "only_install_trial_pipeline_writes_a_parameter_into_a_global",
        ("hydromodpy/", "hydromodpy_annex/", "hydromodpy_server/"),
        _injection_offences,
        "_G = None\n\ndef register_something(value):\n    global _G\n    _G = value\n",
        "hydromodpy/fake.py",
    ),
    Rule(
        "install_trial_pipeline_is_called_from_project_only",
        ("hydromodpy/", "hydromodpy_annex/", "hydromodpy_server/"),
        _install_callers,
        "install_trial_pipeline(x)\n",
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "no_retired_provider_name_is_used",
        ("hydromodpy/", "tests/", "tools/"),
        _retired_names,
        "ensure_bootstrapped()\n",
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "a_warning_of_a_document_goes_through_say",
        PKG,
        _unsaid_warnings,
        "import warnings\nfrom pydantic import field_validator\nwarnings.warn('a')\n",
        "hydromodpy/model/x.py",
    ),
    Rule(
        "no_global_http_client_or_unfenced_session",
        PKG,
        _http_offences,
        "import requests\ns = requests.Session()\n",
        "hydromodpy/mesh/x.py",
    ),
    *(
        Rule(f"windows_{name}", WINDOWS_SCOPE, _windows(det, allowed), bad, "hydromodpy/mesh/x.py")
        for name, det, allowed, bad in WINDOWS_DETECTORS
    ),
)


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_the_tree_obeys(rule: Rule) -> None:
    assert offences(rule) == []


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_a_rule_flags_its_bad_example(rule: Rule) -> None:
    assert rule.judge(parse(rule.bad), rule.bad_at), "the rule flags nothing: the gate is empty"


TRIAL_KEY_CASES = (
    ("a folder pattern", 'MARK = r"_trial\\d{6}$"\n', 1),
    ("a key", 'flag = overrides.get("trial_owns_its_recharge")\n', 1),
    ("a name in __all__", '__all__ = ["PRIVATE_TRIAL_RECHARGE_KEY"]\n', 1),
    ("inside an f-string", 'name = f"{base}_trial{index:06d}"\n', 1),
    ("a sentence", 'message = "one trial of a parallel calibration"\n', 0),
    ("a docstring", 'def f():\n    """Build the model of a trial."""\n', 0),
    ("a numerical trial value", "bottom_trial = 1.0\n", 0),
)
GONE_CASES = (
    ("attribute", "x = setup.flow_runtime_overrides\n", 1),
    ("getattr", 'x = getattr(setup, "flow_runtime_overrides", None)\n', 1),
    ("parameter", "def f(flow_runtime_overrides=None):\n    pass\n", 1),
    ("keyword", "f(flow_runtime_overrides={})\n", 1),
    ("variable", "flow_runtime_overrides = {}\n", 1),
    ("a docstring", 'def f():\n    """It replaced flow_runtime_overrides."""\n', 0),
    ("the typed request", "x = setup.slot_request\n", 0),
)


@pytest.mark.parametrize(
    ("case", "source", "n"), TRIAL_KEY_CASES, ids=[c[0] for c in TRIAL_KEY_CASES]
)
def test_the_gate_sees_every_spelling_of_a_trial_key(case: str, source: str, n: int) -> None:
    assert len(trial_keys(parse(source))) == n


@pytest.mark.parametrize(("case", "source", "n"), GONE_CASES, ids=[c[0] for c in GONE_CASES])
def test_the_gate_sees_every_spelling_of_the_gone_dictionary(
    case: str, source: str, n: int
) -> None:
    assert len(names_of_the_gone_dictionary(parse(source))) == n


def test_the_model_exemption_table_is_empty() -> None:
    """The Model, the slot and the options serve every read the gate refused."""
    assert MODEL_EXEMPTIONS == {}


# ---------------------------------------------------------------------------
# Tables checked against the tree: process state and environment reads
# ---------------------------------------------------------------------------
#
# Two runs in two threads of one process share the environment, the working
# directory, the matplotlib backend and ``rcParams``, the handlers of the
# ``hydromodpy`` logger, the warning filters and the signal handlers. A run that
# writes one of them changes the other (rule 15). ``process_state.yaml`` carries
# one row per site that can write such a state and ``environment_reads.yaml`` one
# per ``os.environ`` site and per network client, each with its class. A site
# without a row and a row without a site both fail, so a table only shrinks.

STATE = yaml.safe_load((HERE / "process_state.yaml").read_text(encoding="utf-8"))
ENVIRONMENT = yaml.safe_load((HERE / "environment_reads.yaml").read_text(encoding="utf-8"))
STATE_CLASSES = ("import", "process", "cli", "trial_pipeline", "lock", "once", "transitional")
ENV_CLASSES = ("machine", "process", "cli", "diagnostic", "child", "transitional")
NEVER = ("matplotlib.use", "rcParams[...] =", "rcParams.update", "os.chdir", "sys.path.insert")
"""Kinds no row may carry: a render never switches the backend or leaves a style behind."""
NO_ENVIRONMENT_FILES = (
    "hydromodpy/core/io/http_client.py",
    "hydromodpy/core/io/pinned_download.py",
    "hydromodpy/core/runtime/bounds.py",
    "hydromodpy/project/environment.py",
    "hydromodpy/project/credentials.py",
    "hydromodpy/data/source/port.py",
)
FORBIDDEN_NAME = re.compile("CREDENTIAL|PASSWORD|TOKEN|NETRC|ALLOW|MAX_DOWNLOAD")
"""A host list, a credential or a ceiling never arrive through a variable."""
ENVIRONMENT_VERBS = (
    ("hydromodpy/project/api.py", ("run", "calibrate", "spinup", "replay", "export")),
    ("hydromodpy/project/facade.py", ("Project.__init__", "Project.launch")),
)


def _check_rows(rows: list[dict], classes: tuple[str, ...]) -> None:
    for row in rows:
        assert row["class"] in classes, f"{row} is not in {classes}"
        assert bool(row.get("lifted_by")) == (row["class"] == "transitional"), f"lifted_by of {row}"
        assert len(row["why"].split()) >= 4, f"the why of {row} is too short"


def test_every_process_state_site_has_its_row_and_every_row_its_site() -> None:
    carried = [(r["file"], r["site"], r["scope"]) for r in STATE["rows"]]
    found = [s for p in _scan.files() for s in _scan.globals_written(_scan.tree(p), rel(p))]
    unexpected, stale = (
        sorted(Counter(found) - Counter(carried)),
        sorted(Counter(carried) - Counter(found)),
    )
    assert not unexpected and not stale, (
        f"sites without a row: {unexpected}. Rows without a site: {stale}. A row leaves only with "
        "its code, and a new site needs its row, its class and its why."
    )


def test_the_process_state_rows_are_classed_and_never_switch_a_render() -> None:
    _check_rows(STATE["rows"], STATE_CLASSES)
    kinds = {row["site"] for row in STATE["rows"]}
    assert not kinds & set(NEVER), f"{sorted(kinds & set(NEVER))} write the state of every render"
    assert not [r for r in STATE["rows"] if r["class"] == "transitional"], (
        "a transitional row is left"
    )


def test_the_warning_filters_and_handlers_are_set_in_their_one_place() -> None:
    wrong = [
        row
        for row in STATE["rows"]
        if (
            row["site"] in {"catch_warnings", "simplefilter"}
            and row["class"] not in ("cli", "transitional")
        )
        or (row["site"] == "filterwarnings" and row["scope"] != "<module>")
    ]
    assert not wrong, f"{wrong}: a library filter is bounded and set once, at import"
    handlers = {r["file"] for r in STATE["rows"] if r["site"] in {"addHandler", "removeHandler"}}
    assert handlers <= {"hydromodpy/core/logging.py"}, handlers


def test_the_process_state_scan_flags_a_planted_site() -> None:
    planted = parse("import os\n\ndef run():\n    os.chdir('x')\n    global _G\n")
    assert [(k, s) for _, k, s in _scan.globals_written(planted, "x.py")] == [
        ("os.chdir", "run"),
        ("global", "run"),
    ]


def test_every_environment_site_has_its_row_and_every_row_its_site() -> None:
    carried = [(r["file"], r["kind"], r["variable"]) for r in ENVIRONMENT["rows"]]
    found = [(rel(p), k, v) for p in _scan.files() for k, v in _scan.env_reads(_scan.tree(p))]
    unexpected, stale = (
        sorted(Counter(found) - Counter(carried)),
        sorted(Counter(carried) - Counter(found)),
    )
    assert not unexpected and not stale, (
        f"sites without a row: {unexpected}. Rows without a site: {stale}. A row leaves only with "
        "the code that read it, and a new read needs its row, its class and its why."
    )


def test_the_environment_rows_are_classed_and_name_no_secret() -> None:
    _check_rows(ENVIRONMENT["rows"], ENV_CLASSES)
    named = Counter(
        r["variable"] for r in ENVIRONMENT["rows"] if FORBIDDEN_NAME.search(r["variable"])
    )
    assert not named, f"{dict(named)}: a host list, a credential or a ceiling never arrives so"
    wrong = {r["class"] for r in ENVIRONMENT["rows"] if r["kind"] == "write"} - {
        "process",
        "transitional",
    }
    assert not wrong, f"{wrong}: an environment write happens once, at import or at a start"


def test_the_files_that_carry_the_bounds_read_no_environment() -> None:
    offenders = {
        p: sites
        for p in NO_ENVIRONMENT_FILES
        if (REPO_ROOT / p).is_file() and (sites := _scan.env_reads(_scan.tree(REPO_ROOT / p)))
    }
    assert not offenders, (
        f"{offenders}: a caller builds the Bounds or the Environment and passes it"
    )


def test_the_environment_scan_reads_a_planted_site() -> None:
    planted = parse("import os\nA = 'X'\nos.environ[A] = '1'\nos.getenv('Y')\nf(os.environ)\n")
    assert sorted(_scan.env_reads(planted)) == [("pass", "<whole>"), ("read", "Y"), ("write", "X")]


def _environment_function(tree_: ast.Module, name: str) -> FunctionNode | None:
    """The last definition of a function, so the implementation wins over its overloads."""
    cls, _, method = name.rpartition(".")
    scope = next(
        (n.body for n in tree_.body if isinstance(n, ast.ClassDef) and n.name == cls), None
    )
    body = tree_.body if not cls else (scope or [])
    found = [n for n in body if isinstance(n, FunctionNode) and n.name == method]
    return found[-1] if found else None


def test_the_verbs_and_the_project_receive_the_environment_by_keyword() -> None:
    missing: list[str] = []
    for relative, names in ENVIRONMENT_VERBS:
        module = _scan.tree(REPO_ROOT / relative)
        for name in names:
            function = _environment_function(module, name)
            if function is None:
                missing.append(f"{relative}:{name} has no function to read")
                continue
            pairs = list(zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True))
            found = [(a, d) for a, d in pairs if a.arg == "environment"]
            if not found:
                missing.append(f"{relative}:{name} takes no keyword-only environment")
                continue
            arg, default = found[0]
            annotation = ast.unparse(arg.annotation).replace(" ", "") if arg.annotation else ""
            if (
                default is None
                or ast.unparse(default) != "None"
                or annotation != "Environment|None"
            ):
                missing.append(f"{relative}:{name}.environment is not `Environment | None = None`")
    assert not missing, (
        f"run, calibrate, spinup, export, Project.__init__ and Project.launch: {missing}"
    )


def _network_clients() -> Counter[tuple[str, str]]:
    """Every network client site per (file, kind): a second client in a file fails too."""
    kinds = {
        "requests.Session": "requests-session",
        "urllib.request.urlopen": "urllib",
        "urllib.request.urlretrieve": "urllib",
        "ftplib.FTP": "ftplib-ftp",
        "ftplib.FTP_TLS": "ftplib-ftps",
        "paramiko.Transport": "paramiko-sftp",
    }
    found: Counter[tuple[str, str]] = Counter()
    for path in _scan.files():
        for node in ast.walk(_scan.tree(path)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (kind := kinds.get(ast.unparse(node.func))) is not None:
                    found[rel(path), kind] += 1
    return found


def test_the_network_clients_are_the_ones_declared() -> None:
    found = _network_clients()
    carried = Counter((r["file"], r["client"]) for r in ENVIRONMENT["network"])
    unexpected, stale = sorted(found - carried), sorted(carried - found)
    assert not unexpected and not stale, (
        f"clients without a row {unexpected}, rows without a client {stale}"
    )
    assert list(carried) == [
        ("hydromodpy/core/io/fetch.py", "requests-session"),
        ("hydromodpy/project/deliver.py", "ftplib-ftp"),
        ("hydromodpy/project/deliver.py", "ftplib-ftps"),
        ("hydromodpy/project/deliver.py", "paramiko-sftp"),
    ]
    assert "trust_env = False" in (REPO_ROOT / FETCH_PY).read_text(encoding="utf-8")
