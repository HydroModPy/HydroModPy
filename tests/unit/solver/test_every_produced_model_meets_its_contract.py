"""Every class a solver adapter hands back satisfies the contract that types it.

``SolverRun.solver_model`` is typed ``SolverModel``, a three-member
protocol. The type is only worth its annotation if the eight classes that reach
that field really carry the three members, and if an eighth producer cannot
appear without this test noticing. A dataclass declares its members as
fields, so the scan reads the annotated names of the class body too.

The check is static rather than by instantiation: constructing a MODFLOW 6
model means a grid, a domain and a config, and the question here is about what
``__init__`` promises, not about what a built model contains.

Known bound, written here rather than left to be discovered: the member scan
walks a class's own body only. A producer that inherited one of the three from
a base class, or set it through ``setattr``, would fail this test while being
correct. None of the seven does, and the day one does, the fix is to widen the
scan, not to add an exception.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from hydromodpy.core.contracts.solver_model import SolverModel

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "hydromodpy"

# The classes that reach ``SolverRun.solver_model``, one per adapter.
PRODUCED_MODELS = {
    "Boussinesq": "solver/boussinesq/boussinesq.py",
    "Modflow6": "solver/modflow6/modflow6.py",
    "ModflowNwt": "solver/modflow_nwt/nwt/nwt_solver.py",
    "Modflow6Transport": "solver/modflow6/transport.py",
    "Modflow6Prt": "solver/modflow6/prt.py",
    "Mt3dms": "solver/modflow_nwt/mt3dms/mt3dms.py",
    "Modpath": "solver/modflow_nwt/modpath/modpath.py",
    "LinearReservoir": "solver/linear_reservoir/adapter.py",
}

CONTRACT_MEMBERS = frozenset(SolverModel.__annotations__)


def _self_assignments(class_node: ast.ClassDef) -> set[str]:
    """Every ``self.<name>`` this class assigns, and every field a dataclass declares."""
    assigned: set[str] = {
        node.target.id
        for node in class_node.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    for node in ast.walk(class_node):
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                assigned.add(target.attr)
    return assigned


def _class_node(relative_path: str, class_name: str) -> ast.ClassDef:
    tree = ast.parse((PACKAGE_ROOT / relative_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise AssertionError(f"{class_name} is not defined in {relative_path}")


@pytest.mark.parametrize(("class_name", "relative_path"), sorted(PRODUCED_MODELS.items()))
def test_a_produced_model_carries_the_three_members(class_name: str, relative_path: str) -> None:
    missing = sorted(CONTRACT_MEMBERS - _self_assignments(_class_node(relative_path, class_name)))
    assert not missing, f"{class_name} never assigns {missing}, so it cannot type solver_model"


def test_the_contract_stays_the_measured_one() -> None:
    """The three members are what the seven share, not a wish.

    Widening the protocol is a decision: it means proving the new member exists
    on all seven, and this test is where that proof is missing from.
    """
    assert CONTRACT_MEMBERS == {"model_name", "model_folder", "full_path"}


# Every module that builds a ``SolverRun``, and what it puts in ``solver_model``. The
# shared MODFLOW helper builds the run for both flow backends, which is why the
# sites cover seven classes. The MODFLOW 6 rerun hands back the ``Modflow6`` object
# of the run it took over, with its files moved and rewritten. ``replace`` of an
# existing run builds nothing new and is not a site.
RESULT_BUILDERS = {
    "solver/boussinesq/adapter.py": "Boussinesq",
    "solver/modflow_common/flow_run.py": "Modflow6 or ModflowNwt",
    "solver/modflow6/rerun.py": "Modflow6",
    "solver/modflow6/transport.py": "Modflow6Transport",
    "solver/modflow6/prt.py": "Modflow6Prt",
    "solver/modflow_nwt/mt3dms/mt3dms.py": "Mt3dms",
    "solver/modflow_nwt/modpath/modpath.py": "Modpath",
    "solver/linear_reservoir/adapter.py": "LinearReservoir",
    # A mesh run produces no model, and a run put back by a resume has lost its own.
    # The sites are listed with nothing beside them so that a producer without a
    # class is a statement and not an omission.
    "solver/base/runner.py": None,
    "workflow/steps/run_solver.py": None,
}


def _result_names(tree: ast.AST) -> set[str]:
    """Every local name this module binds to the run class, alias included."""
    names = {"SolverRun"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.update(
                alias.asname or alias.name for alias in node.names if alias.name == "SolverRun"
            )
    return names


def _result_builds(tree: ast.AST) -> list[int]:
    """Lines where this module builds a run, whatever the spelling.

    An aliased import and a dotted call reach the same constructor, and a call
    that gives its arguments by position sets the field without naming it.
    Matching only ``SolverRun(solver_model=...)`` would have seen none of the three.
    """
    names = _result_names(tree)
    builds: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        named = isinstance(func, ast.Name) and func.id in names
        dotted = isinstance(func, ast.Attribute) and func.attr == "SolverRun"
        if named or dotted:
            builds.append(node.lineno)
    return builds


def test_no_producer_escapes_the_list() -> None:
    """An eighth adapter cannot ship without declaring the class it hands back.

    The whole package is scanned, not only ``solver/``: a run built in
    ``workflow/`` or ``calibration/`` reaches the same field.
    """
    found = {
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in PACKAGE_ROOT.rglob("*.py")
        if _result_builds(ast.parse(path.read_text(encoding="utf-8")))
    }

    assert found == set(RESULT_BUILDERS), (
        "The set of modules building a SolverRun moved.\n"
        f"appeared: {sorted(found - set(RESULT_BUILDERS))}\n"
        f"vanished: {sorted(set(RESULT_BUILDERS) - found)}"
    )


OFFENDING_BUILDS = (
    ("keyword", "from x import SolverRun\nr = SolverRun(slot=s, solver_model=m)\n"),
    ("positional", "from x import SolverRun\nr = SolverRun(s, m)\n"),
    ("aliased import", "from x import SolverRun as SR\nr = SR(slot=s, solver_model=m)\n"),
    ("dotted call", "import x\nr = x.SolverRun(slot=s, solver_model=m)\n"),
)


@pytest.mark.parametrize(
    ("spelling", "source"), OFFENDING_BUILDS, ids=[s for s, _ in OFFENDING_BUILDS]
)
def test_the_gate_sees_every_spelling_of_a_run_build(spelling: str, source: str) -> None:
    """The gate's own angles, pinned, as F8a, F8c and F8d-1 all had to learn."""
    del spelling
    assert _result_builds(ast.parse(source))
