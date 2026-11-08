"""A solver never recognises a calibration trial, and no untyped dictionary tells it about one.

A MODFLOW 6 build once walked its folder path up to a ``<base>_trialNNNNNN``
component, matched by a regular expression, to choose where the recharge
binaries go, and read two more trial keys from ``setup.flow_runtime_overrides``.
A trial now says what it asks for in a typed ``SlotRequest``, and the runner
hands the solver a ``RunSlot`` with the run name, the stop before the solve and
the shared forcing folder. Two AST checks hold it.

Under ``hydromodpy/solver``, no string constant that is a key, a pattern or a
name (a constant without white space) contains ``trial``. A sentence of a
message or a field description may name a trial, and a docstring is no
constant. In the whole package, no code names ``flow_runtime_overrides``: not
a variable, an attribute, a parameter, a keyword or a string.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "hydromodpy"
SOLVER_ROOT = PACKAGE_ROOT / "solver"

WORD = "trial"
GONE = "flow_runtime_overrides"


def _docstrings(tree: ast.AST) -> set[int]:
    """The ids of the string constants that stand alone as a statement."""
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }


def trial_keys(source: str) -> list[tuple[int, str]]:
    """Every ``(line, constant)`` that is a key, a pattern or a name holding ``trial``."""
    tree = ast.parse(source)
    docstrings = _docstrings(tree)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and WORD in node.value.lower()
        and not any(character.isspace() for character in node.value)
    ]


def names_of_the_gone_dictionary(source: str) -> list[int]:
    """Every line that names ``flow_runtime_overrides`` in code."""
    tree = ast.parse(source)
    docstrings = _docstrings(tree)
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            named = node.id
        elif isinstance(node, ast.Attribute):
            named = node.attr
        elif isinstance(node, ast.arg):
            named = node.arg
        elif isinstance(node, ast.keyword):
            named = node.arg or ""
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            named = node.name
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            named = "" if id(node) in docstrings else node.value
        else:
            continue
        if GONE in named:
            lines.append(node.lineno)
    return lines


def test_no_solver_module_holds_a_trial_key_or_pattern() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line} {value!r}"
        for path in sorted(SOLVER_ROOT.rglob("*.py"))
        for line, value in trial_keys(path.read_text(encoding="utf-8"))
    ]

    assert not offenders, (
        "A solver reads what a trial asks for in its RunSlot, never a trial name:\n"
        + "\n".join(offenders)
    )


def test_no_module_names_the_untyped_overrides() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}"
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        for line in names_of_the_gone_dictionary(path.read_text(encoding="utf-8"))
    ]

    assert not offenders, (
        "setup.flow_runtime_overrides is gone; a trial puts a SlotRequest on the setup:\n"
        + "\n".join(offenders)
    )


KEY_CASES = (
    ("a folder pattern", 'MARK = r"_trial\\d{6}$"\n', 1),
    ("a key", 'flag = overrides.get("trial_owns_its_recharge")\n', 1),
    ("a name in __all__", '__all__ = ["PRIVATE_TRIAL_RECHARGE_KEY"]\n', 1),
    ("inside an f-string", 'name = f"{base}_trial{index:06d}"\n', 1),
    ("a sentence", 'message = "one trial of a parallel calibration"\n', 0),
    ("a docstring", 'def f():\n    """Build the model of a trial."""\n', 0),
    ("a numerical trial value", "bottom_trial = 1.0\n", 0),
)


@pytest.mark.parametrize(
    ("case", "source", "expected"), KEY_CASES, ids=[case for case, _, _ in KEY_CASES]
)
def test_the_gate_sees_every_spelling_of_a_trial_key(case: str, source: str, expected: int) -> None:
    del case
    assert len(trial_keys(source)) == expected


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
    ("case", "source", "expected"), GONE_CASES, ids=[case for case, _, _ in GONE_CASES]
)
def test_the_gate_sees_every_spelling_of_the_gone_dictionary(
    case: str, source: str, expected: int
) -> None:
    del case
    assert len(names_of_the_gone_dictionary(source)) == expected
