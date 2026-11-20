"""The ordered run list the planner builds from ``[[simulation.process]]``.

Each process expands to one run per solver, in the order the user wrote them. A transport
run is bound to the flow run it reads, and a run never depends on a later one.
"""

from __future__ import annotations

import pytest

from hydromodpy.solver.base.planner import SimulationPlanner
from hydromodpy.solver.base.simulation_config import SimulationConfig

FLOW = {"id": "f", "kind": "flow", "solvers": ["modflow_nwt"]}
TRANSPORT = {"id": "t", "kind": "transport", "solvers": ["mt3dms"]}


def config_of(*process: dict[str, object]) -> SimulationConfig:
    return SimulationConfig.model_validate({"name": "w", "process": list(process)})


def test_transport_depends_on_the_earlier_flow() -> None:
    plan = SimulationPlanner().build(config_of(FLOW, TRANSPORT))

    assert [(run.id, run.depends_on) for run in plan.runs] == [
        ("f::modflow_nwt", ()),
        ("t::mt3dms", ("f::modflow_nwt",)),
    ]


def test_unsupported_pair_is_refused() -> None:
    # The config validator names the solvers of a kind, so a solver the registry lacks needs a
    # list edited after validation.
    cfg = config_of(FLOW)
    cfg.process[0].solvers.append("nope")

    with pytest.raises(ValueError, match="Unsupported simulation process/solver pair"):
        SimulationPlanner().build(cfg)


REFUSALS = [
    pytest.param([TRANSPORT], "requires an earlier process using flow/modflow_nwt", id="no flow"),
    pytest.param(
        [TRANSPORT, FLOW],
        "requires an earlier process using flow/modflow_nwt",
        id="flow declared after",
    ),
    pytest.param(
        [FLOW | {"solvers": ["modflow6", "modflow6"]}],
        "Duplicate process run id 'f::modflow6'",
        id="solver listed twice",
    ),
]


@pytest.mark.parametrize(("process", "match"), REFUSALS)
def test_refusals(process: list[dict[str, object]], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        SimulationPlanner().build(config_of(*process))


def test_duplicate_process_id_is_refused() -> None:
    # The config validator refuses two processes of one kind, so the same id needs an edit
    # after validation.
    cfg = config_of(FLOW, TRANSPORT)
    cfg.process[1].id = "f"

    with pytest.raises(ValueError, match="Duplicate simulation process id 'f'"):
        SimulationPlanner().build(cfg)
