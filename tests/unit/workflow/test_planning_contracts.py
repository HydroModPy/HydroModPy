from __future__ import annotations

from types import SimpleNamespace

import pytest

import hydromodpy.workflow.steps.planning as planning_module
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.planning.results_config import DerivedConfig, ResultsConfig


def _run(run_id: str, process_type: str, solver: str) -> ProcessRun:
    return ProcessRun(
        id=run_id,
        process_id=process_type,
        process_type=process_type,
        solver=solver,
    )


def test_step_build_plan_delegates_to_simulation_planner(monkeypatch) -> None:
    plan = SimulationPlan(
        name="declared",
        description="declared",
        runs=(_run("flow_main::modflow6", "flow", "modflow6"),),
    )
    built_with: list[object] = []

    class FakePlanner:
        def build(self, simulation_cfg: object) -> SimulationPlan:
            built_with.append(simulation_cfg)
            return plan

    import hydromodpy.simulation as simulation_module

    monkeypatch.setattr(simulation_module, "SimulationPlanner", FakePlanner, raising=False)
    simulation_cfg = object()
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(simulation=simulation_cfg),
        setup=SimpleNamespace(run_id=None),
        execution=SimpleNamespace(simulation_plan=None, process_runs_by_id={}),
    )

    returned = planning_module.step_build_plan(ctx, name="run-from-cli")

    assert returned is plan
    assert built_with == [simulation_cfg]
    assert ctx.setup.run_id == "run-from-cli"
    assert ctx.execution.simulation_plan is plan
    assert ctx.execution.process_runs_by_id == {"flow_main::modflow6": plan.runs[0]}


def test_step_build_plan_uses_override_branch_when_partial_inputs_are_supplied(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    override_plan = SimulationPlan(name="override", description="override")

    def fake_build_plan_with_overrides(ctx, **kwargs):
        captured["ctx"] = ctx
        captured.update(kwargs)
        return override_plan

    monkeypatch.setattr(
        planning_module,
        "_build_plan_with_overrides",
        fake_build_plan_with_overrides,
    )
    ctx = SimpleNamespace()

    returned = planning_module.step_build_plan(
        ctx,
        name="calibration-trial",
        overrides={"hydraulic_conductivity": 2.5},
        thickness=30.0,
        first_clim="wet",
        solver="modflow6",
    )

    assert returned is override_plan
    assert captured == {
        "ctx": ctx,
        "name": "calibration-trial",
        "overrides": {"hydraulic_conductivity": 2.5},
        "thickness": 30.0,
        "first_clim": "wet",
        "solver": "modflow6",
    }


def test_step_apply_flow_overrides_patches_known_parameters() -> None:
    flow = SimpleNamespace(
        parameters={
            "hydraulic_conductivity": SimpleNamespace(value=1.0),
            "specific_yield": SimpleNamespace(value=0.2),
        }
    )

    planning_module.step_apply_flow_overrides(
        flow,
        {"hydraulic_conductivity": 4.5, "specific_yield": 0.12},
    )

    assert flow.parameters["hydraulic_conductivity"].value == 4.5
    assert flow.parameters["specific_yield"].value == 0.12


def test_step_apply_flow_overrides_rejects_unknown_parameter_with_available_keys() -> None:
    flow = SimpleNamespace(
        parameters={
            "hydraulic_conductivity": SimpleNamespace(value=1.0),
            "specific_yield": SimpleNamespace(value=0.2),
        }
    )

    with pytest.raises(ConfigError, match="Unknown parameter 'porosity'"):
        planning_module.step_apply_flow_overrides(flow, {"porosity": 0.3})


def test_default_flow_solver_prefers_declared_flow_process_over_backend() -> None:
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(
                process=(
                    SimpleNamespace(type="transport", solvers=("mt3dms",)),
                    SimpleNamespace(type="flow", solvers=("modflow6", "boussinesq")),
                )
            ),
            solver=SimpleNamespace(backend_name="fallback_backend"),
        )
    )

    assert planning_module._default_flow_solver(ctx) == "modflow6"


def test_default_flow_solver_falls_back_to_solver_backend() -> None:
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(process=()),
            solver=SimpleNamespace(backend_name="boussinesq"),
        )
    )

    assert planning_module._default_flow_solver(ctx) == "boussinesq"


def test_step_configure_results_disables_transport_only_outputs_without_transport() -> None:
    user_cfg = ResultsConfig(
        derived=DerivedConfig(
            concentration_seepage=True,
            mass_seepage=True,
            watertable_depth=False,
        )
    )
    plan = SimulationPlan(
        name="flow-only",
        description="flow-only",
        runs=(_run("flow_main::modflow6", "flow", "modflow6"),),
    )

    configured = planning_module.step_configure_results(user_cfg, plan)

    assert configured is not user_cfg
    assert configured.derived.concentration_seepage is False
    assert configured.derived.mass_seepage is False
    assert configured.derived.watertable_depth is False
    assert user_cfg.derived.concentration_seepage is True
    assert user_cfg.derived.mass_seepage is True


def test_step_configure_results_preserves_user_config_when_transport_exists() -> None:
    user_cfg = ResultsConfig(
        derived=DerivedConfig(
            concentration_seepage=True,
            mass_seepage=True,
        )
    )
    plan = SimulationPlan(
        name="flow-transport",
        description="flow-transport",
        runs=(
            _run("flow_main::modflow6", "flow", "modflow6"),
            _run("transport_main::mt3dms", "transport", "mt3dms"),
        ),
    )

    assert planning_module.step_configure_results(user_cfg, plan) is user_cfg
