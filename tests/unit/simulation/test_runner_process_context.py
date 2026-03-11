"""Unit tests for runner-driven process-context materialization."""

from types import SimpleNamespace

import pytest

from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.process.transport.transport_config import TransportConfig
from hydromodpy.simulation.adapters.flow.modflow_common import run_flow_model
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.runtime.runner import ProcessCallbacks, SimulationRunner
from hydromodpy.simulation.runtime.runtime_contracts import RunContext, RunExecutionResult
from hydromodpy.solver.modflow_nwt import ModflowPreprocessOptions


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
        results=SimpleNamespace(
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
    monkeypatch.setattr(
        "hydromodpy.simulation.runtime.runner.get_solver_adapter",
        lambda process_type, solver_name: adapters[(process_type, solver_name)],
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
    assert state.results.models_by_run_id == {
        "flow_main::modflownwt": flow_model,
        "transport_main::mt3dms": transport_model,
    }


def test_run_flow_model_raises_when_solver_fails(monkeypatch) -> None:
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
        results=SimpleNamespace(models_by_run_id={}),
    )

    monkeypatch.setattr(
        "hydromodpy.simulation.adapters.flow.modflow_common._persist_pre_run_payload",
        lambda workspace, model_name, model_modflow: None,
    )

    class _FailingFlowModel:
        model_name = "demo_model"
        full_path = "C:/tmp/demo_model"

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

    with pytest.raises(RuntimeError, match="Flow solver 'modflow6' failed"):
        run_flow_model(
            RunContext(plan=plan, run=plan.runs[0], state=state),
            model,
            ModflowPreprocessOptions(),
        )

    assert model.calls == ["pre", "processing"]
