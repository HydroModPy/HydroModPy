"""MODFLOW 6 and MODFLOW-NWT receive the cell mesh of the run, and a run without one stops.

The planar grid is the mesh the run built, never one a solver rebuilds from the
DEM. It reaches the solver in ``Model.geometry.cells``. An adapter that finds
none says the mesh step did not run.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import MeshError
from hydromodpy.core.state.run_state import RunState
from hydromodpy.model.model import ModelOptions
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SimulationPlan
from hydromodpy.solver.modflow6.adapter import Modflow6FlowAdapter
from hydromodpy.solver.modflow_nwt.adapter import ModflowNwtFlowAdapter

_ADAPTERS = {
    "modflow6": (Modflow6FlowAdapter, "hydromodpy.solver.modflow6.adapter.Modflow6"),
    "modflow_nwt": (
        ModflowNwtFlowAdapter,
        "hydromodpy.solver.modflow_nwt.adapter.ModflowNwt",
    ),
}


class _FakeSolver:
    """Stands for the solver class: records what ``pre_processing`` receives."""

    instances: list[_FakeSolver] = []

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


def _model_on(cell_mesh: object | None) -> SimpleNamespace:
    """The members of a ``Model`` an adapter reads before it builds a solver."""
    return SimpleNamespace(
        geometry=SimpleNamespace(cells=cell_mesh),
        time=SimpleNamespace(grid=None),
        options=ModelOptions(
            sink_fill=False,
            drain_band_depth_m=1.0,
            drain_bed_thickness_m=1.0,
            drain_conductance_floor_m2_s=1e-12,
        ),
    )


def _context(solver: str) -> RunContext:
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
    return RunContext(plan=plan, run=plan.runs[0], state=RunState(cfg=SimpleNamespace()))


@pytest.mark.parametrize("solver", sorted(_ADAPTERS))
def test_a_run_without_a_cell_mesh_stops_before_the_solver_builds(
    solver: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter_cls, solver_path = _ADAPTERS[solver]
    _FakeSolver.instances = []
    monkeypatch.setattr(solver_path, _FakeSolver)

    with pytest.raises(MeshError, match="mesh step"):
        adapter_cls().build(
            _model_on(None), SimpleNamespace(), RunSlot(tmp_path, "island"), _context(solver)
        )

    assert all(fake.pre_model is None for fake in _FakeSolver.instances)
