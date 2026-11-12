"""The MODFLOW 6 transport adapters, GWT and PRT, answer the members of the contract.

A transport run follows one flow run of its own family. Its ``build`` takes the
``Model`` of that flow, its options, the slot of the flow and the ``SolverRun``
of the flow, and reads nothing of the setup, the configuration or the run
store. It works in the folder the flow solved in, under the name of its model
plus the constant suffix of the transport. ``run`` writes the input files
unless they are written, and a solve that fails names the run by its slot. A
transport serves no calibration observable.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.exceptions import SolverDivergedError, SolverInputError
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow6 import prt, transport
from tests.unit.solver.modflow_common.solver_runs import keep_all, solved_run


class _Engine:
    """Stands for ``Modflow6Transport`` and ``Modflow6Prt``: records how it is built and driven."""

    instances: list[_Engine] = []
    success = True

    def __init__(self, model: Any, flow_model: Any, **kwargs: Any) -> None:
        self.args = (model, flow_model)
        self.kwargs = kwargs
        self.full_path = str(Path(kwargs["model_folder"]) / kwargs["model_name"])
        self.calls: list[tuple] = []
        _Engine.instances.append(self)

    def pre_processing(self) -> None:
        self.calls.append(("pre",))

    def processing(self, **kwargs: Any) -> bool:
        self.calls.append(("run", kwargs))
        return _Engine.success


ADAPTERS = {
    "gwt": (transport.Modflow6GwtTransportAdapter, transport, "Modflow6Transport", "_mt_s1"),
    "prt": (prt.Modflow6PrtTransportAdapter, prt, "Modflow6Prt", "_prt"),
}


@pytest.fixture(params=sorted(ADAPTERS))
def adapter(request, monkeypatch):
    """The adapter of one transport, with its engine class replaced by ``_Engine``."""
    adapter_cls, module, solver_class, _ = ADAPTERS[request.param]
    _Engine.instances = []
    _Engine.success = True
    monkeypatch.setattr(module, solver_class, _Engine)
    return adapter_cls()


def _upstream(tmp_path: Path) -> SolverRun:
    """The solved flow run a transport of this plan follows."""
    flow_model = SimpleNamespace(model_name="island", full_path=str(tmp_path / "island"))
    return solved_run(tmp_path / "island", model=object(), solver_model=flow_model)


def test_a_build_refuses_a_flow_run_without_its_solver_object(adapter, tmp_path: Path) -> None:
    stripped = replace(_upstream(tmp_path), solver_model=None)

    with pytest.raises(SolverInputError) as raised:
        adapter.build(object(), None, RunSlot(tmp_path, "island"), (stripped,))

    assert f"Transport '{adapter.name}' follows a flow run whose model is missing" in str(
        raised.value
    )


def test_a_run_writes_the_input_files_and_solves(adapter, tmp_path: Path) -> None:
    followed = _upstream(tmp_path)
    built = adapter.build(object(), None, followed.slot, (followed,))

    solved = adapter.run(built)

    (_, options) = built.solver_model.calls[-1]
    assert options["write_model"] is True and options["run_model"] is True
    assert solved.output_dir == tmp_path / "island"
    assert (solved.written, solved.solved) == (True, True)
    assert solved.solver_model is built.solver_model


def test_a_run_whose_files_are_written_does_not_write_them_again(adapter, tmp_path: Path) -> None:
    built = adapter.build(object(), None, RunSlot(tmp_path, "island"), (_upstream(tmp_path),))

    adapter.run(replace(built, written=True))

    assert built.solver_model.calls[-1][1]["write_model"] is False


def test_a_failed_solve_names_the_transport_and_the_run_by_its_slot(
    adapter, tmp_path: Path
) -> None:
    followed = _upstream(tmp_path)
    built = adapter.build(object(), None, RunSlot(tmp_path, "island_t1"), (followed,))
    _Engine.success = False

    with pytest.raises(SolverDivergedError) as raised:
        adapter.run(built)

    assert f"solver '{adapter.name}' failed for run 'island_t1'" in str(raised.value)
    assert raised.value.run_id is None, "the runner puts the run id on it"


def test_an_extract_goes_through_the_extractor_registered_for_the_transport(
    adapter, tmp_path: Path, monkeypatch
) -> None:
    keys: list[tuple] = []
    calls: list[tuple] = []

    class _Extractor:
        def extract(self, solver_run, store, retention) -> None:
            calls.append((solver_run, store, retention))

    monkeypatch.setattr(extractors, "create", lambda *key, **_: keys.append(key) or _Extractor())
    solver_run, store = solved_run(tmp_path), object()

    adapter.extract(solver_run, store, keep_all)

    assert keys == [("transport", adapter.name)]
    assert calls == [(solver_run, store, keep_all)]


def test_a_cleanup_removes_the_folder_of_the_run_and_forgets_a_run_without_one(
    adapter, tmp_path: Path
) -> None:
    folder = tmp_path / "island"
    folder.mkdir()
    (folder / "mfsim.nam").write_text("name")

    adapter.cleanup(solved_run(folder))
    adapter.cleanup(SolverRun(slot=RunSlot(tmp_path, "island")))

    assert not folder.exists()
