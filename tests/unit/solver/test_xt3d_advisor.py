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

from hydromodpy.solver.modflow6.builders.solver_options import (
    _recommend_xt3d,
    resolve_xt3d_decision,
)
from hydromodpy.solver.modflow6.builders.solver_options import (
    logger as advisor_logger,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.mesh_orthogonality import nonorthogonality_summary
from tests._helpers.solver_meshes import solver_mesh_from

from ._test_modflow6_boundary_conditions_builders import _build_model, _build_unstructured_model

# A unit square split on its diagonal is orthogonal; a 3:1 rectangle split the
# same way skews the shared-edge connection by ~53 deg.
_ORTHO = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
_SKEW = [[0.0, 0.0], [3.0, 0.0], [3.0, 1.0], [0.0, 1.0]]


@contextlib.contextmanager
def _capture_advisor_logs(level: int = logging.INFO):
    """Capture records on the advisor logger directly (HMP loggers do not propagate)."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    previous = advisor_logger.level
    advisor_logger.addHandler(handler)
    advisor_logger.setLevel(level)
    try:
        yield records
    finally:
        advisor_logger.removeHandler(handler)
        advisor_logger.setLevel(previous)


@contextlib.contextmanager
def _no_runtime_warning():
    """Turn any RuntimeWarning into an error, so a test fails on one."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        yield


def _solver_mesh(vertices) -> SolverMesh:
    conn = np.asarray([[0, 1, 2], [0, 2, 3]], dtype=int)
    planar = HydroMesh(
        vertices=np.asarray(vertices, dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),
    )
    return solver_mesh_from(
        planar,
        top=np.asarray([10.0, 10.0], dtype=float),
        botm=np.asarray([[1.0, 1.0]], dtype=float),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )


def _quad_solver_mesh(shear: float):
    """Two quadrilaterals side by side, the top row shifted by ``shear`` metres.

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
    model = _build_unstructured_model()
    model.solver_mesh = solver_mesh
    return model


def test_nonorthogonality_orthogonal_vs_skewed() -> None:
    assert nonorthogonality_summary(_solver_mesh(_ORTHO).planar_mesh)["p95"] < 1.0
    assert nonorthogonality_summary(_solver_mesh(_SKEW).planar_mesh)["p95"] > 30.0


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


def test_recommend_on_for_triangles_even_when_orthogonal() -> None:
    model = _model_on(_solver_mesh(_ORTHO))
    assert nonorthogonality_summary(model.solver_mesh.planar_mesh)["p95"] < 1.0
    advice = _recommend_xt3d(model, model.solver_mesh)
    assert advice.enabled is True
    assert advice.required is False
    assert "triangle cells" in advice.reason


def test_auto_off_decision_logs_info() -> None:
    model = _model_on(_quad_solver_mesh(0.0))
    with _capture_advisor_logs(logging.INFO) as records:
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is False
    assert decision.source == "auto_off"
    assert any("XT3D auto-off" in r.getMessage() for r in records)
    assert all(r.levelno == logging.INFO for r in records)


def test_auto_on_decision_for_triangles() -> None:
    model = _model_on(_solver_mesh(_ORTHO))
    with _no_runtime_warning():
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is True
    assert decision.source == "auto_on"


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


def test_explicit_override_warns_when_it_contradicts() -> None:
    model = _model_on(_quad_solver_mesh(0.0))  # checks recommend off
    model.modflow_config = _with_override(model, True)
    with _capture_advisor_logs(logging.WARNING) as records:
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is True
    assert decision.source == "explicit_on"
    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert any("recommend off" in r.getMessage().lower() for r in warnings)


def test_explicit_off_on_triangles_is_honoured_with_a_warning() -> None:
    model = _model_on(_solver_mesh(_ORTHO))  # checks recommend on
    model.modflow_config = _with_override(model, False)
    with _capture_advisor_logs(logging.WARNING) as records:
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is False
    assert decision.source == "explicit_off"
    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert any("recommend on" in r.getMessage().lower() for r in warnings)


def test_explicit_off_agreeing_does_not_warn() -> None:
    model = _model_on(_quad_solver_mesh(0.0))  # checks recommend off
    model.modflow_config = _with_override(model, False)
    with _capture_advisor_logs(logging.WARNING) as records:
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is False
    assert decision.source == "explicit_off"
    assert [r for r in records if r.levelno == logging.WARNING] == []


def _with_tensor(model, *, k22_ratio: float, angle1: float | None = None):
    """Set K, a K22 of ``k22_ratio`` times K and an optional angle1 on every cell."""
    shape = (model.nlay, model.ncpl)
    model.hk = np.full(shape, 1e-4)
    model.k22 = k22_ratio * model.hk
    model.angle1 = None if angle1 is None else np.full(shape, angle1)
    return model


def test_off_axis_k22_on_a_structured_grid_turns_xt3d_on_with_a_runtime_warning() -> None:
    model = _with_tensor(_build_model(), k22_ratio=0.1, angle1=30.0)
    assert model.solver_mesh.is_structured
    with pytest.warns(RuntimeWarning, match="about 9 to 11") as caught:
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is True
    assert decision.source == "auto_on"
    message = str(caught[0].message)
    assert "angle1 is not a multiple of 90 degrees" in message
    assert "refinement does not reduce" in message


@pytest.mark.parametrize("angle1", [0.0, 90.0, -180.0, None])
def test_k22_along_the_axes_of_a_structured_grid_leaves_xt3d_off(angle1: float | None) -> None:
    model = _with_tensor(_build_model(), k22_ratio=0.1, angle1=angle1)
    with _no_runtime_warning():
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is False
    assert decision.source == "auto_off"


def test_k22_equal_to_k_with_an_azimuth_leaves_xt3d_off() -> None:
    model = _with_tensor(_build_model(), k22_ratio=1.0, angle1=30.0)
    with _no_runtime_warning():
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is False


@pytest.mark.parametrize("angle1", [None, 0.0])
def test_k22_on_a_near_orthogonal_unstructured_mesh_turns_xt3d_on(angle1: float | None) -> None:
    model = _with_tensor(_model_on(_quad_solver_mesh(0.0)), k22_ratio=0.2, angle1=angle1)
    assert not model.solver_mesh.is_structured
    assert nonorthogonality_summary(model.solver_mesh.planar_mesh)["p95"] < 1.0
    with pytest.warns(RuntimeWarning, match="unstructured mesh"):
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is True
    assert decision.source == "auto_on"


def test_the_runtime_warning_fires_once_per_model() -> None:
    model = _with_tensor(_build_model(), k22_ratio=0.1, angle1=30.0)
    with pytest.warns(RuntimeWarning):
        first = resolve_xt3d_decision(model, model.solver_mesh)
    with _no_runtime_warning():
        assert resolve_xt3d_decision(model, model.solver_mesh) is first


def test_explicit_true_with_an_off_axis_k22_does_not_warn() -> None:
    model = _with_tensor(_build_model(), k22_ratio=0.1, angle1=30.0)
    model.modflow_config = _with_override(model, True)
    with _no_runtime_warning(), _capture_advisor_logs(logging.WARNING) as records:
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is True
    assert decision.source == "explicit_on"
    assert [r for r in records if r.levelno >= logging.WARNING] == []


def test_explicit_false_with_an_off_axis_k22_raises_a_runtime_warning() -> None:
    model = _with_tensor(_build_model(), k22_ratio=0.1, angle1=30.0)
    model.modflow_config = _with_override(model, False)
    with pytest.warns(RuntimeWarning, match="inconsistent"):
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is False
    assert decision.source == "explicit_off"


def test_a_model_without_the_tensor_never_raises_the_runtime_warning() -> None:
    for model in (
        _build_model(),
        _model_on(_solver_mesh(_ORTHO)),
        _model_on(_quad_solver_mesh(1.0)),
    ):
        with _no_runtime_warning():
            resolve_xt3d_decision(model, model.solver_mesh)


def test_the_warning_reaches_the_log_under_a_global_runtime_warning_ignore() -> None:
    """Importing flopy.plot ignores every RuntimeWarning, so the log line stands alone."""
    model = _with_tensor(_build_model(), k22_ratio=0.1, angle1=30.0)
    with warnings.catch_warnings(), _capture_advisor_logs(logging.WARNING) as records:
        warnings.simplefilter("ignore", RuntimeWarning)
        resolve_xt3d_decision(model, model.solver_mesh)
    warned = [r.getMessage() for r in records if r.levelno == logging.WARNING]
    assert any("about 9 to 11" in message for message in warned)
