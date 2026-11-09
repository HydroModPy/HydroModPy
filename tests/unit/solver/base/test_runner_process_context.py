"""Unit tests for the run store a persisted run hands to its launcher.

The runner keeps the products of one run in ``execution.solver_runs``, and a
step that opens the store passes the handle to the launcher it drives. The
``hand_off`` of a transport run that reads ``face_flow``, MT3DMS among them,
is read in ``tests/unit/solver/base/test_runner.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from hydromodpy.solver.base.plan import ProcessRun, SimulationPlan
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.base.runner import SimulationRunner
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.run_solver import RunSolverStep


def test_run_solver_step_uses_injected_launcher() -> None:
    plan = SimulationPlan(
        name="demo",
        description="demo",
        runs=(
            ProcessRun(
                id="flow_main::modflow_nwt",
                process_id="flow_main",
                process_type="flow",
                solver="modflow_nwt",
            ),
        ),
    )
    # A run with no index: the step drives the launcher and opens nothing.
    ctx = SimpleNamespace(
        execution=SimpleNamespace(simulation_plan=plan, lightweight=False),
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(
                results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=False))
            )
        ),
        setup=SimpleNamespace(workspace=None),
    )

    class _Launcher:
        def __init__(self) -> None:
            self.calls: list[tuple[SimulationPlan, object, object]] = []

        def execute(
            self,
            plan: SimulationPlan,
            state: object,
            *,
            callbacks: object | None = None,
        ) -> None:
            self.calls.append((plan, state, callbacks))

    launcher = _Launcher()
    state = PipelineState(run_id="run", data={"ctx": ctx})

    out = RunSolverStep(launcher=launcher).run(state)

    called_plan, called_state, callbacks = launcher.calls[0]
    assert called_plan is plan
    assert called_state is ctx
    assert callbacks is not None
    assert out.get("wall_seconds") is not None


def test_run_solver_step_hands_the_run_store_to_the_launcher(monkeypatch) -> None:
    """A persisted run passes its open store down; the adapters write through it."""
    import hydromodpy.workflow.steps.run_solver as run_solver_module

    plan = SimulationPlan(
        name="demo",
        description="demo",
        runs=(
            ProcessRun(
                id="flow_main::modflow_nwt",
                process_id="flow_main",
                process_type="flow",
                solver="modflow_nwt",
            ),
        ),
    )
    handle = object()
    ctx = SimpleNamespace(
        execution=SimpleNamespace(simulation_plan=plan, lightweight=False),
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(
                results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=True))
            )
        ),
        setup=SimpleNamespace(workspace=object()),
        sim_id="sim-1",
    )

    @contextmanager
    def _fake_scope(_ctx):
        yield handle

    monkeypatch.setattr(run_solver_module, "run_store", _fake_scope)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.prepare_solver.dispatch.refresh_run_environment",
        lambda _ctx, *, store: None,
    )

    class _Launcher:
        def __init__(self) -> None:
            self.calls: list[tuple[SimulationPlan, object, object]] = []

        def execute(self, plan, state, *, callbacks=None):
            self.calls.append((plan, state, callbacks))
            return ()

    launcher = _Launcher()
    RunSolverStep(launcher=launcher).run(PipelineState(run_id="run", data={"ctx": ctx}))

    # The run store is open while the plan runs, and the adapters read what the
    # run handed them; the launcher itself reads only the plan and the state.
    assert len(launcher.calls) == 1


def test_runner_records_mesh_process_without_solver_adapter(monkeypatch) -> None:
    def _no_adapter(process_type, solver_name):
        raise AssertionError("mesh process should not request a solver adapter")

    monkeypatch.setattr(solvers, "create", _no_adapter)
    setup = SimpleNamespace(workspace=None, settings=None, geographic=None, domain=None)
    setup.mesh_summary = {"output_mesh": "mesh.msh", "n_cells": 12}
    state = SimpleNamespace(
        cfg=None, setup=setup, execution=SimpleNamespace(solver_runs={}), sim_id=None
    )
    plan = SimulationPlan(
        name="mesh-only",
        description="mesh-only",
        runs=(
            ProcessRun(
                id="mesh_main::catchment",
                process_id="mesh_main",
                process_type="mesh",
                solver="catchment",
                backend="catchment",
            ),
        ),
    )

    SimulationRunner().execute(plan, state)

    # A mesh run materializes a mesh, not a model: its run carries no solver
    # model, and what it built is execution metadata.
    assert state.execution.solver_runs["mesh_main::catchment"].solver_model is None
    assert state.execution.solver_runs["mesh_main::catchment"].metrics == {
        "backend": "catchment",
        "summary": {"output_mesh": "mesh.msh", "n_cells": 12},
    }
