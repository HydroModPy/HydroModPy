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
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter
from hydromodpy.solver.modflow6.adapter import Modflow6FlowAdapter
from hydromodpy.solver.modflow_common.flow_adapter_helpers import require_cell_mesh
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
def test_the_adapter_hands_the_cell_mesh_to_pre_processing(
    solver: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter_cls, solver_path = _ADAPTERS[solver]
    _FakeSolver.instances = []
    monkeypatch.setattr(solver_path, _FakeSolver)
    the_model = _model_on(object())
    slot = RunSlot(tmp_path, "island")

    built = adapter_cls().build(the_model, SimpleNamespace(), slot, _context(solver))

    (fake,) = _FakeSolver.instances
    assert fake.pre_model is the_model
    assert fake.pre_kwargs["slot"] is slot
    assert "cell_mesh" not in fake.pre_kwargs
    assert "mesh_support" not in fake.pre_kwargs
    assert built.solver_model is fake and built.model is the_model
    assert (built.written, built.solved) == (False, False), "a build writes and solves nothing"


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


def test_require_cell_mesh_returns_the_mesh_of_the_model() -> None:
    assert require_cell_mesh(_model_on(cell_mesh := object())) is cell_mesh
    with pytest.raises(MeshError):
        require_cell_mesh(_model_on(None))


@pytest.mark.parametrize(
    ("key", "adapter_cls"),
    [
        (("flow", "modflow6"), Modflow6FlowAdapter),
        (("flow", "modflow_nwt"), ModflowNwtFlowAdapter),
        (("flow", "boussinesq"), BoussinesqFlowAdapter),
    ],
)
def test_the_registry_serves_the_adapter_class_that_names_the_meshes(key, adapter_cls) -> None:
    # The registry no longer keeps a copy of the meshes: the class is the only
    # place a backend, in the tree or installed, says which meshes it reads.
    assert solvers.get(*key) is adapter_cls
    assert isinstance(adapter_cls.accepted_meshes, frozenset)
    assert adapter_cls.accepted_meshes
