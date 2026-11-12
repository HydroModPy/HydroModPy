"""The MF6 NPF options for rewetting and XT3D, and the solver complexity XT3D forces.

XT3D is off by default on a structured mesh, switches on by itself on an orthogonal triangle mesh
and follows the user when the flag is set. Rewetting is off unless asked, with a wetting factor
of 0.1 for every cell.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.initial_conditions import resolve_rewet_npf_options
from hydromodpy.solver.modflow6.builders.solver_options import (
    resolve_ims_complexity,
    resolve_xt3d_npf_options,
    xt3d_activation_mode,
    xt3d_is_enabled,
    xt3d_requested_value,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mf6_toy_models import toy_model, two_triangle_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def structured_solver_mesh() -> SolverMesh:
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm = np.ones((1, 2, 3))
    return solver_mesh_from_structured_arrays(nrow=2, ncol=3, top=top, botm=botm)


def with_runtime(model, **update):
    runtime = model.modflow_config.runtime.model_copy(update=update)
    model.modflow_config = model.modflow_config.model_copy(update={"runtime": runtime})
    return model


def test_rewet_is_off_by_default() -> None:
    rewet_record, wetdry = resolve_rewet_npf_options(toy_model(), structured_solver_mesh())
    assert rewet_record is None
    assert wetdry is None


def test_rewet_when_requested() -> None:
    model = with_runtime(toy_model(), mf6_enable_rewet=True)

    rewet_record, wetdry = resolve_rewet_npf_options(model, structured_solver_mesh())

    assert rewet_record == ["WETFCT", pytest.approx(0.1), "IWETIT", 1, "IHDWET", 0]
    np.testing.assert_allclose(wetdry, np.full((1, 6), 0.1))


def test_xt3d_is_off_by_default_on_a_structured_mesh() -> None:
    model = toy_model()
    assert xt3d_requested_value(model) is None
    assert xt3d_is_enabled(model) is False
    assert resolve_xt3d_npf_options(model) is None


def test_xt3d_when_requested_on_a_structured_mesh() -> None:
    model = with_runtime(toy_model(), mf6_enable_xt3d=True)
    assert xt3d_is_enabled(model) is True
    assert resolve_xt3d_npf_options(model) == ["XT3D"]


# (runtime update, requested value, activation mode, enabled, NPF options)
XT3D_ON_TRIANGLES = [
    pytest.param({}, None, "auto_on", True, ["XT3D"], id="auto on an orthogonal mesh"),
    pytest.param(
        {"mf6_enable_xt3d": False}, False, "explicit_off", False, None, id="explicit false"
    ),
    pytest.param(
        {"mf6_enable_xt3d": True}, True, "explicit_on", True, ["XT3D"], id="explicit true"
    ),
]


@pytest.mark.parametrize(("update", "requested", "mode", "enabled", "npf"), XT3D_ON_TRIANGLES)
def test_xt3d_on_a_triangle_mesh(update, requested, mode, enabled, npf) -> None:
    model = with_runtime(two_triangle_model(), **update)

    assert xt3d_requested_value(model) is requested
    assert xt3d_activation_mode(model, model.solver_mesh) == mode
    assert xt3d_is_enabled(model, model.solver_mesh) is enabled
    assert resolve_xt3d_npf_options(model, model.solver_mesh) == npf


def test_xt3d_forces_complex_ims() -> None:
    model = with_runtime(two_triangle_model(), mf6_ims_complexity="SIMPLE", mf6_enable_xt3d=True)

    assert xt3d_is_enabled(model, model.solver_mesh) is True
    assert resolve_ims_complexity(model, model.solver_mesh) == "COMPLEX"
