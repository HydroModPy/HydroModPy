"""What the MODFLOW 6 and MODFLOW-NWT flow adapters do with the grid of a run.

Each backend finds the cell of a gauge on its own grid, so the caller never
learns which grid it got. The planar mesh the run built reaches the solver in
``Model.geometry.cells``, and an adapter that finds none says the mesh step did
not run. Coordinates and cell sizes are in m.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshError
from hydromodpy.core.state.run_state import RunState
from hydromodpy.model.model import ModelOptions
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SimulationPlan
from hydromodpy.solver.modflow6.adapter import Modflow6FlowAdapter, _collapse_to_disv_cells
from hydromodpy.solver.modflow_common.observable_extraction import flat_cell_index
from hydromodpy.solver.modflow_nwt.adapter import ModflowNwtFlowAdapter
from tests._helpers.mf6_toy_models import regular_solver_mesh


def solver_run_of(model: object) -> SimpleNamespace:
    """The ``SolverRun`` a cell lookup reads: the solver model its run built."""
    return SimpleNamespace(solver_model=model)


def mf6_run(mesh: object) -> SimpleNamespace:
    return solver_run_of(SimpleNamespace(solver_mesh=mesh))


def nwt_run(grid: object) -> SimpleNamespace:
    return solver_run_of(SimpleNamespace(mf=SimpleNamespace(modelgrid=grid)))


def nwt_grid() -> SimpleNamespace:
    """A 2 x 3 flopy-like grid of 10 m cells, centers on a 10 m lattice from the origin."""
    return SimpleNamespace(
        xcellcenters=np.array([[0.0, 10.0, 20.0], [0.0, 10.0, 20.0]]),
        ycellcenters=np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]),
        delr=np.full(3, 10.0),
        delc=np.full(2, 10.0),
    )


def test_mf6_point_beyond_a_cell_size_is_not_located(caplog) -> None:
    mesh = regular_solver_mesh(2, 3)

    with caplog.at_level("WARNING"):
        cell = Modflow6FlowAdapter().locate_cell(mf6_run(mesh), 40.0, -3.0)

    assert cell is None
    assert "(40.00, -3.00)" in caplog.text


def test_mf6_selector_is_a_fixed_point_of_the_cell_readers() -> None:
    model = SimpleNamespace(solver_mesh=regular_solver_mesh(2, 3))

    cell = Modflow6FlowAdapter().locate_cell(solver_run_of(model), 2.5, 0.5)

    # The head reader collapses (row, col) to the flat id, the discharge reader
    # flattens it: a flat selector goes through both unchanged.
    assert _collapse_to_disv_cells({"gauge": cell}, model) == {"gauge": cell}
    assert flat_cell_index(model, cell) == 1 * 3 + 2


def test_no_model_yields_no_cell() -> None:
    assert Modflow6FlowAdapter().locate_cell(solver_run_of(None), 0.0, 0.0) is None


def test_nwt_reads_its_own_flopy_grid() -> None:
    cell = ModflowNwtFlowAdapter().locate_cell(nwt_run(nwt_grid()), 21.0, 11.0)

    assert cell == (0, 1, 2)


def test_nwt_point_beyond_a_cell_size_is_not_located(caplog) -> None:
    # Cells of 10 m: 14 m east of the last center is 9 m out, 16 m is 11 m out.
    run = nwt_run(nwt_grid())
    assert ModflowNwtFlowAdapter().locate_cell(run, 34.0, 10.0) == (0, 1, 2)

    with caplog.at_level("WARNING"):
        assert ModflowNwtFlowAdapter().locate_cell(run, 36.0, 10.0) is None
    assert "(36.00, 10.00)" in caplog.text


def test_nwt_without_a_grid_yields_no_cell() -> None:
    assert ModflowNwtFlowAdapter().locate_cell(nwt_run(None), 0.0, 0.0) is None


def test_calibration_layer_knows_no_backend_internals() -> None:
    source = Path("hydromodpy/calibration/metrics/solver_extract.py").read_text(encoding="utf-8")

    assert "modelgrid" not in source
    assert "solver_mesh" not in source


class FakeSolver:
    """Stands for the solver class: records what ``pre_processing`` receives."""

    instances: list[FakeSolver] = []

    def __init__(self, **kwargs) -> None:
        self.init = dict(kwargs)
        self.pre_model: object | None = None
        self.pre_kwargs: dict[str, object] = {}
        type(self).instances.append(self)

    def pre_processing(self, model, **kwargs) -> None:
        self.pre_model = model
        self.pre_kwargs = dict(kwargs)

    def processing(self, options) -> bool:
        del options
        return True


MESH_REFUSALS = [
    pytest.param(
        Modflow6FlowAdapter,
        "hydromodpy.solver.modflow6.adapter.Modflow6",
        "modflow6",
        id="modflow6",
    ),
    pytest.param(
        ModflowNwtFlowAdapter,
        "hydromodpy.solver.modflow_nwt.adapter.ModflowNwt",
        "modflow_nwt",
        id="modflow nwt",
    ),
]


@pytest.mark.parametrize(("adapter_cls", "solver_path", "solver"), MESH_REFUSALS)
def test_run_without_a_cell_mesh_stops_before_the_solver_builds(
    adapter_cls, solver_path, solver, tmp_path, monkeypatch
) -> None:
    FakeSolver.instances = []
    monkeypatch.setattr(solver_path, FakeSolver)
    model = SimpleNamespace(
        geometry=SimpleNamespace(cells=None),
        time=SimpleNamespace(grid=None),
        options=ModelOptions(
            sink_fill=False,
            drain_band_depth_m=1.0,
            drain_bed_thickness_m=1.0,
            drain_conductance_floor_m2_s=1e-12,
        ),
    )
    plan = SimulationPlan(
        name="demo",
        description="demo",
        runs=(
            ProcessRun(
                id=f"flow_main::{solver}",
                process_id="flow_main",
                process_type="flow",
                solver=solver,
            ),
        ),
    )
    context = RunContext(plan=plan, run=plan.runs[0], state=RunState(cfg=SimpleNamespace()))

    with pytest.raises(MeshError, match="mesh step"):
        adapter_cls().build(model, SimpleNamespace(), RunSlot(tmp_path, "island"), context)

    assert all(fake.pre_model is None for fake in FakeSolver.instances)
