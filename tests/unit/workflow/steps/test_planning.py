"""The planning step decides which per-cell budget terms a run keeps.

A run keeps its whole budget unless the config says that only some consumers read it.
The consumers are the figures and their overlays, the exports, the calibration
outputs, the observation points and a solver that reads the seepage mask.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import hydromodpy.workflow.steps.planning as planning_module
from hydromodpy.core.budget.terms import POLICY_ALL, BudgetKeep, budget_terms_for
from hydromodpy.display.config import DisplayConfig
from hydromodpy.results.exporters.export_spec import load_export_requests
from hydromodpy.solver.base.observation_config import ObservationConfig
from hydromodpy.solver.base.plan import ProcessRun, SimulationPlan
from hydromodpy.solver.base.results_config import ResultsConfig


def plan_of(solver: str) -> SimulationPlan:
    run = ProcessRun(
        id=f"flow_main::{solver}", process_id="flow", process_type="flow", solver=solver
    )
    return SimulationPlan(name=solver, description=solver, runs=(run,))


FLOW_ONLY = plan_of("modflow6")
BOUSSINESQ = plan_of("boussinesq")
CONSUMERS = ResultsConfig(keep_per_cell_budget=False)
NO_FIGURES = DisplayConfig(figures=[])


def keep_for(
    results: ResultsConfig = CONSUMERS,
    *,
    level: str = "result",
    plan: SimulationPlan = FLOW_ONLY,
    display: DisplayConfig = NO_FIGURES,
    display_active: bool = True,
    exports: list[dict] | None = None,
    calibration: object | None = None,
    observation: object | None = None,
    lightweight: bool = False,
) -> BudgetKeep:
    return planning_module.step_configure_results(
        results,
        plan,
        display,
        level=level,
        display_active=display_active,
        export_requests=load_export_requests(exports or []),
        calibration=calibration,
        observation=observation,
        lightweight=lightweight,
    )


def keep_with_log(**kwargs) -> tuple[BudgetKeep, list[logging.LogRecord]]:
    # HMP loggers do not propagate: attach a handler to the module logger.
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    planning_module.logger.addHandler(handler)
    try:
        return keep_for(**kwargs), records
    finally:
        planning_module.logger.removeHandler(handler)


def observation(*variables: str, point_variables: list[str] | None = None) -> ObservationConfig:
    point = {"id": "p1", "x": 1.0, "y": 2.0, "depth": 5.0}
    if point_variables is not None:
        point["variables"] = point_variables
    kwargs = {"variables": list(variables)} if variables else {}
    return ObservationConfig(points=[point], **kwargs)


DRAIN_CELL_OUTPUT = SimpleNamespace(
    outputs={"drain_cell": SimpleNamespace(support="cell", variable="drain")}
)
RECHARGE_MAP = DisplayConfig(figures=["recharge_map"])
PIEZOMETRIC_WITH_OVERLAYS = DisplayConfig(
    figures=["piezometric_map"],
    overrides={"piezometric_map": {"overlays": ["watershed", "wells", "seepage"]}},
)

# Each row is the keyword arguments of one run and the budget it keeps.
KEPT_BUDGETS = [
    pytest.param(
        {"results": ResultsConfig(), "plan": BOUSSINESQ},
        BudgetKeep.everything(),
        id="default on a surface excess plan",
    ),
    pytest.param(
        {
            "results": ResultsConfig(),
            "display": RECHARGE_MAP,
            "exports": [{"variables": "drain"}],
        },
        BudgetKeep.everything(),
        id="result run keeps its whole budget",
    ),
    pytest.param(
        {
            "results": ResultsConfig(keep_per_cell_budget=False),
            "level": "research",
            "calibration": DRAIN_CELL_OUTPUT,
            "exports": [{"variables": "recharge"}],
        },
        BudgetKeep.of_terms(("drain",)),
        id="kept trial keeps its criterion terms",
    ),
]


@pytest.mark.parametrize(("kwargs", "expected"), KEPT_BUDGETS)
def test_kept_budget(kwargs, expected) -> None:
    assert keep_for(**kwargs) == expected


# Each row is the keyword arguments of one run and the terms its consumers read.
KEPT_TERMS = [
    pytest.param(
        {"observation": observation("recharge")},
        {"recharge"},
        id="observation section variable",
    ),
    pytest.param(
        {"level": "research", "plan": BOUSSINESQ},
        {"surface_excess"},
        id="kept trial keeps the seepage mask of a surface excess solver",
    ),
    pytest.param(
        {"display": PIEZOMETRIC_WITH_OVERLAYS},
        {"well", *budget_terms_for("seepage_mask")},
        id="overlays asked in the overrides",
    ),
    pytest.param(
        {"exports": [{"variables": ["release_flux"]}, {"variables": "recharge"}]},
        frozenset(budget_terms_for("release_flux")),
        id="export names",
    ),
    pytest.param({"exports": [{"variables": "all"}]}, frozenset(), id="all export adds nothing"),
    pytest.param({"calibration": DRAIN_CELL_OUTPUT}, {"drain"}, id="cell output on a budget term"),
    pytest.param({"plan": BOUSSINESQ}, {"surface_excess"}, id="surface excess solver"),
    pytest.param(
        {
            "display": DisplayConfig(
                figures=["recharge_map"], overrides={"recharge_map": {"overlays": ["wells"]}}
            ),
            "display_active": False,
        },
        frozenset(),
        id="no display drops figures and overlays",
    ),
    pytest.param(
        {"display": DisplayConfig(enabled=False, figures=["recharge_map"])},
        frozenset(),
        id="disabled display drops figures",
    ),
]


@pytest.mark.parametrize(("kwargs", "terms"), KEPT_TERMS)
def test_kept_terms(kwargs, terms) -> None:
    assert keep_for(**kwargs).terms == terms


def test_default_keeps_the_whole_budget_and_says_nothing() -> None:
    every_consumer = DisplayConfig(figures=["recharge_map", "simulated_active_network"])

    keep, records = keep_with_log(
        results=ResultsConfig(), display=every_consumer, exports=[{"variables": "drain"}]
    )

    assert keep == BudgetKeep.everything()
    assert keep.policy == POLICY_ALL
    assert records == []


def test_observation_point_keeps_the_terms_of_its_variables() -> None:
    keep, records = keep_with_log(
        observation=observation(point_variables=["head", "drain", "well"])
    )

    assert keep.terms == {"drain", "well"}
    assert "[[observation.points]] 'p1'" in records[0].getMessage()
