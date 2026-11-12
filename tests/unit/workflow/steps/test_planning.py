"""The planning step."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import hydromodpy.workflow.steps.planning as planning_module
from hydromodpy.core.budget.terms import POLICY_ALL, BudgetKeep, budget_terms_for
from hydromodpy.display.config import DisplayConfig
from hydromodpy.results.exporters.export_spec import load_export_requests
from hydromodpy.solver.base.plan import ProcessRun, SimulationPlan
from hydromodpy.solver.base.results_config import ResultsConfig


def _no_figures() -> DisplayConfig:
    return DisplayConfig(figures=[])


def _run(run_id: str, process_type: str, solver: str) -> ProcessRun:
    return ProcessRun(
        id=run_id,
        process_id=process_type,
        process_type=process_type,
        solver=solver,
    )


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
    level: str = "result",
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
        level=level,
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


def _observation(*variables: str, point_variables: list[str] | None = None):
    from hydromodpy.solver.base.observation_config import ObservationConfig

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


# ---------------------------------------------------------------------------
# research - a kept calibration trial keeps the terms of its criterion alone
# ---------------------------------------------------------------------------


def test_a_kept_trial_keeps_its_criterion_terms_without_the_whole_budget() -> None:
    calibration = SimpleNamespace(
        outputs={"drain_cell": SimpleNamespace(support="cell", variable="drain")}
    )

    keep = _keep(
        ResultsConfig(keep_per_cell_budget=False),
        level="research",
        calibration=calibration,
        exports=[{"variables": "recharge"}],
    )

    assert keep == BudgetKeep.of_terms(("drain",))


def test_a_kept_trial_keeps_the_seepage_mask_of_a_surface_excess_solver() -> None:
    assert _keep(level="research", plan=_boussinesq_plan()).terms == {"surface_excess"}


def test_a_result_run_keeps_its_whole_budget_at_the_result_level() -> None:
    keep = _keep(
        ResultsConfig(),
        level="result",
        display=DisplayConfig(figures=["recharge_map"]),
        exports=[{"variables": "drain"}],
    )

    assert keep == BudgetKeep.everything()


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


def test_a_cell_output_on_a_budget_term_keeps_that_term() -> None:
    calibration = SimpleNamespace(
        outputs={"drain_cell": SimpleNamespace(support="cell", variable="drain")}
    )

    assert _keep(calibration=calibration).terms == {"drain"}


def test_a_surface_excess_solver_keeps_its_seepage_term() -> None:
    keep = _keep(plan=_boussinesq_plan())

    assert keep.terms == {"surface_excess"}


def test_no_display_drops_the_figures_and_their_overlays() -> None:
    display = DisplayConfig(
        figures=["recharge_map"],
        overrides={"recharge_map": {"overlays": ["wells"]}},
    )

    assert _keep(display=display, display_active=False).terms == frozenset()


def test_a_disabled_display_drops_the_figures() -> None:
    display = DisplayConfig(enabled=False, figures=["recharge_map"])

    assert _keep(display=display).terms == frozenset()


# ---------------------------------------------------------------------------
# resolve_run_config - an override defines the configuration of the run
# ---------------------------------------------------------------------------


def _config_with_thickness(tmp_path, thickness: float):
    from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.workspace.config import WorkspaceConfig

    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        domain={"depth_model": {"kind": "constant_thickness", "thickness": thickness}},
    )
