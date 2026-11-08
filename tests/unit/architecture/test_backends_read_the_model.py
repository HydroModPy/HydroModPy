"""A flow backend reads the frozen ``Model``, never the setup objects it is built from.

The ``prepare_solver`` step builds one ``Model`` per run from the setup flow,
the domain, the cell mesh, the delineation, the time grid and ``[solver]``.
A backend that read one of those again would see what the ``Model`` does not
say, and two backends could read two different things. So under the solver
folders this gate refuses a read of ``setup.flow``, ``setup.domain``,
``setup.cell_mesh``, ``setup.geographic``, ``setup.time_grid``, ``cfg.solver``,
``cfg.domain``, ``cfg.geographic`` and ``cfg.flow``, an import of
``hydromodpy.model.flow``, and any write of an attribute or an item below an
expression that ends in ``inputs``, the attribute a solver object keeps its
``Model`` in.

A read through a local alias counts, ``setup = ctx.state.setup`` then
``setup.flow``, and so does ``getattr``. An exemption names its file, the reads
it covers, why and the change that lifts it. An exemption that no longer serves
fails, so the list only shrinks.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SOLVER_FOLDERS = ("modflow6", "modflow_nwt", "boussinesq", "modflow_common", "modflow_grid")

SETUP_MEMBERS = frozenset({"flow", "domain", "cell_mesh", "geographic", "time_grid"})
CONFIG_MEMBERS = frozenset({"solver", "domain", "geographic", "flow"})
SETUP_NAMES = frozenset({"setup", "setup_state"})
CONFIG_NAMES = frozenset({"cfg"})
FORBIDDEN_MODULE = "hydromodpy.model.flow"

_TRANSPORT_WHY = (
    "A transport adapter still reads the domain of the setup until the transport "
    "port takes the Model."
)
EXEMPTIONS: dict[str, dict[str, object]] = {
    "hydromodpy/solver/modflow6/adapters/transport.py": {
        "reads": frozenset({"setup.domain"}),
        "why": _TRANSPORT_WHY,
        "lifted_by": "3.5",
    },
    "hydromodpy/solver/modflow6/adapters/prt.py": {
        "reads": frozenset({"setup.domain"}),
        "why": _TRANSPORT_WHY,
        "lifted_by": "3.5",
    },
    "hydromodpy/solver/modflow_nwt/adapters/transport_modpath.py": {
        "reads": frozenset({"setup.domain"}),
        "why": _TRANSPORT_WHY,
        "lifted_by": "3.5",
    },
    "hydromodpy/solver/modflow_nwt/adapters/transport_mt3dms.py": {
        "reads": frozenset({"setup.domain"}),
        "why": _TRANSPORT_WHY,
        "lifted_by": "3.5",
    },
    **{
        f"hydromodpy/solver/{folder}/adapters/flow.py": {
            "reads": frozenset({"cfg.solver.options_of"}),
            "why": (
                "A flow adapter reads its own settings, [solver.<name>], by "
                "cfg.solver.options_of(self.name) until the adapter contract hands them in."
            ),
            "lifted_by": "3.4",
        }
        for folder in ("modflow6", "modflow_nwt", "boussinesq")
    },
}


def _getattr_call(node: ast.AST) -> tuple[ast.expr, str] | None:
    """Return ``(receiver, name)`` when ``node`` is ``getattr(receiver, "name", ...)``."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    if node.func.id != "getattr" or len(node.args) < 2:
        return None
    name = node.args[1]
    if not isinstance(name, ast.Constant) or not isinstance(name.value, str):
        return None
    return _unwrap(node.args[0]), name.value


def _unwrap(node: ast.expr) -> ast.expr:
    return node.value if isinstance(node, ast.NamedExpr) else node


def _member_read(node: ast.AST) -> tuple[ast.expr, str] | None:
    """``(receiver, member)`` for ``receiver.member`` and ``getattr(receiver, "member")``."""
    if isinstance(node, ast.Attribute):
        return _unwrap(node.value), node.attr
    return _getattr_call(node)


def _is_scope(node: ast.expr, scope: str, names: frozenset[str], aliases: set[str]) -> bool:
    """Whether ``node`` is the ``scope`` object: ``x.scope``, ``getattr(x, "scope")`` or a name."""
    node = _unwrap(node)
    if isinstance(node, ast.Name):
        return node.id in names or node.id in aliases
    read = _member_read(node)
    return read is not None and read[1] == scope


def _aliases(tree: ast.AST, scope: str, names: frozenset[str]) -> set[str]:
    """Local names bound to the ``scope`` object anywhere in the module."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign | ast.NamedExpr):
            targets, value = [node.target], node.value
        else:
            continue
        if value is not None and _is_scope(value, scope, names, set()):
            aliases.update(target.id for target in targets if isinstance(target, ast.Name))
    return aliases


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def forbidden_reads(source: str) -> list[tuple[int, str]]:
    """Every ``(line, label)`` the source reads of the setup or the configuration."""
    tree = ast.parse(source)
    setup_aliases = _aliases(tree, "setup", SETUP_NAMES)
    config_aliases = _aliases(tree, "cfg", CONFIG_NAMES)
    parents = _parents(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        read = _member_read(node)
        if read is None:
            continue
        receiver, member = read
        if member in SETUP_MEMBERS and _is_scope(receiver, "setup", SETUP_NAMES, setup_aliases):
            found.append((node.lineno, f"setup.{member}"))
        elif member in CONFIG_MEMBERS and _is_scope(receiver, "cfg", CONFIG_NAMES, config_aliases):
            label = f"cfg.{member}"
            outer = parents.get(node)
            outer_read = None if outer is None else _member_read(outer)
            if member == "solver" and outer_read is not None and outer_read[1] == "options_of":
                label = "cfg.solver.options_of"
            found.append((node.lineno, label))
    return found


def _is_the_flow_module(module: str) -> bool:
    return module == FORBIDDEN_MODULE or module.startswith(FORBIDDEN_MODULE + ".")


def forbidden_imports(source: str) -> list[tuple[int, str]]:
    """Every ``(line, label)`` the source imports of ``hydromodpy.model.flow``."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            hits = [a.name for a in node.names if _is_the_flow_module(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module:
            hits = [
                f"{node.module}.{a.name}"
                for a in node.names
                if _is_the_flow_module(node.module) or f"{node.module}.{a.name}" == FORBIDDEN_MODULE
            ]
        else:
            continue
        found.extend((node.lineno, f"import {hit}") for hit in hits)
    return found


def _ends_in_inputs(node: ast.expr) -> bool:
    node = _unwrap(node)
    return (isinstance(node, ast.Attribute) and node.attr == "inputs") or (
        isinstance(node, ast.Name) and node.id == "inputs"
    )


def _below_inputs(target: ast.expr) -> bool:
    """Whether a write target sits below an expression that ends in ``inputs``."""
    node = target
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
        if _ends_in_inputs(node):
            return True
    return False


def writes_on_the_model(source: str) -> list[tuple[int, str]]:
    """Every ``(line, label)`` that writes an attribute or an item of a solver's ``Model``."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = node.targets
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"setattr", "delattr"}
            and node.args
            and (_ends_in_inputs(node.args[0]) or _below_inputs(node.args[0]))
        ):
            found.append((node.lineno, f"{node.func.id} on inputs"))
            continue
        else:
            continue
        for target in targets:
            elements = target.elts if isinstance(target, ast.Tuple | ast.List) else [target]
            found.extend(
                (node.lineno, "write below inputs") for item in elements if _below_inputs(item)
            )
    return found


def _solver_modules() -> list[pathlib.Path]:
    return sorted(
        path
        for folder in SOLVER_FOLDERS
        for path in (REPO_ROOT / "hydromodpy" / "solver" / folder).rglob("*.py")
    )


@pytest.fixture(scope="module")
def solver_findings() -> dict[str, list[tuple[int, str]]]:
    findings: dict[str, list[tuple[int, str]]] = {}
    for path in _solver_modules():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        findings[rel] = forbidden_reads(source) + forbidden_imports(source)
        findings[rel] += writes_on_the_model(source)
    return findings


def test_no_backend_reads_the_setup_objects_the_model_replaces(solver_findings) -> None:
    offenders = [
        f"{rel}:{line} {label}"
        for rel, found in solver_findings.items()
        for line, label in found
        if label not in EXEMPTIONS.get(rel, {}).get("reads", frozenset())
    ]

    assert not offenders, (
        "A backend reads the Model, ctx.state.setup.model, and nothing it is built from:\n"
        + "\n".join(sorted(offenders))
    )


@pytest.mark.parametrize("rel", sorted(EXEMPTIONS))
def test_every_exemption_still_serves(rel: str, solver_findings) -> None:
    exemption = EXEMPTIONS[rel]
    assert {"reads", "why", "lifted_by"} <= set(exemption)
    used = {label for _, label in solver_findings.get(rel, [])}
    unused = sorted(set(exemption["reads"]) - used)

    assert not unused, (
        f"{rel} no longer reads {', '.join(unused)}; remove it from the exemptions "
        f"(lifted by {exemption['lifted_by']})."
    )


READ_CASES = (
    ("direct", "def f(ctx):\n    return ctx.state.setup.flow\n", ["setup.flow"]),
    (
        "getattr",
        'def f(state):\n    return getattr(state.setup, "domain", None)\n',
        ["setup.domain"],
    ),
    (
        "getattr on both",
        'def f(s):\n    return getattr(getattr(s, "setup", None), "cell_mesh", None)\n',
        ["setup.cell_mesh"],
    ),
    (
        "assigned alias",
        "def f(state):\n    here = state.setup\n    return here.geographic\n",
        ["setup.geographic"],
    ),
    (
        "walrus alias",
        "def f(state):\n    if (here := state.setup) is not None:\n        return here.time_grid\n",
        ["setup.time_grid"],
    ),
    ("setup parameter", "def f(setup):\n    return setup.flow\n", ["setup.flow"]),
    ("config", "def f(state):\n    return state.cfg.solver.sink_fill\n", ["cfg.solver"]),
    (
        "config getattr",
        'def f(state):\n    return getattr(state.cfg, "geographic", None)\n',
        ["cfg.geographic"],
    ),
    ("config flow", "def f(cfg):\n    return cfg.flow.restart_from\n", ["cfg.flow"]),
    ("config flow runtime", "def f(cfg):\n    return cfg.flow.runtime\n", ["cfg.flow"]),
    (
        "config solver options",
        "def f(self, state):\n    return state.cfg.solver.options_of(self.name)\n",
        ["cfg.solver.options_of"],
    ),
    (
        "allowed members",
        "def f(state):\n    return state.setup.workspace, state.cfg.simulation\n",
        [],
    ),
    ("the model", "def f(state):\n    return state.setup.model.geometry.domain\n", []),
)


@pytest.mark.parametrize(
    ("case", "source", "expected"), READ_CASES, ids=[case for case, _, _ in READ_CASES]
)
def test_the_gate_sees_every_spelling_of_a_read(case: str, source: str, expected: list) -> None:
    del case
    assert [label for _, label in forbidden_reads(source)] == expected


IMPORT_CASES = (
    ("from module", "from hydromodpy.model.flow import Flow\n", 1),
    ("plain import", "import hydromodpy.model.flow\n", 1),
    ("from package", "from hydromodpy.model import flow\n", 1),
    ("the model module", "from hydromodpy.model.model import Model\n", 0),
    ("flow_config", "from hydromodpy.model.flow_config import FlowConfig\n", 0),
)


@pytest.mark.parametrize(
    ("case", "source", "expected"), IMPORT_CASES, ids=[case for case, _, _ in IMPORT_CASES]
)
def test_the_gate_sees_every_import_of_the_flow(case: str, source: str, expected: int) -> None:
    del case
    assert len(forbidden_imports(source)) == expected


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


@pytest.mark.parametrize(
    ("case", "source", "expected"), WRITE_CASES, ids=[case for case, _, _ in WRITE_CASES]
)
def test_the_gate_sees_every_write_on_the_model(case: str, source: str, expected: int) -> None:
    del case
    assert len(writes_on_the_model(source)) == expected
