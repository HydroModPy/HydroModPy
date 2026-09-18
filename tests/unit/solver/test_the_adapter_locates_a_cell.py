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


class _Mesh:
    is_structured = True
    ncol = 3

    @staticmethod
    def cell_centroids() -> np.ndarray:
        return np.array(
            [[0.0, 0.0], [10.0, 0.0], [20.0, 0.0], [0.0, 10.0], [10.0, 10.0], [20.0, 10.0]],
            dtype=float,
        )


def _ctx(model: object) -> SimpleNamespace:
    return SimpleNamespace(
        run=SimpleNamespace(id="r1"),
        state=SimpleNamespace(),
        model=model,
    )


class TestOnASolverMesh:
    def test_it_returns_the_nearest_structured_cell(self) -> None:
        from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter

        cell = Modflow6FlowAdapter().locate_cell(
            _ctx(SimpleNamespace(solver_mesh=_Mesh())), 11.0, 9.0
        )

        assert cell == (0, 1, 1)

    def test_an_unstructured_mesh_returns_the_flat_selector(self) -> None:
        from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter

        class _Voronoi(_Mesh):
            is_structured = False

        cell = Modflow6FlowAdapter().locate_cell(
            _ctx(SimpleNamespace(solver_mesh=_Voronoi())), 19.0, 1.0
        )

        assert cell == (0, 0, 2)

    def test_no_model_yields_nothing_rather_than_a_wrong_cell(self) -> None:
        from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter

        assert Modflow6FlowAdapter().locate_cell(_ctx(None), 0.0, 0.0) is None


class TestOnTheNwtGrid:
    def test_it_reads_its_own_flopy_grid(self) -> None:
        from hydromodpy.solver.modflow_nwt.adapters.flow import ModflowNwtFlowAdapter

        grid = SimpleNamespace(
            xcellcenters=np.array([[0.0, 10.0, 20.0], [0.0, 10.0, 20.0]]),
            ycellcenters=np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]),
        )
        model = SimpleNamespace(mf=SimpleNamespace(modelgrid=grid))

        assert ModflowNwtFlowAdapter().locate_cell(_ctx(model), 21.0, 11.0) == (0, 1, 2)

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
