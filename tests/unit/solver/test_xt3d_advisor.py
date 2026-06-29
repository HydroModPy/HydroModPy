"""The XT3D advisor: auto on/off from mesh non-orthogonality, with override warning."""

from __future__ import annotations

import contextlib
import logging

import numpy as np

from hydromodpy.solver.modflow6.builders.solver_options import (
    _recommend_xt3d,
    resolve_xt3d_decision,
)
from hydromodpy.solver.modflow6.builders.solver_options import (
    logger as advisor_logger,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.mesh_orthogonality import nonorthogonality_summary

from ._test_modflow6_boundary_conditions_builders import _build_unstructured_model

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


def _solver_mesh(vertices) -> SolverMesh:
    conn = np.asarray([[0, 1, 2], [0, 2, 3]], dtype=int)
    planar = HydroMesh(
        vertices=np.asarray(vertices, dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),
    )
    return SolverMesh(
        planar_mesh=planar,
        top=np.asarray([10.0, 10.0], dtype=float),
        botm=np.asarray([[1.0, 1.0]], dtype=float),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )


def test_nonorthogonality_orthogonal_vs_skewed() -> None:
    assert nonorthogonality_summary(_solver_mesh(_ORTHO).planar_mesh)["p95"] < 1.0
    assert nonorthogonality_summary(_solver_mesh(_SKEW).planar_mesh)["p95"] > 30.0


def test_recommend_off_on_near_orthogonal_mesh() -> None:
    model = _build_unstructured_model()
    enabled, reason = _recommend_xt3d(model, model.solver_mesh)
    assert enabled is False
    assert "near-orthogonal" in reason


def test_recommend_on_for_skewed_mesh() -> None:
    model = _build_unstructured_model()
    model.solver_mesh = _solver_mesh(_SKEW)
    enabled, reason = _recommend_xt3d(model, model.solver_mesh)
    assert enabled is True
    assert "non-orthogonality" in reason


def test_auto_off_decision_logs_info() -> None:
    model = _build_unstructured_model()  # near-orthogonal -> auto off
    with _capture_advisor_logs(logging.INFO) as records:
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is False
    assert decision.source == "auto_off"
    assert any("XT3D auto-off" in r.getMessage() for r in records)
    assert all(r.levelno == logging.INFO for r in records)


def test_auto_on_decision_for_skewed_mesh() -> None:
    model = _build_unstructured_model()
    model.solver_mesh = _solver_mesh(_SKEW)
    decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is True
    assert decision.source == "auto_on"


def test_explicit_override_warns_when_it_contradicts() -> None:
    model = _build_unstructured_model()  # checks recommend off
    model.modflow_config = model.modflow_config.model_copy(
        update={
            "runtime": model.modflow_config.runtime.model_copy(update={"mf6_enable_xt3d": True})
        }
    )
    with _capture_advisor_logs(logging.WARNING) as records:
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is True
    assert decision.source == "explicit_on"
    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert any("recommend off" in r.getMessage().lower() for r in warnings)


def test_explicit_off_agreeing_does_not_warn() -> None:
    model = _build_unstructured_model()  # checks recommend off
    model.modflow_config = model.modflow_config.model_copy(
        update={
            "runtime": model.modflow_config.runtime.model_copy(update={"mf6_enable_xt3d": False})
        }
    )
    with _capture_advisor_logs(logging.WARNING) as records:
        decision = resolve_xt3d_decision(model, model.solver_mesh)
    assert decision.enabled is False
    assert decision.source == "explicit_off"
    assert [r for r in records if r.levelno == logging.WARNING] == []
