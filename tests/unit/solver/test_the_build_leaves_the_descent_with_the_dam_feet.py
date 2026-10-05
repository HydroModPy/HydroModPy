"""The lake and descent section of the MF6 build leaves D beside the model, dam feet included.

``run_pre_processing`` hands the section to ``_build_descent_and_dam_feet``: it
builds D, resolves the toe cell of each declared spillway through the
production path and writes the sidecar the extractor stores. A build that no
longer calls it stores no D and no dam foot, and a calibration scores without
forced heads, so both the call and the section are pinned.
"""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6 import build
from hydromodpy.solver.modflow6.builders import lake as lake_builder
from hydromodpy.solver.modflow_common.mesh_descent import read_descent_sidecar
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

N_ROWS, N_COLS = 5, 7
LAKE = {"res": [2 * N_COLS + 3, 2 * N_COLS + 4]}
TOE = 2 * N_COLS + 2  # west of the lake cell nearest the outlet, lower than its row neighbours


def _mesh() -> SolverMesh:
    _, cols = np.divmod(np.arange(N_ROWS * N_COLS), N_COLS)
    top = (10.0 + cols).reshape(N_ROWS, N_COLS)
    return SolverMesh.from_structured_arrays(
        nrow=N_ROWS,
        ncol=N_COLS,
        top=top,
        botm=np.full((1, N_ROWS, N_COLS), -50.0),
        dx=10.0,
        dy=10.0,
    )


def _model(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        full_path=str(tmp_path),
        model_output_name="model",
        geographic=None,
    )


def _declare_spillway(monkeypatch, declared: bool) -> None:
    outlets = [{"mover": {"to_downstream_reach": True}}] if declared else []
    monkeypatch.setattr(
        lake_builder, "_active_lake_definitions", lambda model: {"res": {"outlets": outlets}}
    )


def _build(model, outlet_xy=(0.0, 25.0)):
    return build._build_descent_and_dam_feet(
        model, _mesh(), LAKE, np.zeros(N_ROWS * N_COLS, dtype=bool), outlet_xy
    )


def test_the_build_calls_the_section_that_writes_the_sidecar() -> None:
    tree = ast.parse(inspect.getsource(build.run_pre_processing))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "_build_descent_and_dam_feet" in called


def test_the_section_writes_the_sidecar_with_the_dam_feet(monkeypatch, tmp_path) -> None:
    _declare_spillway(monkeypatch, declared=True)
    model = _model(tmp_path)

    descent, seeds = _build(model)

    assert seeds == {"res": TOE}
    assert model.dam_foot_cells == {"res": TOE}
    record = read_descent_sidecar(tmp_path / "model.descent.npz")
    assert record is not None
    assert record.dam_foot.tolist() == [TOE]
    np.testing.assert_array_equal(record.receiver, descent.receiver)


def test_the_section_hands_the_feet_to_the_sidecar_write(monkeypatch, tmp_path) -> None:
    _declare_spillway(monkeypatch, declared=True)
    written = []

    def spy(descent, folder, stem, *, dam_foot_cells=None):
        written.append(dict(dam_foot_cells))

    monkeypatch.setattr(build, "write_descent_sidecar", spy)

    _build(_model(tmp_path))

    assert written == [{"res": TOE}]


def test_a_lake_without_a_declared_spillway_has_no_foot_but_D_is_stored(
    monkeypatch, tmp_path
) -> None:
    _declare_spillway(monkeypatch, declared=False)
    model = _model(tmp_path)

    _, seeds = _build(model)

    assert seeds == {}
    assert model.dam_foot_cells == {}
    record = read_descent_sidecar(tmp_path / "model.descent.npz")
    assert record is not None
    assert record.dam_foot.size == 0
