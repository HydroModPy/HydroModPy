"""The planning step."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import hydromodpy.workflow.steps.planning as planning_module
from hydromodpy.core.budget.terms import (
    POLICY_ALL,
    POLICY_CONSUMERS,
    BudgetKeep,
    budget_terms_for,
)
from hydromodpy.display.config import DisplayConfig
from hydromodpy.results.exporters.export_spec import load_export_requests
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.planning.results_config import ResultsConfig


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


# ---------------------------------------------------------------------------
# step_configure_results - the per-cell budget the run keeps
# ---------------------------------------------------------------------------


def _flow_only_plan() -> SimulationPlan:
    return SimulationPlan(
        name="flow-only",
        description="flow-only",
        runs=(_run("flow_main::modflow6", "flow", "modflow6"),),
    )


def _boussinesq_plan() -> SimulationPlan:
    return SimulationPlan(
        name="boussinesq",
        description="boussinesq",
        runs=(_run("flow_main::boussinesq", "flow", "boussinesq"),),
    )


_CONSUMERS = ResultsConfig(keep_per_cell_budget=False)


def _keep(
    results: ResultsConfig = _CONSUMERS,
    *,
    plan: SimulationPlan | None = None,
    display: DisplayConfig | None = None,
    display_active: bool = True,
    exports: list[dict] | None = None,
    calibration: object | None = None,
    observation: object | None = None,
    lightweight: bool = False,
) -> BudgetKeep:
    return planning_module.step_configure_results(
        results,
        plan or _flow_only_plan(),
        display or _no_figures(),
        display_active=display_active,
        export_requests=load_export_requests(exports or []),
        calibration=calibration,
        observation=observation,
        lightweight=lightweight,
    )


def _records(call) -> tuple[object, list[logging.LogRecord]]:
    # HMP loggers do not propagate: attach a handler to the module logger.
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    planning_module.logger.addHandler(handler)
    try:
        return call(), records
    finally:
        planning_module.logger.removeHandler(handler)


def test_the_default_keeps_the_whole_budget_and_says_nothing() -> None:
    every_consumer = DisplayConfig(figures=["recharge_map", "simulated_active_network"])

    keep, records = _records(
        lambda: _keep(ResultsConfig(), display=every_consumer, exports=[{"variables": "drain"}])
    )

    assert keep == BudgetKeep.everything()
    assert keep.policy == POLICY_ALL
    assert records == []


def test_the_default_keeps_the_whole_budget_on_a_surface_excess_plan() -> None:
    assert _keep(ResultsConfig(), plan=_boussinesq_plan()) == BudgetKeep.everything()


def test_without_consumers_the_run_keeps_no_term() -> None:
    keep, records = _records(lambda: _keep())

    assert keep == BudgetKeep.of_terms(())
    assert keep.policy == POLICY_CONSUMERS
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert "keep_per_cell_budget = false" in records[0].getMessage()


def test_a_figure_keeps_the_terms_its_required_fields_read() -> None:
    keep = _keep(display=DisplayConfig(figures=["recharge_map"]))

    assert keep.terms == frozenset(budget_terms_for("recharge"))
    assert keep.terms == {"recharge"}


def test_the_active_network_figure_keeps_the_network_criterion_terms() -> None:
    """The persistence mode reads release_flux, whatever its required field says."""
    from hydromodpy.display import figure_registry

    spec = figure_registry.get("simulated_active_network").spec
    assert spec.required_fields == ("drain_accumulation_flux",)
    assert "release_flux" in spec.optional_fields

    keep = _keep(display=DisplayConfig(figures=["simulated_active_network"]))

    assert keep.terms >= frozenset(budget_terms_for("drain_accumulation_flux"))
    assert keep.terms >= frozenset(budget_terms_for("release_flux"))


def test_a_figure_keeps_the_terms_its_optional_fields_read() -> None:
    """A map over a family of packages requires none and reads all of them."""
    from hydromodpy.display import figure_registry

    spec = figure_registry.get("boundary_package_map").spec
    assert spec.required_fields == ()

    keep = _keep(display=DisplayConfig(figures=["boundary_package_map"]))

    assert keep.terms == frozenset(spec.optional_fields)


def test_the_kept_terms_are_the_union_over_the_consumers() -> None:
    keep, records = _records(
        lambda: _keep(
            display=DisplayConfig(figures=["recharge_map", "simulated_active_network"]),
            exports=[{"variables": ["well", "head"]}],
        )
    )

    assert keep.terms == {"recharge", "drain", "drain_to_mover", "well"} | frozenset(
        budget_terms_for("release_flux")
    )
    message = records[0].getMessage()
    assert "recharge (figure 'recharge_map'" in message
    assert "well ([[export]])" in message
    assert "simulated_active_network" in message


def _observation(*variables: str, point_variables: list[str] | None = None):
    from hydromodpy.simulation.planning.observation_config import ObservationConfig

    point = {"id": "p1", "x": 1.0, "y": 2.0, "depth": 5.0}
    if point_variables is not None:
        point["variables"] = point_variables
    kwargs = {"variables": list(variables)} if variables else {}
    return ObservationConfig(points=[point], **kwargs)


def test_an_observation_point_keeps_the_terms_of_its_variables() -> None:
    keep, records = _records(
        lambda: _keep(observation=_observation(point_variables=["head", "drain", "well"]))
    )

    assert keep.terms == {"drain", "well"}
    assert "[[observation.points]] 'p1'" in records[0].getMessage()


def test_an_observation_section_variable_default_is_resolved_per_point() -> None:
    keep = _keep(observation=_observation("recharge"))

    assert keep.terms == {"recharge"}


def test_an_observation_without_points_keeps_nothing() -> None:
    from hydromodpy.simulation.planning.observation_config import ObservationConfig

    assert _keep(observation=ObservationConfig()).terms == frozenset()


def test_a_lightweight_trial_logs_the_decision_at_debug() -> None:
    _, records = _records(lambda: _keep(lightweight=True))

    assert [r.levelno for r in records] == [logging.DEBUG]


def test_an_overlay_asked_for_in_the_overrides_keeps_what_it_reads() -> None:
    display = DisplayConfig(
        figures=["piezometric_map"],
        overrides={"piezometric_map": {"overlays": ["watershed", "wells", "seepage"]}},
    )

    keep = _keep(display=display)

    assert keep.terms == {"well", *budget_terms_for("seepage_mask")}


def test_an_export_keeps_the_terms_its_names_read() -> None:
    keep = _keep(exports=[{"variables": ["release_flux"]}, {"variables": "recharge"}])

    assert keep.terms == frozenset(budget_terms_for("release_flux"))


def test_an_all_export_adds_nothing() -> None:
    assert _keep(exports=[{"variables": "all"}]).terms == frozenset()


def test_a_network_criterion_keeps_what_release_flux_reads() -> None:
    calibration = SimpleNamespace(
        outputs={
            "network": SimpleNamespace(support="network"),
            "piezometer": SimpleNamespace(support="point", variable="head"),
        }
    )

    keep, records = _records(lambda: _keep(calibration=calibration))

    assert keep.terms == frozenset(budget_terms_for("release_flux"))
    assert "calibration output 'network'" in records[0].getMessage()


def test_a_cell_output_on_a_budget_term_keeps_that_term() -> None:
    calibration = SimpleNamespace(
        outputs={"drain_cell": SimpleNamespace(support="cell", variable="drain")}
    )

    assert _keep(calibration=calibration).terms == {"drain"}


def test_a_surface_excess_solver_keeps_its_seepage_term() -> None:
    keep = _keep(plan=_boussinesq_plan())

    assert keep.terms == {"surface_excess"}


def test_a_modflow_plan_keeps_surface_excess_only_for_a_seepage_consumer() -> None:
    # seepage_map reads seepage_mask, rebuilt from surface_excess where a
    # solver writes it: asked for, kept if produced.
    assert _keep(display=DisplayConfig(figures=["seepage_map"])).terms == {"surface_excess"}
    assert _keep().terms == frozenset()


def test_no_display_drops_the_figures_and_their_overlays() -> None:
    display = DisplayConfig(
        figures=["recharge_map"],
        overrides={"recharge_map": {"overlays": ["wells"]}},
    )

    assert _keep(display=display, display_active=False).terms == frozenset()


def test_a_disabled_display_drops_the_figures() -> None:
    display = DisplayConfig(enabled=False, figures=["recharge_map"])

    assert _keep(display=display).terms == frozenset()


def test_no_display_keeps_the_other_consumers() -> None:
    keep = _keep(
        plan=_boussinesq_plan(),
        display=DisplayConfig(figures=["recharge_map"]),
        display_active=False,
        exports=[{"variables": "drain"}],
    )

    assert keep.terms == {"drain", "surface_excess"}


# ---------------------------------------------------------------------------
# resolve_run_config - an override defines the configuration of the run
# ---------------------------------------------------------------------------


def _config_with_thickness(tmp_path, thickness: float):
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.workspace.config import WorkspaceConfig
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        domain={"depth_model": {"kind": "constant_thickness", "thickness": thickness}},
    )
