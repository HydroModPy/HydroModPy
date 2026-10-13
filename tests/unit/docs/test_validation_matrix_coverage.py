"""Every validation file says, for each solver column, whether it runs or cannot run.

The "Case by solver" matrix of the Validation page has six solver columns. A
column is either declared (the file parametrizes the solver, its case names it,
or a solver marker does) or listed in the module-level ``NOT_APPLICABLE`` dict
of the test file with the reason the solver cannot run that test. A column that
is neither looks like a test nobody wrote, so this gate names it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.docs import tests_index
from tools.docs.tests_index import SOLVER_ORDER, column_of, solvers_of

ROOT = Path(__file__).resolve().parents[3]
MAX_REASON = 300


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    return tests_index.build(ROOT)["validation"]


def _declared(entry: dict) -> set[str]:
    return {column_of(s) for s in solvers_of(entry)} & set(SOLVER_ORDER)


def test_every_solver_column_is_declared_or_not_applicable(entries: list[dict]) -> None:
    flagged = []
    for e in entries:
        na = e["not_applicable"]
        covered = _declared(e) | (set(SOLVER_ORDER) if "*" in na else set(na))
        flagged += [(e["file"], c) for c in SOLVER_ORDER if c not in covered]
    assert not flagged, "columns neither declared nor n/a:\n" + "\n".join(
        f"{f}::{c}" for f, c in flagged
    )


def test_a_column_is_never_declared_and_not_applicable(entries: list[dict]) -> None:
    both = [(e["file"], c) for e in entries for c in e["not_applicable"] if c in _declared(e)]
    assert not both, f"declared and n/a at once: {both}"


def test_the_not_applicable_declarations_are_well_formed(entries: list[dict]) -> None:
    problems = []
    for e in entries:
        for key, reason in e["not_applicable"].items():
            if key != "*" and key not in SOLVER_ORDER:
                problems.append(f"{e['file']}: unknown column {key!r}")
            if not reason.strip():
                problems.append(f"{e['file']}: empty reason for {key}")
            if len(reason) >= MAX_REASON:
                problems.append(f"{e['file']}: reason for {key} has {len(reason)} characters")
        if "*" in e["not_applicable"] and _declared(e):
            problems.append(f"{e['file']}: '*' on a file that declares {sorted(_declared(e))}")
    assert not problems, "\n".join(problems)


def test_a_non_literal_declaration_is_refused() -> None:
    import ast

    tree = ast.parse("NOT_APPLICABLE = {'modflow_nwt': make()}")
    with pytest.raises(ValueError, match="literal"):
        tests_index.not_applicable(tree, "tests/validation/x/test_y.py")
    tree = ast.parse("NOT_APPLICABLE = {'modflow_nwt': 3}")
    with pytest.raises(ValueError, match="str to str"):
        tests_index.not_applicable(tree, "tests/validation/x/test_y.py")


def test_the_column_of_a_solver_is_its_longest_prefix() -> None:
    expected = {
        "modflow6": "modflow6",
        "modflow6_scaled_down": "modflow6",
        "modflow6_irregular_tri_xt3d_off": "modflow6_irregular_tri",
        "modflow6_voronoi": "modflow6_voronoi",
        "modflow_nwt": "modflow_nwt",
        "boussinesq_local": "boussinesq_local",
        "boussinesq": "boussinesq",
        "petsc": "boussinesq",
        "petsc_partition": "boussinesq",
        "mt3dms": "other",
        None: "other",
    }
    assert {k: column_of(k) for k in expected} == expected


# ---------------------------------------------------------------- labeling and rendering


@pytest.fixture(scope="module")
def V():
    """hmp_validation is a module of docs/source/_ext, not of a package."""
    import sys

    ext = ROOT / "docs" / "source" / "_ext"
    sys.path.insert(0, str(ext))
    import hmp_validation

    yield hmp_validation
    sys.path.remove(str(ext))


def test_a_record_without_solver_takes_the_column_of_its_function_markers(V) -> None:
    entry = {
        "functions": [
            {"name": "test_a", "markers": ["petsc", "validation"], "solvers": []},
            {"name": "test_b", "markers": ["mf6"], "solvers": []},
            {"name": "test_c", "markers": ["mf6", "petsc"], "solvers": []},
        ]
    }
    by_function = V.function_columns(entry)
    assert by_function == {"test_a": "boussinesq", "test_b": "modflow6"}
    nodeid = "tests/validation/x/test_y.py::test_a"
    assert V.record_column({"nodeid": nodeid, "solver": None}, by_function, "other") == "boussinesq"
    assert V.record_column({"nodeid": nodeid + "[p]"}, by_function, "other") == "boussinesq"
    assert V.record_column(
        {"nodeid": nodeid.replace("test_a", "test_c")}, by_function, "modflow6"
    ) == ("modflow6")
    assert V.record_column({"nodeid": nodeid, "solver": "modflow_nwt"}, by_function, "x") == (
        "modflow_nwt"
    )


def test_a_parametrized_value_is_recorded_not_its_pytest_id(tmp_path) -> None:
    import ast

    src = (
        "import pytest\n"
        "REF = 'modflow6'\n"
        "ALL = (REF, *('modflow6_scaled_up',), 'modflow6_k_only')\n"
        "@pytest.mark.parametrize('solver', ALL)\n"
        "def test_a(solver): pass\n"
        "@pytest.mark.parametrize(('solver', 'x'), [pytest.param('petsc', 1, id='petsc_strong')])\n"
        "def test_b(solver, x): pass\n"
    )
    funcs = {f["name"]: f for f in tests_index.function_info(ast.parse(src))}
    assert [s["id"] for s in funcs["test_a"]["solvers"]] == [
        "modflow6",
        "modflow6_scaled_up",
        "modflow6_k_only",
    ]
    assert [s["id"] for s in funcs["test_b"]["solvers"]] == ["petsc"]


def test_a_not_applicable_column_renders_its_reason(V) -> None:
    html = V.ValidationDirective.cell([], False, False, "no <b>NWT</b> here")
    assert "hmp-val-na" in html
    assert ">n/a<" in html
    assert 'title="no &lt;b&gt;NWT&lt;/b&gt; here"' in html
    assert "not measured" in V.ValidationDirective.cell([], True, False, None)


def test_a_star_covers_every_column_and_a_declared_column_wins(V) -> None:
    entry = {
        "file": "tests/validation/x/test_y.py",
        "solvers": ["modflow6"],
        "cases": [],
        "markers": [],
        "not_applicable": {"*": "closed form needs no solver"},
    }
    na = V.not_applicable_of(entry)
    assert set(na) == set(SOLVER_ORDER) - {"modflow6"}
