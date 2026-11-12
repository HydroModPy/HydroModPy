"""The MODFLOW-NWT flow adapter answers the members of the solver contract.

``build`` makes a ``ModflowNwt`` in the folder, under the name and with the
binaries the slot gives, and solves nothing. ``run`` writes and solves, ``extract``
goes through the registered extractor, and the observables, the cell lookup and
the cleanup read the ``SolverRun``. NWT has no ``rerun``. Grid cells are 10 m wide.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow_common.options import ModflowRunOptions
from hydromodpy.solver.modflow_nwt import adapter as nwt_adapter
from hydromodpy.solver.modflow_nwt.adapter import ModflowNwtFlowAdapter
from tests._helpers.model_factory import make_model
from tests.unit.solver.modflow_common.solver_runs import keep_all, solved_run


@dataclass
class _FakeNwt:
    """Stands for ``ModflowNwt``: skips the model build."""

    model_folder: Path
    model_name: str
    bin_path: object = None
    modflow_config: object = None

    def __post_init__(self) -> None:
        self.link_mt3dms = False
        self.input_files: tuple[str, ...] = ()
        self.last_flow_solve_time_seconds = None
        self.full_path = Path(self.model_folder) / self.model_name

    def pre_processing(self, model=None, options=None, *, slot=None) -> None:
        self.pre_process_model = model


@dataclass
class _SolvedStandIn:
    """A solver model whose ``processing`` succeeds and records its options."""

    processing_calls: list[ModflowRunOptions] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.link_mt3dms = False
        self.full_path = None
        self.last_flow_solve_time_seconds = None

    def processing(self, options: ModflowRunOptions) -> bool:
        self.processing_calls.append(options)
        return True


class _Grid:
    """A 2 x 3 grid of 10 m cells, rows counted from the top."""

    xcellcenters = np.array([[5.0, 15.0, 25.0], [5.0, 15.0, 25.0]])
    ycellcenters = np.array([[15.0, 15.0, 15.0], [5.0, 5.0, 5.0]])
    delr = np.full(3, 10.0)
    delc = np.full(2, 10.0)


def request(name: str) -> ObservableRequest:
    return ObservableRequest(id=f"id:{name}", name=name, support="domain")


def test_build_solves_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(nwt_adapter, "ModflowNwt", _FakeNwt)
    slot = RunSlot(tmp_path, "island", bin_dir=tmp_path / "bin", hand_off=frozenset({"face_flow"}))

    built = ModflowNwtFlowAdapter().build(make_model(), None, slot)

    assert built.solver_model.model_name == "island"
    assert (built.written, built.solved, built.output_dir) == (False, False, None)


def test_run_lifecycle(tmp_path: Path, monkeypatch) -> None:
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


def test_solve_time(tmp_path: Path) -> None:
    solver_model = _SolvedStandIn()
    solver_model.full_path = tmp_path / "island"
    solver_model.last_flow_solve_time_seconds = 2.25  # s
    run = SolverRun(
        slot=RunSlot(tmp_path, "island"), solver_model=solver_model, written=True, model=None
    )

    solved = ModflowNwtFlowAdapter().run(run)

    assert solved.solve_s == 2.25
    assert "flow_solve_time_seconds" not in solved.metrics


def test_extract_via_registry(tmp_path: Path, monkeypatch) -> None:
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


def test_cleanup(tmp_path: Path) -> None:
    folder = tmp_path / "island"
    folder.mkdir()
    (folder / "island.nam").write_text("name")

    ModflowNwtFlowAdapter().cleanup(solved_run(folder))
    # A run that never had a folder is forgotten without error.
    ModflowNwtFlowAdapter().cleanup(SolverRun(slot=RunSlot(tmp_path, "island")))

    assert not folder.exists()


def test_no_request(tmp_path: Path) -> None:
    run = SolverRun(slot=RunSlot(tmp_path, "island"))

    assert ModflowNwtFlowAdapter().observables(run, []) == {}


def test_observables_in_run_folder(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "island"
    solver_model = SimpleNamespace(model_name="island")
    seen: list[tuple] = []

    def common(directory, name, model, requests, *, time_index):
        seen.append((directory, name, model, [r.id for r in requests], time_index))
        return {"id:head": "served"}, []

    monkeypatch.setattr(nwt_adapter, "extract_common_modflow_observables", common)

    got = ModflowNwtFlowAdapter().observables(
        solved_run(folder, solver_model=solver_model), [request("head")], time_index=None
    )

    assert got == {"id:head": "served"}
    assert seen == [(folder, "island", solver_model, ["id:head"], None)]


def test_far_point_warns(tmp_path: Path, caplog) -> None:
    solver_model = SimpleNamespace(mf=SimpleNamespace(modelgrid=_Grid()))

    with caplog.at_level(logging.WARNING, logger="hydromodpy"):
        located = ModflowNwtFlowAdapter().locate_cell(
            solved_run(tmp_path, solver_model=solver_model), 80.0, 5.0
        )

    assert located is None
    assert any("80.00" in record.getMessage() for record in caplog.records)


NO_GRID = [
    pytest.param(None, id="no solver object"),
    pytest.param(SimpleNamespace(), id="no grid"),
    pytest.param(SimpleNamespace(mf=SimpleNamespace(modelgrid=None)), id="no model grid"),
]


@pytest.mark.parametrize("solver_model", NO_GRID)
def test_no_grid_no_cell(tmp_path: Path, solver_model: Any) -> None:
    run = solved_run(tmp_path, solver_model=solver_model)

    assert ModflowNwtFlowAdapter().locate_cell(run, 1.0, 1.0) is None


def test_refuses_unserved_observable(tmp_path: Path, monkeypatch) -> None:
    unserved = request("stage")
    monkeypatch.setattr(
        nwt_adapter, "extract_common_modflow_observables", lambda *a, **k: ({}, [unserved])
    )
    run = solved_run(tmp_path / "island", solver_model=SimpleNamespace(model_name="island"))

    with pytest.raises(ObservableNotAvailableError, match="'stage'"):
        ModflowNwtFlowAdapter().observables(run, [unserved])


def test_refuses_no_solver_object(tmp_path: Path) -> None:
    run = solved_run(tmp_path / "island")

    with pytest.raises(ObservableNotAvailableError, match="'island'"):
        ModflowNwtFlowAdapter().observables(run, [request("head")])
