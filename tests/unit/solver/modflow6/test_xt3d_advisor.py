"""The XT3D advisor: the K tensor first, then triangles and mesh non-orthogonality.

A tilted tensor, or a K22 whose axes leave the connections, needs XT3D for a
consistent result. Automatic mode then turns it on with a RuntimeWarning on
its cost, and a written false raises one on the inconsistency.
"""

from __future__ import annotations

import contextlib
import logging
import warnings

import numpy as np
import pytest

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.quality import nonorthogonality_summary
from hydromodpy.solver.modflow6.builders.solver_options import (
    _recommend_xt3d,
    resolve_xt3d_decision,
)
from hydromodpy.solver.modflow6.builders.solver_options import (
    logger as advisor_logger,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mf6_toy_models import toy_model, two_triangle_model
from tests._helpers.solver_meshes import solver_mesh_from

# A unit square split on its diagonal is orthogonal; a 3:1 rectangle split the
# same way skews the shared-edge connection by ~53 deg.


@contextlib.contextmanager
def _no_runtime_warning():
    """Turn any RuntimeWarning into an error, so a test fails on one."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        yield


def _quad_solver_mesh(shear: float):
    """Two quadrilaterals side by side, the top row shifted by ``shear`` meters.

    ``shear = 0`` gives two unit squares, an orthogonal connection; ``shear = 1`` a
    connection at 45 degrees to the normal of the shared face.
    """
    vertices = [
        [0.0, 0.0],
        [1.0, 0.0],
        [2.0, 0.0],
        [shear, 1.0],
        [1.0 + shear, 1.0],
        [2.0 + shear, 1.0],
    ]
    conn = np.asarray([[0, 1, 4, 3], [1, 2, 5, 4]], dtype=int)
    planar = HydroMesh(
        vertices=np.asarray(vertices, dtype=float),
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),),
    )
    return solver_mesh_from(
        planar,
        top=np.asarray([10.0, 10.0], dtype=float),
        botm=np.asarray([[1.0, 1.0]], dtype=float),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )


def _model_on(solver_mesh: SolverMesh):
    model = two_triangle_model()
    model.solver_mesh = solver_mesh
    return model


def test_recommend_off_on_near_orthogonal_quadrilaterals() -> None:
    model = _model_on(_quad_solver_mesh(0.0))
    advice = _recommend_xt3d(model, model.solver_mesh)
    assert advice.enabled is False
    assert "near-orthogonal" in advice.reason


def test_recommend_on_for_skewed_quadrilaterals() -> None:
    model = _model_on(_quad_solver_mesh(1.0))
    advice = _recommend_xt3d(model, model.solver_mesh)
    assert advice.enabled is True
    assert advice.required is False
    assert "non-orthogonality" in advice.reason


def test_auto_on_decision_for_skewed_mesh() -> None:
    model = _model_on(_quad_solver_mesh(1.0))
    decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is True
    assert decision.source == "auto_on"


def _with_override(model, value: bool):
    return model.modflow_config.model_copy(
        update={
            "runtime": model.modflow_config.runtime.model_copy(update={"mf6_enable_xt3d": value})
        }
    )


def _with_tensor(model, *, k22_ratio: float, angle1: float | None = None):
    """Set K, a K22 of ``k22_ratio`` times K and an optional angle1 on every cell."""
    shape = (model.nlay, model.ncpl)
    model.hk = np.full(shape, 1e-4)
    model.k22 = k22_ratio * model.hk
    model.angle1 = None if angle1 is None else np.full(shape, angle1)
    return model


@pytest.mark.parametrize("angle1", [0.0, 90.0, -180.0, None])
def test_k22_along_the_axes_of_a_structured_grid_leaves_xt3d_off(angle1: float | None) -> None:
    model = _with_tensor(toy_model(), k22_ratio=0.1, angle1=angle1)
    with _no_runtime_warning():
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is False
    assert decision.source == "auto_off"


@pytest.mark.parametrize("angle1", [None, 0.0])
def test_k22_on_a_near_orthogonal_unstructured_mesh_turns_xt3d_on(angle1: float | None) -> None:
    model = _with_tensor(_model_on(_quad_solver_mesh(0.0)), k22_ratio=0.2, angle1=angle1)
    assert not model.solver_mesh.is_structured
    assert nonorthogonality_summary(model.solver_mesh.planar_mesh)["p95"] < 1.0
    with pytest.warns(RuntimeWarning, match="unstructured mesh"):
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is True
    assert decision.source == "auto_on"


def test_explicit_false_with_an_off_axis_k22_raises_a_runtime_warning() -> None:
    model = _with_tensor(toy_model(), k22_ratio=0.1, angle1=30.0)
    model.modflow_config = _with_override(model, False)
    with pytest.warns(RuntimeWarning, match="inconsistent"):
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is False
    assert decision.source == "explicit_off"
