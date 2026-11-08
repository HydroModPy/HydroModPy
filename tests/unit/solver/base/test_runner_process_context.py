"""Unit tests for runner-driven process-context materialization."""

from types import SimpleNamespace

from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.transport.transport_config import TransportConfig
from hydromodpy.solver.base.plan import ProcessRun, RunContext, SimulationPlan, SolverRun
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.base.runner import ProcessCallbacks, SimulationRunner
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.run_solver import RunSolverStep
from tests._helpers.fake_solvers import FakeAdapter


class _RecordingAdapter(FakeAdapter):
    def __init__(self, produced_model: object) -> None:
        super().__init__()
        self.produced_model = produced_model
        self.contexts: list[RunContext] = []

    def build(self, model, options, slot, ctx):
        self.contexts.append(ctx)
        return SolverRun(slot=slot, model=model, solver_model=self.produced_model)


def _build_state() -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(
            flow=FlowConfig(),
            transport=TransportConfig(),
        ),
        setup=SimpleNamespace(
            workspace=None,
            settings=None,
            geographic=None,
            domain=None,
            flow=None,
            model=object(),
            transport=None,
        ),
        execution=SimpleNamespace(
            solver_runs={},
        ),
        sim_id=None,
    )


def test_runner_ensures_the_transport_and_never_the_flow_before_the_callback(monkeypatch) -> None:
    flow_model = object()
    transport_model = object()
    flow_adapter = _RecordingAdapter(flow_model)
    transport_adapter = _RecordingAdapter(transport_model)
    adapters = {
        ("flow", "modflow_nwt"): flow_adapter,
        ("transport", "mt3dms"): transport_adapter,
    }
    monkeypatch.setattr(
        solvers, "create", lambda process_type, solver_name: adapters[(process_type, solver_name)]
    )

    observations: dict[str, tuple[bool, bool]] = {}
    state = _build_state()
    runner = SimulationRunner(
        callbacks=ProcessCallbacks(
            before_process=lambda process_type: observations.setdefault(
                process_type,
                (state.setup.flow is not None, state.setup.transport is not None),
            ),
        )
    )
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
            ProcessRun(
                id="transport_main::mt3dms",
                process_id="transport_main",
                process_type="transport",
                solver="mt3dms",
                depends_on=("flow_main::modflow_nwt",),
            ),
        ),
    )

    runner.execute(plan, state)

    assert observations["flow"] == (False, False)
    assert observations["transport"] == (False, True)
    assert flow_adapter.contexts[0].upstream == ()
    (flow_run,) = transport_adapter.contexts[0].upstream
    assert flow_run.solver_model is flow_model
    assert {
        run_id: produced.solver_model for run_id, produced in state.execution.solver_runs.items()
    } == {
        "flow_main::modflow_nwt": flow_model,
        "transport_main::mt3dms": transport_model,
    }


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
            self.calls: list[tuple[SimulationPlan, object, object, object]] = []

        def execute(
            self,
            plan: SimulationPlan,
            state: object,
            *,
            callbacks: object | None = None,
            store: object | None = None,
        ) -> None:
            self.calls.append((plan, state, callbacks, store))

    launcher = _Launcher()
    state = PipelineState(run_id="run", data={"ctx": ctx})

    out = RunSolverStep(launcher=launcher).run(state)

    called_plan, called_state, callbacks, store = launcher.calls[0]
    assert called_plan is plan
    assert called_state is ctx
    assert callbacks is not None
    assert store is None
    assert out.get("wall_seconds") is not None


def test_run_solver_step_hands_the_run_store_to_the_launcher(monkeypatch) -> None:
    """A persisted run passes its open store down; the adapters write through it."""
    from contextlib import contextmanager

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
            self.stores: list[object] = []

        def execute(self, plan, state, *, callbacks=None, store=None):
            self.stores.append(store)
            return ()

    launcher = _Launcher()
    RunSolverStep(launcher=launcher).run(PipelineState(run_id="run", data={"ctx": ctx}))

    assert launcher.stores == [handle]


def test_runner_records_mesh_process_without_solver_adapter(monkeypatch) -> None:
    def _no_adapter(process_type, solver_name):
        raise AssertionError("mesh process should not request a solver adapter")

    monkeypatch.setattr(solvers, "create", _no_adapter)
    state = _build_state()
    state.setup.mesh_summary = {"output_mesh": "mesh.msh", "n_cells": 12}
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
    observed_runs = []

    SimulationRunner(
        callbacks=ProcessCallbacks(
            after_run=lambda run, result, state: observed_runs.append((run, result)),
        )
    ).execute(plan, state)

    assert observed_runs[0][0].id == "mesh_main::catchment"
    # A mesh run materializes a mesh, not a model: its run carries no solver
    # model, and what it built is execution metadata.
    assert state.execution.solver_runs["mesh_main::catchment"].solver_model is None
    assert observed_runs[0][1].solver_model is None
    assert observed_runs[0][1].metrics == {
        "backend": "catchment",
        "summary": {"output_mesh": "mesh.msh", "n_cells": 12},
    }
