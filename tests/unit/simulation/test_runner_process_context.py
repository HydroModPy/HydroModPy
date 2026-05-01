"""Unit tests for runner-driven process-context materialization."""

from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import SolverDivergedError
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
    )


def test_runner_ensures_process_context_before_before_process_callback(monkeypatch) -> None:
    flow_model = object()
    transport_model = object()
    flow_adapter = _RecordingAdapter(flow_model)
    transport_adapter = _RecordingAdapter(transport_model)
    adapters = {
        ("flow", "modflownwt"): flow_adapter,
        ("transport", "mt3dms"): transport_adapter,
    }
    from hydromodpy.simulation import _solver_protocol

    class _FakeProvider:
        def get_solver_adapter(self, process_type, solver_name):
            return adapters[(process_type, solver_name)]

    monkeypatch.setattr(_solver_protocol, "_PROVIDER", _FakeProvider())

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
                id="flow_main::modflownwt",
                process_id="flow_main",
                process_type="flow",
                solver="modflownwt",
            ),
            ProcessRun(
                id="transport_main::mt3dms",
                process_id="transport_main",
                process_type="transport",
                solver="mt3dms",
                depends_on=("flow_main::modflownwt",),
            ),
        ),
    )

    runner.execute(plan, state)

    assert observations["flow"] == (True, False)
    assert observations["transport"] == (True, True)
    assert flow_adapter.calls[0].dependency_models == ()
    assert transport_adapter.calls[0].dependency_models == (flow_model,)
    assert state.execution.models_by_run_id == {
        "flow_main::modflownwt": flow_model,
        "transport_main::mt3dms": transport_model,
    }


def test_run_solver_step_uses_injected_launcher() -> None:
    plan = SimulationPlan(
        name="demo",
        description="demo",
        runs=(
            ProcessRun(
                id="flow_main::modflownwt",
                process_id="flow_main",
                process_type="flow",
                solver="modflownwt",
            ),
        ),
    )
    ctx = SimpleNamespace(execution=SimpleNamespace(simulation_plan=plan))

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
    state = SimpleNamespace(
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
        execution=SimpleNamespace(models_by_run_id={}),
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
    state = SimpleNamespace(
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
        execution=SimpleNamespace(models_by_run_id={}),
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
        id="flow_main::modflownwt",
        process_id="flow_main",
        process_type="flow",
        solver="modflownwt",
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
    state = SimpleNamespace(
        setup=SimpleNamespace(
            flow=SimpleNamespace(active_bc=[]),
            domain=SimpleNamespace(),
            flow_runtime_overrides=None,
        ),
        execution=SimpleNamespace(models_by_run_id={}),
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
