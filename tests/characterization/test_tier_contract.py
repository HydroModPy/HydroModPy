"""The shape of the tier itself.

The characterization net was built around five strict xfails, one per claim the
code makes and does not honour. The count is part of the contract: adding one
without saying so hides a new defect among the known ones, and losing one
silently drops a claim nobody is watching any more. Phases F1, F7 and F8 each
turn some of them green; when they do, the two declarations below are what must
be edited, deliberately. A repaired claim does not disappear from this file: it
moves to ``REPAIRED_STRICT_XFAILS``, where it keeps guarding against anyone
marking it xfail again.
"""

from __future__ import annotations

import ast
from pathlib import Path

TIER_DIR = Path(__file__).resolve().parent

EXPECTED_STRICT_XFAILS: dict[str, str] = {
    "test_every_step_of_a_run_declares_what_it_left_on_disk": "F7",
    "test_the_runtime_state_survives_a_process_boundary": "F8",
}

# Claims the code now honours. They stay named here so that re-marking one
# xfail is a failure rather than a quiet regression.
REPAIRED_STRICT_XFAILS: dict[str, str] = {
    "test_a_stranger_opens_the_field_store_with_xarray": "F1",
    "test_the_field_store_metadata_is_valid_json": "F1",
    "test_the_run_declares_a_derived_identity": "F1",
}


def _names_xfail(node: ast.AST) -> bool:
    """Return True for any node that reaches ``pytest.mark.xfail``."""
    if isinstance(node, ast.Call):
        return _names_xfail(node.func)
    return isinstance(node, ast.Attribute) and node.attr == "xfail"


def _is_strict_xfail(node: ast.expr) -> bool:
    """Return True for an explicit ``pytest.mark.xfail(strict=True, ...)``.

    ``pytest.ini`` sets ``xfail_strict = true``, so a bare ``pytest.mark.xfail``
    is strict as well. This tier refuses the bare form (checked below) so that
    reading a test file tells the truth about what it does.
    """
    if not isinstance(node, ast.Call) or not _names_xfail(node):
        return False
    return any(
        keyword.arg == "strict" and isinstance(keyword.value, ast.Constant) and keyword.value.value
        for keyword in node.keywords
    )


def _collect_strict_xfails() -> dict[str, str]:
    """Return every strict-xfail test of the tier, mapped to its module name."""
    found: dict[str, str] = {}
    for path in sorted(TIER_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(_is_strict_xfail(decorator) for decorator in node.decorator_list):
                found[node.name] = path.name
    return found


def test_the_tier_carries_exactly_the_declared_strict_xfails() -> None:
    """Every pinned claim is named and attached to the phase that repairs it."""
    found = _collect_strict_xfails()
    assert set(found) == set(EXPECTED_STRICT_XFAILS), (
        f"undeclared strict xfails: {sorted(set(found) - set(EXPECTED_STRICT_XFAILS))}; "
        f"declared but absent: {sorted(set(EXPECTED_STRICT_XFAILS) - set(found))}"
    )
    assert len(found) == 2


def test_a_repaired_claim_is_never_marked_xfail_again() -> None:
    """A claim the code honours stays a plain test, and stays present."""
    found = _collect_strict_xfails()
    bodies = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(TIER_DIR.glob("test_*.py"))
    )
    for name in REPAIRED_STRICT_XFAILS:
        assert name not in found, f"{name} was repaired and is marked xfail again"
        assert f"def {name}(" in bodies, f"{name} was repaired and then deleted"


def test_every_strict_xfail_states_a_reason() -> None:
    """An xfail without a reason is a test nobody can act on."""
    for path in sorted(TIER_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not _is_strict_xfail(decorator):
                    continue
                reasons = [
                    keyword
                    for keyword in decorator.keywords
                    if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant)
                ]
                assert reasons, f"{path.name}::{node.name} has no reason"
                assert len(str(reasons[0].value.value)) > 20, (
                    f"{path.name}::{node.name} has a reason nobody can act on"
                )


def test_no_xfail_of_this_tier_hides_outside_a_decorator() -> None:
    """Every xfail is an explicit strict decorator on a declared test.

    A bare ``pytest.mark.xfail``, a module-level ``pytestmark``, or an xfail
    tucked into ``pytest.param(marks=...)`` would all be strict under this
    repository's ``xfail_strict = true`` and would all escape the count above.
    None of those forms is allowed here.
    """
    stray: list[str] = []
    for path in sorted(TIER_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        declared: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if not _names_xfail(decorator):
                        continue
                    if _is_strict_xfail(decorator):
                        declared.add(id(decorator))
                    else:
                        stray.append(f"{path.name}::{node.name} xfail without strict=True")
        for node in ast.walk(tree):
            if _names_xfail(node) and isinstance(node, ast.Call) and id(node) not in declared:
                stray.append(f"{path.name}:{node.lineno} xfail outside a test decorator")
    assert not stray, f"xfails the tier contract cannot count: {stray}"
