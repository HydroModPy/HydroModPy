"""The MODFLOW-NWT adapter answers the members of the solver contract.

``build`` makes a ``ModflowNwt`` in the folder, under the name and with the
binaries the slot gives, and solves nothing. ``run`` writes and solves, ``extract``
goes through the registered extractor, and the observables, the cell lookup and
the cleanup read the ``SolverRun``. NWT has no ``rerun``: nothing in its model
can change between two solves without a build.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.core.state.run_state import RunState
from hydromodpy.solver.base.adapter_protocol import (
    OPTIONAL_MEMBERS,
    RERUN_MEMBERS,
    CellLocator,
    solver_members,
)
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SimulationPlan, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow_nwt import adapter as nwt_adapter
from hydromodpy.solver.modflow_nwt.adapter import ModflowNwtFlowAdapter
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig
from tests._helpers.model_factory import make_model
from tests.unit.solver.modflow_common.solver_runs import keep_all, solved_run

FLOW = ProcessRun(
    id="flow_main::modflow_nwt", process_id="flow_main", process_type="flow", solver="modflow_nwt"
)


def _context() -> RunContext:
    plan = SimulationPlan(name="demo", description="demo", runs=(FLOW,))
    return RunContext(plan=plan, run=FLOW, state=RunState(cfg=SimpleNamespace()))


class _Solver:
    """Stands for ``ModflowNwt``: keeps what it was built with and what it is asked."""

    instances: list[_Solver] = []

    def __init__(self, **kwargs: Any) -> None:
        self.init = kwargs
        self.full_path = str(Path(kwargs["model_folder"]) / kwargs["model_name"])
        self.pre: list[dict] = []
        type(self).instances.append(self)

    def pre_processing(self, model, **kwargs) -> None:
        self.pre.append({"model": model, **kwargs})


@pytest.fixture
def fake_solver(monkeypatch) -> type[_Solver]:
    _Solver.instances = []
    monkeypatch.setattr(nwt_adapter, "ModflowNwt", _Solver)
    return _Solver


def test_the_adapter_carries_the_members_of_the_contract_and_no_rerun() -> None:
    members = [name for name in solver_members() if not hasattr(ModflowNwtFlowAdapter, name)]

    assert members == []
    assert not any(hasattr(ModflowNwtFlowAdapter, name) for name in RERUN_MEMBERS)
    assert ModflowNwtFlowAdapter.mutable == frozenset()
    assert all(hasattr(ModflowNwtFlowAdapter, name) for name in OPTIONAL_MEMBERS)
    assert isinstance(ModflowNwtFlowAdapter(), CellLocator)


def test_a_build_makes_the_solver_in_the_folder_the_slot_gives(
    tmp_path: Path, fake_solver: type[_Solver]
) -> None:
    model = make_model()
    options = ModflowConfig()
    slot = RunSlot(tmp_path, "island", bin_dir=tmp_path / "bin")

    built = ModflowNwtFlowAdapter().build(model, options, slot, _context())

    (solver,) = fake_solver.instances
    assert solver.init["model_folder"] == tmp_path
    assert solver.init["model_name"] == "island"
    assert solver.init["bin_path"] == tmp_path / "bin"
    assert solver.init["modflow_config"] is options
    assert solver.pre[0]["model"] is model and solver.pre[0]["slot"] is slot
    assert built.solver_model is solver and built.options is options and built.slot is slot
    assert (built.written, built.solved) == (False, False)


def test_a_build_makes_the_name_safe_for_the_fortran_solver(
    tmp_path: Path, fake_solver: type[_Solver]
) -> None:
    ModflowNwtFlowAdapter().build(
        make_model(), ModflowConfig(), RunSlot(tmp_path, "Example 12 launcher"), _context()
    )

    assert fake_solver.instances[0].init["model_name"] == "Example_12_launcher"


def test_a_build_without_a_binary_folder_takes_the_managed_cache(
    tmp_path: Path, fake_solver: type[_Solver]
) -> None:
    ModflowNwtFlowAdapter().build(make_model(), ModflowConfig(), RunSlot(tmp_path, "a"), _context())

    assert fake_solver.instances[0].init["bin_path"] is None


def test_a_run_solves_through_the_shared_lifecycle(tmp_path: Path, monkeypatch) -> None:
    seen: list[tuple] = []
    solved = SolverRun(slot=RunSlot(tmp_path, "a"), solved=True)
    monkeypatch.setattr(
        nwt_adapter,
        "run_flow_model",
        lambda run, *, solver_name: seen.append((run, solver_name)) or solved,
    )
    built = SolverRun(slot=RunSlot(tmp_path, "a"))

    assert ModflowNwtFlowAdapter().run(built) is solved
    assert seen == [(built, "modflow_nwt")]


def test_an_extract_goes_through_the_extractor_registered_for_nwt(
    tmp_path: Path, monkeypatch
) -> None:
    keys: list[tuple] = []
    calls: list[tuple] = []

    class _Extractor:
        def extract(self, solver_run, store, retention) -> None:
            calls.append((solver_run, store, retention))

    monkeypatch.setattr(
        extractors, "create", lambda *key, **_: keys.append(key) or _Extractor(), raising=True
    )
    solver_run, store = solved_run(tmp_path), object()

    ModflowNwtFlowAdapter().extract(solver_run, store, keep_all)

    assert keys == [("flow", "modflow_nwt")]
    assert calls == [(solver_run, store, keep_all)]


def test_the_registry_serves_the_nwt_extractor_for_the_adapter_key() -> None:
    from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter

    assert type(extractors.create("flow", "modflow_nwt")) is ModflowNwtOutputAdapter


def test_a_cleanup_removes_the_folder_of_the_run_and_forgets_a_run_without_one(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "island"
    folder.mkdir()
    (folder / "island.nam").write_text("name")

    ModflowNwtFlowAdapter().cleanup(solved_run(folder))
    ModflowNwtFlowAdapter().cleanup(SolverRun(slot=RunSlot(tmp_path, "island")))

    assert not folder.exists()


def test_the_declared_observables_do_not_depend_on_the_active_conditions() -> None:
    adapter = ModflowNwtFlowAdapter()

    everything = adapter.declared_observables(frozenset({"lake", "sfr", "drainage"}))
    nothing = adapter.declared_observables(frozenset())

    assert everything == nothing
    states = {support.name: support.state for support in everything}
    assert states["head"] == states["discharge"] == "servable"
    assert states["stage"] == states["routed_discharge"] == "unavailable"


def _request(name: str) -> ObservableRequest:
    return ObservableRequest(id=f"id:{name}", name=name, support="domain")


def test_no_request_reads_nothing_and_needs_no_output(tmp_path: Path) -> None:
    run = SolverRun(slot=RunSlot(tmp_path, "island"))

    assert ModflowNwtFlowAdapter().observables(run, []) == {}


def test_observables_are_read_on_the_output_folder_of_the_run(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "island"
    solver_model = SimpleNamespace(model_name="island")
    seen: list[tuple] = []

    def common(directory, name, model, requests, *, time_index):
        seen.append((directory, name, model, [r.id for r in requests], time_index))
        return {"id:head": "served"}, []

    monkeypatch.setattr(nwt_adapter, "extract_common_modflow_observables", common)

    got = ModflowNwtFlowAdapter().observables(
        solved_run(folder, solver_model=solver_model), [_request("head")], time_index=None
    )

    assert got == {"id:head": "served"}
    assert seen == [(folder, "island", solver_model, ["id:head"], None)]


def test_an_observable_the_backend_cannot_produce_is_refused_by_name(
    tmp_path: Path, monkeypatch
) -> None:
    unserved = _request("stage")
    monkeypatch.setattr(
        nwt_adapter, "extract_common_modflow_observables", lambda *a, **k: ({}, [unserved])
    )
    run = solved_run(tmp_path / "island", solver_model=SimpleNamespace(model_name="island"))

    with pytest.raises(ObservableNotAvailableError, match="'stage'"):
        ModflowNwtFlowAdapter().observables(run, [unserved])


def test_observables_of_a_run_without_its_solver_object_are_refused_by_the_slot_name(
    tmp_path: Path,
) -> None:
    run = solved_run(tmp_path / "island")

    with pytest.raises(ObservableNotAvailableError, match="'island'"):
        ModflowNwtFlowAdapter().observables(run, [_request("head")])


class _Grid:
    """A 2 x 3 grid of 10 m cells, rows counted from the top."""

    xcellcenters = np.array([[5.0, 15.0, 25.0], [5.0, 15.0, 25.0]])
    ycellcenters = np.array([[15.0, 15.0, 15.0], [5.0, 5.0, 5.0]])
    delr = np.full(3, 10.0)
    delc = np.full(2, 10.0)


def _located(tmp_path: Path) -> SolverRun:
    solver_model = SimpleNamespace(mf=SimpleNamespace(modelgrid=_Grid()))
    return solved_run(tmp_path, solver_model=solver_model)


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [(5.0, 15.0, (0, 0, 0)), (24.0, 4.0, (0, 1, 2)), (31.0, 5.0, (0, 1, 2))],
    ids=["first cell", "last cell", "just outside, within one cell"],
)
def test_a_point_is_located_on_the_nearest_cell_of_the_structured_grid(
    tmp_path: Path, x: float, y: float, expected: tuple[int, int, int]
) -> None:
    assert ModflowNwtFlowAdapter().locate_cell(_located(tmp_path), x, y) == expected


def test_a_point_farther_than_one_cell_is_not_located_and_the_warning_names_it(
    tmp_path: Path, caplog
) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy"):
        located = ModflowNwtFlowAdapter().locate_cell(_located(tmp_path), 80.0, 5.0)

    assert located is None
    assert any("80.00" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    "solver_model",
    [None, SimpleNamespace(), SimpleNamespace(mf=SimpleNamespace(modelgrid=None))],
    ids=["no solver object", "no grid", "a model without a model grid"],
)
def test_a_run_without_a_grid_locates_nothing(tmp_path: Path, solver_model: Any) -> None:
    assert (
        ModflowNwtFlowAdapter().locate_cell(
            solved_run(tmp_path, solver_model=solver_model), 1.0, 1.0
        )
        is None
    )


def test_a_run_without_a_solver_object_has_no_top_layer(tmp_path: Path) -> None:
    assert ModflowNwtFlowAdapter().top_active_layer(solved_run(tmp_path), 0, 0) is None
