"""Every site of ``hydromodpy/`` that calls a flow builder passes the engine on.

The configuration, the runtime object and both solvers carry the engine a project names,
and this gate, derived from the source, checks that nothing on the way down drops it.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast

REPO_ROOT = Path(__file__).resolve().parents[3]
"""Anchored on this file. A tree scan that reads the cwd scans nothing from tests/."""

FLOW_BUILDERS = ("build_regional_flow_products", "extract_catchment_from_point")
"""The two functions that turn a configuration into a terrain engine."""

SCANNED_BUILDERS = (*FLOW_BUILDERS, "build_solver_routing_context")
"""Plus the frame both solvers call: leaving it out once kept MODFLOW-NWT unplumbed."""

DIRECT_CALL_FLOOR = 7
"""Anti-vacuity control. A scan that reads nothing satisfies an empty assertion."""


def _python_files() -> list[Path]:
    return sorted((REPO_ROOT / "hydromodpy").rglob("*.py"))


def _named_here(node: ast.expr | None) -> str | None:
    """The builder a default expression names, through ``x or literal`` too."""
    if isinstance(node, ast.Name) and node.id in FLOW_BUILDERS:
        return node.id
    if isinstance(node, ast.BoolOp):
        return next((found for v in node.values if (found := _named_here(v)) is not None), None)
    return None


def test_every_site_that_calls_a_builder_by_name_passes_the_engine_on() -> None:
    without: list[str] = []
    sites = 0
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
                continue
            if call.func.id not in SCANNED_BUILDERS:
                continue
            sites += 1
            if not any(keyword.arg == "engine_id" for keyword in call.keywords):
                without.append(f"{path.relative_to(REPO_ROOT)}:{call.lineno}")
    assert sites >= DIRECT_CALL_FLOOR, f"found {sites} call sites, the scan read the wrong tree"
    assert without == []
