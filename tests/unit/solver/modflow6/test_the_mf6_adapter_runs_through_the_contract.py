"""The MODFLOW 6 flow adapter answers the members of the solver contract.

``build`` makes a ``Modflow6`` in the folder, under the name and with the
binaries the slot gives, hands it the ``Model`` and the slot, and solves
nothing. ``run`` writes and solves through the shared lifecycle and adds the
pumped share of the wells and the convergence of a steady start. ``rerun`` is
there because K and Sy can change between two solves. ``extract`` goes through
the registered extractor, and the observables, the cell lookup and the cleanup
read the ``SolverRun``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.core.state.run_state import RunState
from hydromodpy.model.sinks_sources.wells import WELLS_PUMPED_METRIC
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SimulationPlan, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow6 import adapter as mf6_adapter
from hydromodpy.solver.modflow6.adapter import Modflow6FlowAdapter
from tests._helpers.model_factory import make_model
from tests.unit.solver.modflow_common.solver_runs import keep_all, solved_run

FLOW = ProcessRun(
    id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
)
MT3DMS = ProcessRun(
    id="transport_main::mt3dms",
    process_id="transport_main",
    process_type="transport",
    solver="mt3dms",
    depends_on=(FLOW.id,),
)


def _context(*runs: ProcessRun) -> RunContext:
    plan = SimulationPlan(name="demo", description="demo", runs=runs or (FLOW,))
    return RunContext(plan=plan, run=FLOW, state=RunState(cfg=SimpleNamespace()))


class _Solver:
    """Stands for ``Modflow6``: keeps what it was built with and what it is asked."""

    instances: list[_Solver] = []

    def __init__(self, **kwargs: Any) -> None:
        self.init = kwargs
        self.full_path = str(Path(kwargs["model_folder"]) / kwargs["model_name"])
        self.pre: list[dict] = []
        type(self).instances.append(self)

    def pre_processing(self, model, **kwargs) -> None:
        self.pre.append({"model": model, **kwargs})


RUN_CASES = (
    ("a run without wells or steady start", {}, {"m": 1.0}, None),
    (
        "a run whose wells pumped",
        {"well_pumped_percent": 87.5},
        {"m": 1.0, WELLS_PUMPED_METRIC: 87.5},
        None,
    ),
    ("a steady start that converged", {"initial_state_converged": True}, {"m": 1.0}, True),
    ("a steady start that did not converge", {"initial_state_converged": False}, {"m": 1.0}, False),
)


@pytest.mark.parametrize(
    ("case", "solver_attributes", "metrics", "converged"),
    RUN_CASES,
    ids=[case[0] for case in RUN_CASES],
)
def test_a_run_solves_through_the_shared_lifecycle_and_hands_back_its_own_facts(
    tmp_path: Path,
    monkeypatch,
    case: str,
    solver_attributes: dict,
    metrics: dict,
    converged: bool | None,
) -> None:
    del case
    seen: list[tuple] = []
    solver_model = SimpleNamespace(**solver_attributes)
    solved = SolverRun(
        slot=RunSlot(tmp_path, "a"), solver_model=solver_model, solved=True, metrics={"m": 1.0}
    )
    monkeypatch.setattr(
        mf6_adapter,
        "run_flow_model",
        lambda run, *, solver_name: seen.append((run, solver_name)) or solved,
    )
    built = SolverRun(slot=RunSlot(tmp_path, "a"))

    result = Modflow6FlowAdapter().run(built)

    assert seen == [(built, "modflow6")]
    assert dict(result.metrics) == metrics
    assert result.initial_state_converged is converged
    assert result.solver_model is solver_model


def test_a_rerun_goes_through_the_rerun_of_modflow6_with_what_can_change(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        mf6_adapter,
        "rerun_modflow6",
        lambda previous, model, slot, *, mutable: calls.append((previous, model, slot, mutable)),
    )
    previous, model, slot = solved_run(tmp_path / "a"), make_model(), RunSlot(tmp_path, "b")

    assert Modflow6FlowAdapter().rerun(previous, model, slot) is None
    assert calls == [(previous, model, slot, frozenset({"K", "Sy"}))]


def test_an_extract_goes_through_the_extractor_registered_for_modflow6(
    tmp_path: Path, monkeypatch
) -> None:
    keys: list[tuple] = []
    calls: list[tuple] = []

    class _Extractor:
        def extract(self, solver_run, store, retention) -> None:
            calls.append((solver_run, store, retention))

    monkeypatch.setattr(extractors, "create", lambda *key, **_: keys.append(key) or _Extractor())
    solver_run, store = solved_run(tmp_path), object()

    Modflow6FlowAdapter().extract(solver_run, store, keep_all)

    assert keys == [("flow", "modflow6")]
    assert calls == [(solver_run, store, keep_all)]


def test_a_cleanup_removes_the_folder_of_the_run_and_forgets_a_run_without_one(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "island"
    folder.mkdir()
    (folder / "mfsim.nam").write_text("name")

    Modflow6FlowAdapter().cleanup(solved_run(folder))
    Modflow6FlowAdapter().cleanup(SolverRun(slot=RunSlot(tmp_path, "island")))

    assert not folder.exists()


DECLARED_CASES = (
    (
        "no lake and no network",
        frozenset({"drainage"}),
        "servable_under_condition",
        "servable_under_condition",
    ),
    ("a lake", frozenset({"lake"}), "servable", "servable_under_condition"),
    ("a network, written in capitals", frozenset({"SFR"}), "servable_under_condition", "servable"),
    ("both", frozenset({"lake", "sfr"}), "servable", "servable"),
)


def _request(name: str, *, support: str = "domain", key: str | None = None) -> ObservableRequest:
    return ObservableRequest(id=f"id:{name}", name=name, support=support, key=key)


def test_no_request_reads_nothing_and_needs_no_output(tmp_path: Path) -> None:
    run = SolverRun(slot=RunSlot(tmp_path, "island"))

    assert Modflow6FlowAdapter().observables(run, []) == {}


def test_an_observable_the_backend_cannot_produce_is_refused_by_name(
    tmp_path: Path, monkeypatch
) -> None:
    unserved = _request("nitrate")
    monkeypatch.setattr(
        mf6_adapter, "extract_common_modflow_observables", lambda *a, **k: ({}, [unserved])
    )
    run = solved_run(tmp_path / "island", solver_model=SimpleNamespace(model_output_name="i"))

    with pytest.raises(ObservableNotAvailableError, match="'nitrate'"):
        Modflow6FlowAdapter().observables(run, [unserved])


def test_observables_of_a_run_without_its_solver_object_are_refused_by_the_slot_name(
    tmp_path: Path,
) -> None:
    with pytest.raises(ObservableNotAvailableError, match="'island'"):
        Modflow6FlowAdapter().observables(solved_run(tmp_path / "island"), [_request("head")])


def test_a_run_without_a_solver_object_locates_nothing_and_has_no_top_layer(
    tmp_path: Path,
) -> None:
    run = solved_run(tmp_path)

    assert Modflow6FlowAdapter().locate_cell(run, 1.0, 1.0) is None
    assert Modflow6FlowAdapter().top_active_layer(run, 0, 0) is None
