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

import pytest

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.model.sinks_sources.wells import WELLS_PUMPED_METRIC
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow6 import adapter as mf6_adapter
from hydromodpy.solver.modflow6.adapter import Modflow6FlowAdapter
from tests._helpers.model_factory import make_model
from tests.unit.solver.modflow_common.solver_runs import keep_all, solved_run

RUNS = [
    pytest.param({}, {"m": 1.0}, None, id="no wells, no steady start"),
    pytest.param(
        {"well_pumped_percent": 87.5},
        {"m": 1.0, WELLS_PUMPED_METRIC: 87.5},
        None,
        id="wells pumped",
    ),
    pytest.param({"initial_state_converged": True}, {"m": 1.0}, True, id="steady start converged"),
    pytest.param(
        {"initial_state_converged": False}, {"m": 1.0}, False, id="steady start not converged"
    ),
]


@pytest.mark.parametrize(("solver_attributes", "metrics", "converged"), RUNS)
def test_run_hands_back_its_facts(
    tmp_path: Path,
    monkeypatch,
    solver_attributes: dict,
    metrics: dict,
    converged: bool | None,
) -> None:
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


def test_rerun_may_change_k_and_sy(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        mf6_adapter,
        "rerun_modflow6",
        lambda previous, model, slot, *, mutable: calls.append((previous, model, slot, mutable)),
    )
    previous, model, slot = solved_run(tmp_path / "a"), make_model(), RunSlot(tmp_path, "b")

    assert Modflow6FlowAdapter().rerun(previous, model, slot) is None
    assert calls == [(previous, model, slot, frozenset({"K", "Sy"}))]


def test_extract_uses_registered_extractor(tmp_path: Path, monkeypatch) -> None:
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


def test_cleanup_removes_run_folder(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "island"
    folder.mkdir()
    (folder / "mfsim.nam").write_text("name")

    Modflow6FlowAdapter().cleanup(solved_run(folder))
    Modflow6FlowAdapter().cleanup(SolverRun(slot=RunSlot(tmp_path, "island")))

    assert not folder.exists()


def _request(name: str, *, support: str = "domain", key: str | None = None) -> ObservableRequest:
    return ObservableRequest(id=f"id:{name}", name=name, support=support, key=key)


def test_no_request_gives_nothing(tmp_path: Path) -> None:
    run = SolverRun(slot=RunSlot(tmp_path, "island"))

    assert Modflow6FlowAdapter().observables(run, []) == {}


def test_unserved_observable_refused(tmp_path: Path, monkeypatch) -> None:
    unserved = _request("nitrate")
    monkeypatch.setattr(
        mf6_adapter, "extract_common_modflow_observables", lambda *a, **k: ({}, [unserved])
    )
    run = solved_run(tmp_path / "island", solver_model=SimpleNamespace(model_output_name="i"))

    with pytest.raises(ObservableNotAvailableError, match="'nitrate'"):
        Modflow6FlowAdapter().observables(run, [unserved])


def test_observables_without_solver_refused(
    tmp_path: Path,
) -> None:
    with pytest.raises(ObservableNotAvailableError, match="'island'"):
        Modflow6FlowAdapter().observables(solved_run(tmp_path / "island"), [_request("head")])


def test_no_solver_no_cell_lookup(
    tmp_path: Path,
) -> None:
    run = solved_run(tmp_path)

    assert Modflow6FlowAdapter().locate_cell(run, 1.0, 1.0) is None
    assert Modflow6FlowAdapter().top_active_layer(run, 0, 0) is None
