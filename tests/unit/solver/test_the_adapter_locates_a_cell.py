"""Locating a gauge on the grid is the backend's job, not the caller's.

The calibration layer resolved a station to a cell by reaching into
``model.mf.modelgrid`` — a flopy object that only the MODFLOW-NWT backend owns.
That is the last of the three agnosticism defects: a layer that must serve every
solver knew the internals of one. A backend added tomorrow would silently return
no cell, and a piezometer would go unscored with nothing said.

The adapter answers instead. Each backend knows its own grid; the caller asks
and never learns which one it got.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.base.adapter_protocol import CellLocator, SolverAdapter

from ._test_modflow6_boundary_conditions_builders import (
    _build_unstructured_runtime,
    regular_solver_mesh,
)


def test_the_capability_has_its_own_protocol() -> None:
    """Not folded into SolverAdapter: a transport adapter has no grid to look on."""
    assert hasattr(CellLocator, "locate_cell")
    assert not hasattr(SolverAdapter, "locate_cell")


@pytest.mark.parametrize(
    "module,cls",
    [
        ("hydromodpy.solver.modflow6.adapters.flow", "Modflow6FlowAdapter"),
        ("hydromodpy.solver.modflow_nwt.adapters.flow", "ModflowNwtFlowAdapter"),
        ("hydromodpy.solver.boussinesq.adapters.flow", "BoussinesqFlowAdapter"),
    ],
)
def test_every_flow_backend_answers_it(module: str, cls: str) -> None:
    import importlib

    adapter = getattr(importlib.import_module(module), cls)

    assert callable(getattr(adapter, "locate_cell", None))
    assert isinstance(adapter(), CellLocator)


def _ctx(model: object) -> SimpleNamespace:
    return SimpleNamespace(
        run=SimpleNamespace(id="r1"),
        state=SimpleNamespace(),
        model=model,
    )


class TestOnASolverMesh:
    def test_a_point_in_a_grid_cell_returns_the_flat_selector_of_that_cell(self) -> None:
        from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter

        # Cells of side 1 m, row 0 north: (2.5, 0.5) is in row 1, column 2 of 2 x 3.
        mesh = regular_solver_mesh(2, 3)

        cell = Modflow6FlowAdapter().locate_cell(_ctx(SimpleNamespace(solver_mesh=mesh)), 2.5, 0.5)

        assert cell == (0, 0, 1 * 3 + 2)

    def test_a_point_in_a_triangle_returns_the_triangle_that_holds_it(self) -> None:
        from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter

        # Triangle 0 holds the points under the diagonal y = x, triangle 1 those above it.
        mesh = _build_unstructured_runtime()

        adapter = Modflow6FlowAdapter()
        assert adapter.locate_cell(_ctx(SimpleNamespace(solver_mesh=mesh)), 0.9, 0.2) == (0, 0, 0)
        assert adapter.locate_cell(_ctx(SimpleNamespace(solver_mesh=mesh)), 0.1, 0.8) == (0, 0, 1)

    def test_a_point_just_outside_takes_the_nearest_centre(self) -> None:
        from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter

        mesh = regular_solver_mesh(2, 3)

        # 0.5 m east and 0.3 m south of the south-east corner, within one cell size.
        cell = Modflow6FlowAdapter().locate_cell(_ctx(SimpleNamespace(solver_mesh=mesh)), 3.5, -0.3)

        assert cell == (0, 0, 1 * 3 + 2)

    def test_a_point_farther_than_a_cell_size_is_not_located(self, caplog) -> None:
        from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter

        mesh = regular_solver_mesh(2, 3)

        with caplog.at_level("WARNING"):
            cell = Modflow6FlowAdapter().locate_cell(
                _ctx(SimpleNamespace(solver_mesh=mesh)), 40.0, -3.0
            )

        assert cell is None
        assert "(40.00, -3.00)" in caplog.text

    def test_the_located_selector_is_a_fixed_point_of_the_readers_of_a_cell(self) -> None:
        from hydromodpy.solver.modflow6.adapters.flow import (
            Modflow6FlowAdapter,
            _collapse_to_disv_cells,
        )
        from hydromodpy.solver.modflow_common.discharge_routing import flat_cell_index

        model = SimpleNamespace(solver_mesh=regular_solver_mesh(2, 3))

        cell = Modflow6FlowAdapter().locate_cell(_ctx(model), 2.5, 0.5)

        # The head reader collapses (row, col) to the flat id, the discharge reader
        # flattens it: a flat selector goes through both unchanged.
        assert _collapse_to_disv_cells({"gauge": cell}, model) == {"gauge": cell}
        assert flat_cell_index(model, cell) == 1 * 3 + 2

    def test_no_model_yields_nothing_rather_than_a_wrong_cell(self) -> None:
        from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter

        assert Modflow6FlowAdapter().locate_cell(_ctx(None), 0.0, 0.0) is None


def _nwt_grid() -> SimpleNamespace:
    """A 2 x 3 flopy-like grid of 10 m cells, centres on a 10 m lattice from the origin."""
    return SimpleNamespace(
        xcellcenters=np.array([[0.0, 10.0, 20.0], [0.0, 10.0, 20.0]]),
        ycellcenters=np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]),
        delr=np.full(3, 10.0),
        delc=np.full(2, 10.0),
    )


class TestOnTheNwtGrid:
    def test_it_reads_its_own_flopy_grid(self) -> None:
        from hydromodpy.solver.modflow_nwt.adapters.flow import ModflowNwtFlowAdapter

        model = SimpleNamespace(mf=SimpleNamespace(modelgrid=_nwt_grid()))

        assert ModflowNwtFlowAdapter().locate_cell(_ctx(model), 21.0, 11.0) == (0, 1, 2)

    def test_a_point_farther_than_a_cell_size_is_not_located(self, caplog) -> None:
        from hydromodpy.solver.modflow_nwt.adapters.flow import ModflowNwtFlowAdapter

        model = SimpleNamespace(mf=SimpleNamespace(modelgrid=_nwt_grid()))

        # Cells of 10 m: 14 m east of the last centre is 9 m out, 16 m is 11 m out.
        assert ModflowNwtFlowAdapter().locate_cell(_ctx(model), 34.0, 10.0) == (0, 1, 2)
        with caplog.at_level("WARNING"):
            assert ModflowNwtFlowAdapter().locate_cell(_ctx(model), 36.0, 10.0) is None
        assert "(36.00, 10.00)" in caplog.text

    def test_a_model_without_a_grid_yields_nothing(self) -> None:
        from hydromodpy.solver.modflow_nwt.adapters.flow import ModflowNwtFlowAdapter

        model = SimpleNamespace(mf=SimpleNamespace(modelgrid=None))

        assert ModflowNwtFlowAdapter().locate_cell(_ctx(model), 0.0, 0.0) is None


def test_the_calibration_layer_no_longer_knows_about_flopy() -> None:
    """The point of the exercise: no backend internals in the shared path."""
    from pathlib import Path

    source = Path("hydromodpy/calibration/metrics/solver_extract.py").read_text(encoding="utf-8")

    assert "modelgrid" not in source
    assert "solver_mesh" not in source
