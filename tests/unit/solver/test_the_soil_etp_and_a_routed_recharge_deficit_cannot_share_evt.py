"""The soil residual ETP and a routed negative-recharge deficit never share EVT.

Soil mode refuses ``[data.recharge]`` at load (R1), so ``build_soil_evta_payload``
and ``build_evt_stress_period_data`` returning non-``None`` together should never
happen; ``run_pre_processing`` raises instead of building one EVT package on top
of the other. This is a source-shape test (like
``test_constant_head_roles.py::test_the_output_stem_is_settled_before_any_file_is_named_after_it``):
the guard sits in a single ``noqa: PLR0915`` function no unit test calls whole.
"""

from __future__ import annotations

import ast
import inspect

from hydromodpy.solver.modflow6 import build as build_module


def _soil_evta_guard(tree: ast.AST) -> ast.If:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "soil_evta"
    )


def test_both_payloads_present_raises_before_either_package_is_built() -> None:
    tree = ast.parse(inspect.getsource(build_module.run_pre_processing))
    outer = _soil_evta_guard(tree)

    inner = outer.body[0]
    assert isinstance(inner, ast.If), "soil_evta branch must check evt_spd first"
    assert isinstance(inner.test, ast.Compare)
    assert isinstance(inner.test.left, ast.Name)
    assert inner.test.left.id == "evt_spd"

    raise_stmt = inner.body[0]
    assert isinstance(raise_stmt, ast.Raise), "the collision must raise, not fall through"
    assert isinstance(raise_stmt.exc, ast.Call)
    assert raise_stmt.exc.func.id == "RuntimeError"
    message = ast.literal_eval(raise_stmt.exc.args[0])
    assert message == (
        "the soil residual ETP and the routed negative recharge both ask for "
        "the EVT package; soil mode refuses [data.recharge], so this state is "
        "a bug."
    )
