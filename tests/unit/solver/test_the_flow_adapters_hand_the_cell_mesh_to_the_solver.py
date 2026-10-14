"""MODFLOW 6 and MODFLOW-NWT receive the cell mesh of the run, and a run without one stops.

The planar grid is the mesh the run built, never one a solver rebuilds from the
DEM. An adapter that finds no ``setup.cell_mesh`` says the mesh step did not run.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import MeshError
from hydromodpy.core.state.run_state import RunState
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.base.registry import _BUILTIN_ACCEPTED_MESHES
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter
from hydromodpy.solver.modflow_common.flow_adapter_helpers import require_cell_mesh
from hydromodpy.solver.modflow_nwt.adapters.flow import ModflowNwtFlowAdapter

_ADAPTERS = {
    "modflow6": (Modflow6FlowAdapter, "hydromodpy.solver.modflow6.adapters.flow.Modflow6"),
    "modflow_nwt": (
        ModflowNwtFlowAdapter,
        "hydromodpy.solver.modflow_nwt.adapters.flow.ModflowNwt",
    ),
}


class _FakeSolver:
    """Stands for the solver class: records what ``pre_processing`` receives."""

    instances: list[_FakeSolver] = []

    def __init__(self, geographic, *, model_folder, model_name, **kwargs) -> None:
        del geographic, kwargs
        self.model_name = model_name
        self.full_path = str(Path(model_folder) / model_name)
        self.pre_kwargs: dict[str, object] = {}
        type(self).instances.append(self)

    def pre_processing(self, **kwargs) -> None:
        self.pre_kwargs = dict(kwargs)

    def processing(self, options) -> bool:
        del options
        return True


def _context(solver: str, *, tmp_path: Path, cell_mesh: object | None) -> RunContext:
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
    flow_off = SimpleNamespace(
        intermittency=SimpleNamespace(yearly=False, monthly=False, weekly=False, daily=False),
    )
    state = RunState(
        cfg=SimpleNamespace(
            modflow6=SimpleNamespace(),
            modflownwt=SimpleNamespace(),
            solver=SimpleNamespace(
                sink_fill=False,
                drain_band_depth_m=1.0,
                drain_bed_thickness_m=1.0,
                drain_conductance_floor_m2_s=1e-12,
            ),
            postprocess=SimpleNamespace(flow=flow_off),
        ),
        setup=SimpleNamespace(
            geographic=SimpleNamespace(dem_res=1.0, xmin=0.0, ymax=1.0),
            workspace=SimpleNamespace(
                simulations_folder="unused", bin_path="bin", solver_scratch_folder=str(tmp_path)
            ),
            flow=SimpleNamespace(active_bc=[]),
            domain=SimpleNamespace(),
            cell_mesh=cell_mesh,
        ),
    )
    return RunContext(plan=plan, run=plan.runs[0], state=state)


@pytest.mark.parametrize("solver", sorted(_ADAPTERS))
def test_the_adapter_hands_the_cell_mesh_to_pre_processing(
    solver: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter_cls, solver_path = _ADAPTERS[solver]
    _FakeSolver.instances = []
    monkeypatch.setattr(solver_path, _FakeSolver)
    cell_mesh = object()

    adapter_cls().execute(_context(solver, tmp_path=tmp_path, cell_mesh=cell_mesh))

    (model,) = _FakeSolver.instances
    assert model.pre_kwargs["cell_mesh"] is cell_mesh
    assert "mesh_support" not in model.pre_kwargs


@pytest.mark.parametrize("solver", sorted(_ADAPTERS))
def test_a_run_without_a_cell_mesh_stops_before_the_solver_builds(
    solver: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter_cls, solver_path = _ADAPTERS[solver]
    _FakeSolver.instances = []
    monkeypatch.setattr(solver_path, _FakeSolver)

    with pytest.raises(MeshError, match="mesh step"):
        adapter_cls().execute(_context(solver, tmp_path=tmp_path, cell_mesh=None))

    assert all(not model.pre_kwargs for model in _FakeSolver.instances)


def test_require_cell_mesh_returns_the_mesh_of_the_setup() -> None:
    cell_mesh = object()

    assert require_cell_mesh(SimpleNamespace(cell_mesh=cell_mesh)) is cell_mesh
    with pytest.raises(MeshError):
        require_cell_mesh(SimpleNamespace(cell_mesh=None))


@pytest.mark.parametrize(
    ("key", "adapter_cls"),
    [
        (("flow", "modflow6"), Modflow6FlowAdapter),
        (("flow", "modflow_nwt"), ModflowNwtFlowAdapter),
        (("flow", "boussinesq"), BoussinesqFlowAdapter),
    ],
)
def test_an_adapter_names_the_meshes_the_registry_table_says(key, adapter_cls) -> None:
    # The registry answers from this table without importing the adapter; the
    # class attribute is what a third-party adapter declares. They cannot differ.
    assert adapter_cls.accepted_meshes == _BUILTIN_ACCEPTED_MESHES[key]
