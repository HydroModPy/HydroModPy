"""Every site of ``hydromodpy/`` that calls a flow builder passes the engine on.

The configuration, the runtime object and both solvers carry the engine a project names,
and this gate, derived from the source, checks that nothing on the way down drops it.
``spatial/site_selection/`` reaches the two builders through a ``builder=`` parameter, and
``[site_selection]`` has no field that names an engine (F10f).
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
WRAPPER_FLOOR = 3
"""Same, for the three wrappers that take a builder as a parameter."""


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


def _builder_parameters(function: ast.FunctionDef) -> list[str]:
    """Parameters whose default is one of the two flow builders."""
    arguments = function.args
    positional = arguments.posonlyargs + arguments.args
    pairs: list[tuple[ast.arg, ast.expr | None]] = list(
        zip(positional[len(positional) - len(arguments.defaults) :], arguments.defaults)
    )
    pairs += list(zip(arguments.kwonlyargs, arguments.kw_defaults))
    return [arg.arg for arg, default in pairs if _named_here(default) is not None]


def _declared_names(function: ast.FunctionDef) -> set[str]:
    arguments = function.args
    return {arg.arg for arg in arguments.posonlyargs + arguments.args + arguments.kwonlyargs}


def test_every_wrapper_that_receives_a_builder_declares_the_engine_and_forwards_it() -> None:
    """``build_site_selection_flow_products`` and two delineation helpers call a parameter."""
    faulty: list[str] = []
    wrappers = 0
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            parameters = _builder_parameters(function)
            if not parameters:
                continue
            wrappers += 1
            where = f"{path.relative_to(REPO_ROOT)}:{function.lineno} {function.name}"
            if "engine_id" not in _declared_names(function):
                faulty.append(f"{where} declares no engine_id")
                continue
            for call in ast.walk(function):
                if not isinstance(call, ast.Call):
                    continue
                through_parameter = isinstance(call.func, ast.Name) and call.func.id in parameters
                forwards_parameter = any(
                    isinstance(keyword.value, ast.Name) and keyword.value.id in parameters
                    for keyword in call.keywords
                )
                if not (through_parameter or forwards_parameter):
                    continue
                if not any(keyword.arg == "engine_id" for keyword in call.keywords):
                    faulty.append(f"{where} calls line {call.lineno} without engine_id")
    assert wrappers >= WRAPPER_FLOOR, f"found {wrappers} wrappers, the scan read the wrong tree"
    assert faulty == []
