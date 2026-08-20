from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import hydromodpy.workflow.steps.planning as planning_module
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.display.config import DisplayConfig
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.planning.results_config import DerivedConfig, ResultsConfig


def _no_figures() -> DisplayConfig:
    return DisplayConfig(figures=[])


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
            mass_accumulated=True,
            watertable_depth=False,
        )
    )
    plan = SimulationPlan(
        name="flow-only",
        description="flow-only",
        runs=(_run("flow_main::modflow6", "flow", "modflow6"),),
    )

    configured = planning_module.step_configure_results(user_cfg, plan, _no_figures()).config

    assert configured is not user_cfg
    assert configured.derived.concentration_seepage is False
    assert configured.derived.mass_seepage is False
    # mass_accumulated is built from mass_seepage: the whole solute chain goes.
    assert configured.derived.mass_accumulated is False
    assert configured.derived.watertable_depth is False
    assert user_cfg.derived.concentration_seepage is True
    assert user_cfg.derived.mass_seepage is True
    assert user_cfg.derived.mass_accumulated is True


@pytest.mark.parametrize("particle_solver", ["modflow6_prt", "modpath"])
def test_step_configure_results_disables_solute_outputs_on_a_particle_only_plan(
    particle_solver: str,
) -> None:
    # Particle tracking is a transport process that carries pathlines, not
    # concentrations. Counting it would leave the solute chain enabled and
    # promise a transport run that resolves it, which never comes.
    user_cfg = ResultsConfig(
        derived=DerivedConfig(
            concentration_seepage=True,
            mass_seepage=True,
            mass_accumulated=True,
        )
    )
    plan = SimulationPlan(
        name="flow-particles",
        description="flow-particles",
        runs=(
            _run("flow_main::modflow6", "flow", "modflow6"),
            _run(f"transport_main::{particle_solver}", "transport", particle_solver),
        ),
    )

    configured = planning_module.step_configure_results(user_cfg, plan, _no_figures()).config

    assert configured.derived.concentration_seepage is False
    assert configured.derived.mass_seepage is False
    assert configured.derived.mass_accumulated is False


def test_step_configure_results_preserves_user_config_when_transport_exists() -> None:
    # Transport is present, so neither transport-only field is pruned.
    # mass_seepage reads the per-cell drain budget, which comes back with it
    # as an intermediate.
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

    reconciled = planning_module.step_configure_results(user_cfg, plan, _no_figures())

    assert reconciled.config.derived == user_cfg.derived
    assert reconciled.config.budget.spatial_fields is True
    assert reconciled.budget_is_intermediate is True
    assert user_cfg.budget.spatial_fields is False


def test_step_configure_results_preserves_user_config_without_budget_consumer() -> None:
    user_cfg = ResultsConfig(derived=DerivedConfig(concentration_seepage=True))
    plan = SimulationPlan(
        name="flow-transport",
        description="flow-transport",
        runs=(
            _run("flow_main::modflow6", "flow", "modflow6"),
            _run("transport_main::mt3dms", "transport", "mt3dms"),
        ),
    )

    assert planning_module.step_configure_results(user_cfg, plan, _no_figures()).config is user_cfg


def test_step_configure_results_forces_budget_for_budget_dependent_derived() -> None:
    user_cfg = ResultsConfig(derived=DerivedConfig(accumulation_flux=True))
    plan = SimulationPlan(
        name="flow-only",
        description="flow-only",
        runs=(_run("flow_main::modflow6", "flow", "modflow6"),),
    )
    assert user_cfg.budget.spatial_fields is False

    # HMP loggers do not propagate: attach a handler to the module logger.
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    planning_module.logger.addHandler(handler)
    try:
        reconciled = planning_module.step_configure_results(user_cfg, plan, _no_figures())
    finally:
        planning_module.logger.removeHandler(handler)

    assert reconciled.config.budget.spatial_fields is True
    assert reconciled.config.derived.accumulation_flux is True
    assert reconciled.budget_is_intermediate is True
    assert any("accumulation_flux" in record.getMessage() for record in records)
    assert user_cfg.budget.spatial_fields is False


def test_step_configure_results_keeps_budget_off_without_budget_derived() -> None:
    user_cfg = ResultsConfig()
    plan = SimulationPlan(
        name="flow-only",
        description="flow-only",
        runs=(_run("flow_main::modflow6", "flow", "modflow6"),),
    )

    configured = planning_module.step_configure_results(user_cfg, plan, _no_figures()).config

    assert configured.budget.spatial_fields is False


def _flow_only_plan() -> SimulationPlan:
    return SimulationPlan(
        name="flow-only",
        description="flow-only",
        runs=(_run("flow_main::modflow6", "flow", "modflow6"),),
    )


def test_step_configure_results_enables_derived_required_by_a_figure() -> None:
    # A figure listed in display.figures is an explicit request: the field it
    # declares gets computed, and the budget it needs comes back with it.
    user_cfg = ResultsConfig()
    display = DisplayConfig(figures=["simulated_active_network"])

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    planning_module.logger.addHandler(handler)
    try:
        reconciled = planning_module.step_configure_results(user_cfg, _flow_only_plan(), display)
    finally:
        planning_module.logger.removeHandler(handler)

    assert reconciled.config.derived.accumulation_flux is True
    assert reconciled.config.budget.spatial_fields is True
    assert reconciled.forced_flags == ("derived.accumulation_flux", "budget.spatial_fields")
    assert any("simulated_active_network" in record.getMessage() for record in records)
    assert user_cfg.derived.accumulation_flux is False


def test_step_configure_results_keeps_head_derived_figures_unpersisted() -> None:
    # Water table and seepage are recomputed on the fly from the stored head:
    # asking for their figures must not switch the Zarr fields back on.
    configured = planning_module.step_configure_results(
        ResultsConfig(),
        _flow_only_plan(),
        DisplayConfig(figures=["piezometric_map", "watertable_depth_map", "seepage_map"]),
    ).config

    assert configured.derived.watertable_elevation is False
    assert configured.derived.watertable_depth is False
    assert configured.derived.seepage_areas is False
    assert configured.budget.spatial_fields is False


def test_step_configure_results_ignores_figures_when_display_disabled() -> None:
    configured = planning_module.step_configure_results(
        ResultsConfig(),
        _flow_only_plan(),
        DisplayConfig(enabled=False, figures=["simulated_active_network"]),
    ).config

    assert configured.derived.accumulation_flux is False
    assert configured.budget.spatial_fields is False


def test_step_configure_results_ignores_figures_when_display_is_off_for_this_run() -> None:
    # `hmp run --no-display` must cost nothing: the effective switch wins over
    # the TOML [display] section, so no figure gets to turn a flag on.
    reconciled = planning_module.step_configure_results(
        ResultsConfig(),
        _flow_only_plan(),
        DisplayConfig(figures=["simulated_active_network"]),
        display_active=False,
    )

    assert reconciled.config.derived.accumulation_flux is False
    assert reconciled.config.budget.spatial_fields is False
    assert reconciled.forced_flags == ()
    assert reconciled.budget_is_intermediate is False


def test_step_configure_results_keeps_user_requested_budget_out_of_forced_flags() -> None:
    # An explicit spatial_fields = true is a choice, never an intermediate.
    from hydromodpy.simulation.planning.results_config import BudgetConfig

    user_cfg = ResultsConfig(
        budget=BudgetConfig(spatial_fields=True),
        derived=DerivedConfig(accumulation_flux=True),
    )

    reconciled = planning_module.step_configure_results(user_cfg, _flow_only_plan(), _no_figures())

    assert reconciled.config.budget.spatial_fields is True
    assert reconciled.budget_is_intermediate is False


def _boussinesq_plan() -> SimulationPlan:
    return SimulationPlan(
        name="boussinesq",
        description="boussinesq",
        runs=(_run("flow_main::boussinesq", "flow", "boussinesq"),),
    )


def test_step_configure_results_forces_budget_for_a_raw_budget_figure_field() -> None:
    # recharge_map reads budget/recharge, a field no results.derived flag
    # covers: the group itself is the switch, so the figure turns it on and
    # the run drops it again once the figure is drawn.
    reconciled = planning_module.step_configure_results(
        ResultsConfig(),
        _flow_only_plan(),
        DisplayConfig(figures=["recharge_map"]),
    )

    assert reconciled.config.budget.spatial_fields is True
    assert reconciled.forced_flags == ("budget.spatial_fields",)
    assert reconciled.budget_is_intermediate is True


def test_step_configure_results_ignores_a_raw_budget_figure_without_display() -> None:
    reconciled = planning_module.step_configure_results(
        ResultsConfig(),
        _flow_only_plan(),
        DisplayConfig(figures=["recharge_map"]),
        display_active=False,
    )

    assert reconciled.config.budget.spatial_fields is False
    assert reconciled.forced_flags == ()


def test_derived_config_has_no_groundwater_flux_flag() -> None:
    # No backend stores the intercell face flows the field needed: MODFLOW 6
    # filters FLOW-JA-FACE out of the per-cell budget and Boussinesq has no
    # face record at all. The flag was removed rather than left to kill the
    # run after the solve.
    assert "groundwater_flux" not in DerivedConfig.model_fields
    with pytest.raises(ValidationError):
        DerivedConfig(groundwater_flux=True)


def test_step_configure_results_forces_budget_for_a_boussinesq_seepage_figure() -> None:
    # The Boussinesq seepage mask is budget/surface_excess. Without it the
    # mask silently degrades to the geometric criterion, so the budget is
    # computed as an intermediate to keep the physics.
    reconciled = planning_module.step_configure_results(
        ResultsConfig(),
        _boussinesq_plan(),
        DisplayConfig(figures=["seepage_map"]),
    )

    assert reconciled.config.budget.spatial_fields is True
    assert reconciled.budget_is_intermediate is True


def test_step_configure_results_forces_budget_for_a_boussinesq_seepage_flag() -> None:
    reconciled = planning_module.step_configure_results(
        ResultsConfig(derived=DerivedConfig(seepage_areas=True)),
        _boussinesq_plan(),
        _no_figures(),
    )

    assert reconciled.config.budget.spatial_fields is True
    assert reconciled.budget_is_intermediate is True


def test_step_configure_results_leaves_modflow_seepage_on_the_geometric_criterion() -> None:
    # MODFLOW has no surface-excess flux: the geometric mask is the criterion
    # there, not a degradation, so the budget stays off.
    reconciled = planning_module.step_configure_results(
        ResultsConfig(derived=DerivedConfig(seepage_areas=True)),
        _flow_only_plan(),
        DisplayConfig(figures=["seepage_map"]),
    )

    assert reconciled.config.budget.spatial_fields is False
    assert reconciled.forced_flags == ()
