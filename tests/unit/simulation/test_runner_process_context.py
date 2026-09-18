"""Unit tests for runner-driven process-context materialization."""

from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import SolverDivergedError
from hydromodpy.core.state.run_state import RunState
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.transport.transport_config import TransportConfig
from hydromodpy.simulation.execution.runner import ProcessCallbacks, SimulationRunner
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    RunExecutionResult,
    SimulationPlan,
)
from hydromodpy.solver.modflow_common.flow_adapter_helpers import run_flow_model
from hydromodpy.solver.modflow_nwt import ModflowPreprocessOptions
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.run_solver import RunSolverStep


class _RecordingAdapter:
    def __init__(self, produced_model: object) -> None:
        self.produced_model = produced_model
        self.calls = []

    def execute(self, ctx):
        self.calls.append(ctx)
        return RunExecutionResult(primary_model=self.produced_model)


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
            transport=None,
        ),
        execution=SimpleNamespace(
            models_by_run_id={},
        ),
        sim_id=None,
    )


def test_runner_ensures_process_context_before_before_process_callback(monkeypatch) -> None:
    flow_model = object()
    transport_model = object()
    flow_adapter = _RecordingAdapter(flow_model)
    transport_adapter = _RecordingAdapter(transport_model)
    adapters = {
        ("flow", "modflow_nwt"): flow_adapter,
        ("transport", "mt3dms"): transport_adapter,
    }
    from hydromodpy.core.contracts import solver_registry

    class _FakeProvider:
        def get_solver_adapter(self, process_type, solver_name):
            return adapters[(process_type, solver_name)]

    monkeypatch.setattr(solver_registry, "_PROVIDER", _FakeProvider())

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

    assert observations["flow"] == (True, False)
    assert observations["transport"] == (True, True)
    assert flow_adapter.calls[0].dependency_models == ()
    assert transport_adapter.calls[0].dependency_models == (flow_model,)
    assert state.execution.models_by_run_id == {
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
        effective_results_config=None,
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


def test_run_solver_step_hands_the_run_catalog_to_the_launcher(monkeypatch) -> None:
    """A catalogued run passes its open handle down; the adapters read it there."""
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
        effective_results_config=None,
        setup=SimpleNamespace(workspace=object()),
        sim_id="sim-1",
    )

    @contextmanager
    def _fake_scope(_ctx):
        yield handle

    monkeypatch.setattr(run_solver_module, "run_catalog", _fake_scope)
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
    from hydromodpy.core.contracts import solver_registry

    class _Provider:
        def get_solver_adapter(self, process_type, solver_name):
            raise AssertionError("mesh process should not request a solver adapter")

    monkeypatch.setattr(solver_registry, "_PROVIDER", _Provider())
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
    # A mesh run materialises a mesh, not a model: it records nothing in the
    # registry, and what it built is execution metadata.
    assert "mesh_main::catchment" not in state.execution.models_by_run_id
    assert observed_runs[0][1].metrics == {
        "backend": "catchment",
        "summary": {"output_mesh": "mesh.msh", "n_cells": 12},
    }


def test_run_flow_model_raises_when_solver_fails() -> None:
    plan = SimulationPlan(
        name="demo",
        description="demo",
        runs=(
            ProcessRun(
                id="flow_main::modflow6",
                process_id="flow_main",
                process_type="flow",
                solver="modflow6",
            ),
        ),
    )
    state = RunState(
        cfg=SimpleNamespace(
            postprocess=SimpleNamespace(
                flow=SimpleNamespace(
                    intermittency=SimpleNamespace(
                        yearly=False,
                        monthly=False,
                        weekly=False,
                        daily=False,
                    )
                )
            )
        ),
        setup=SimpleNamespace(
            flow=SimpleNamespace(active_bc=[]),
            domain=SimpleNamespace(),
            workspace=SimpleNamespace(simulations_folder="unused"),
        ),
    )

    class _FailingFlowModel:
        model_name = "demo_model"
        full_path = "tmp/demo_model"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def pre_processing(self, **kwargs) -> None:
            self.calls.append("pre")

        def processing(self, options) -> bool:
            self.calls.append("processing")
            return False

        def post_processing(self, options) -> None:
            self.calls.append("post")

    model = _FailingFlowModel()

    with pytest.raises(SolverDivergedError, match="Flow solver 'modflow6' failed"):
        run_flow_model(
            RunContext(plan=plan, run=plan.runs[0], state=state),
            model,
            ModflowPreprocessOptions(),
        )

    assert model.calls == ["pre", "processing"]


def test_run_flow_model_forwards_flow_runtime_overrides(monkeypatch) -> None:
    plan = SimulationPlan(
        name="demo",
        description="demo",
        runs=(
            ProcessRun(
                id="flow_main::modflow6",
                process_id="flow_main",
                process_type="flow",
                solver="modflow6",
            ),
        ),
    )
    state = RunState(
        cfg=SimpleNamespace(
            postprocess=SimpleNamespace(
                flow=SimpleNamespace(
                    intermittency=SimpleNamespace(
                        yearly=False,
                        monthly=False,
                        weekly=False,
                        daily=False,
                    ),
                    native_mesh_npz=False,
                    native_mesh_csv=False,
                    native_mesh_vtu=False,
                    native_mesh_png=False,
                )
            )
        ),
        setup=SimpleNamespace(
            flow=SimpleNamespace(active_bc=[]),
            domain=SimpleNamespace(),
            workspace=SimpleNamespace(simulations_folder="unused"),
            flow_runtime_overrides={"properties": {"K": [1.0, 2.0]}},
        ),
    )

    class _SuccessfulFlowModel:
        model_name = "demo_model"
        full_path = "/tmp/demo_model"

        def __init__(self) -> None:
            self.pre_kwargs = None
            self.processing_options = None

        def pre_processing(self, **kwargs) -> None:
            self.pre_kwargs = dict(kwargs)

        def processing(self, options) -> bool:
            self.processing_options = options
            return True

        def post_processing(self, options) -> None:
            return None

    model = _SuccessfulFlowModel()

    run_flow_model(
        RunContext(plan=plan, run=plan.runs[0], state=state),
        model,
        ModflowPreprocessOptions(),
    )

    assert model.pre_kwargs is not None
    assert model.pre_kwargs["flow_runtime_overrides"] == {"properties": {"K": [1.0, 2.0]}}
    assert model.processing_options.link_mt3dms is False


def test_run_flow_model_links_mt3dms_only_for_downstream_mt3dms_transport() -> None:
    flow_run = ProcessRun(
        id="flow_main::modflow_nwt",
        process_id="flow_main",
        process_type="flow",
        solver="modflow_nwt",
    )
    transport_run = ProcessRun(
        id="transport_main::mt3dms",
        process_id="transport_main",
        process_type="transport",
        solver="mt3dms",
        depends_on=(flow_run.id,),
    )
    plan = SimulationPlan(
        name="demo",
        description="demo",
        runs=(flow_run, transport_run),
    )
    state = RunState(
        setup=SimpleNamespace(
            flow=SimpleNamespace(active_bc=[]),
            domain=SimpleNamespace(),
            flow_runtime_overrides=None,
        ),
    )

    class _SuccessfulFlowModel:
        model_name = "demo_model"
        full_path = "/tmp/demo_model"

        def __init__(self) -> None:
            self.processing_options = None

        def pre_processing(self, **kwargs) -> None:
            return None

        def processing(self, options) -> bool:
            self.processing_options = options
            return True

    model = _SuccessfulFlowModel()

    run_flow_model(
        RunContext(plan=plan, run=flow_run, state=state),
        model,
        ModflowPreprocessOptions(),
    )

    assert model.processing_options.link_mt3dms is True
