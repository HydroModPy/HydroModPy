"""The MODFLOW-NWT transport adapters, MT3DMS and MODPATH, answer the members of the contract.

A transport run follows a flow run. It builds beside the flow model, in the folder
the slot gives and under the name of the flow model, with the binaries of the slot.
It reads its setup and its upstream run on the run context until the transport port
takes the ``Model``. ``run`` writes the input files unless they are written, and a
solve that fails names the run by its slot.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.exceptions import SolverDivergedError
from hydromodpy.core.state.run_state import RunState
from hydromodpy.solver.base.adapter_protocol import RERUN_MEMBERS, solver_members
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SimulationPlan, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow_nwt.adapters import transport_modpath, transport_mt3dms
from tests.unit.solver.modflow_common.solver_runs import keep_all, solved_run

FLOW = ProcessRun(
    id="flow_main::modflow_nwt", process_id="flow_main", process_type="flow", solver="modflow_nwt"
)


class _Transport:
    """Stands for ``Mt3dms`` and ``Modpath``: records how it is built and driven."""

    instances: list[_Transport] = []
    success = True

    def __init__(self, domain, transport, flow_model, **kwargs: Any) -> None:
        self.args = (domain, transport, flow_model)
        self.kwargs = kwargs
        self.full_path = str(Path(kwargs["model_folder"]) / kwargs["model_name"])
        self.calls: list[tuple] = []
        type(self).instances.append(self)

    def pre_processing(self) -> None:
        self.calls.append(("pre",))

    def processing(self, **kwargs: Any) -> bool:
        self.calls.append(("run", kwargs))
        return type(self).success


ADAPTERS = {
    "mt3dms": (transport_mt3dms.Mt3dmsTransportAdapter, transport_mt3dms, "Mt3dms"),
    "modpath": (transport_modpath.ModpathTransportAdapter, transport_modpath, "Modpath"),
}


@pytest.fixture(params=sorted(ADAPTERS))
def adapter(request, monkeypatch):
    """The adapter of one transport, with its solver class replaced by ``_Transport``."""
    adapter_cls, module, solver_class = ADAPTERS[request.param]
    _Transport.instances = []
    _Transport.success = True
    monkeypatch.setattr(module, solver_class, _Transport)
    return adapter_cls()


def _context(adapter, tmp_path: Path) -> RunContext:
    run = ProcessRun(
        id=f"transport_main::{adapter.name}",
        process_id="transport_main",
        process_type="transport",
        solver=adapter.name,
        depends_on=(FLOW.id,),
    )
    plan = SimulationPlan(name="demo", description="demo", runs=(FLOW, run))
    flow_model = SimpleNamespace(model_name="island", full_path=str(tmp_path / "island"))
    upstream = solved_run(tmp_path / "island", solver_model=flow_model)
    setup = SimpleNamespace(domain="DOMAIN", transport="TRANSPORT")
    state = RunState(cfg=SimpleNamespace(), setup=setup)
    return RunContext(plan=plan, run=run, state=state, upstream=(upstream,))


def test_the_adapter_carries_the_members_of_the_contract(adapter) -> None:
    assert [name for name in solver_members() if not hasattr(adapter, name)] == []
    assert not any(hasattr(adapter, name) for name in RERUN_MEMBERS)
    assert not hasattr(adapter, "observables"), "a transport serves no calibration observable"
    assert adapter.mutable == frozenset()


def test_a_build_sits_beside_the_flow_model_in_the_folder_of_the_slot(
    adapter, tmp_path: Path
) -> None:
    slot = RunSlot(tmp_path, "island_t1", bin_dir=tmp_path / "bin")
    model = object()

    built = adapter.build(model, adapter.options(), slot, _context(adapter, tmp_path))

    (solver,) = _Transport.instances
    assert solver.args[:2] == ("DOMAIN", "TRANSPORT")
    assert solver.kwargs["model_folder"] == tmp_path
    assert solver.kwargs["model_name"] == "island", "the transport reads the files of its flow"
    assert solver.kwargs["bin_path"] == tmp_path / "bin"
    assert solver.calls == [("pre",)]
    assert built.solver_model is solver and built.model is model and built.slot is slot
    assert (built.written, built.solved, built.output_dir) == (False, False, None)


def test_a_run_writes_the_input_files_and_solves(adapter, tmp_path: Path) -> None:
    built = adapter.build(object(), None, RunSlot(tmp_path, "island"), _context(adapter, tmp_path))

    solved = adapter.run(built)

    (solver,) = _Transport.instances
    (_, options) = solver.calls[-1]
    assert options["write_model"] is True and options["run_model"] is True
    assert solved.output_dir == tmp_path / "island"
    assert (solved.written, solved.solved) == (True, True)
    assert solved.solver_model is solver


def test_a_run_whose_files_are_written_does_not_write_them_again(adapter, tmp_path: Path) -> None:
    from dataclasses import replace

    built = adapter.build(object(), None, RunSlot(tmp_path, "island"), _context(adapter, tmp_path))

    adapter.run(replace(built, written=True))

    assert _Transport.instances[0].calls[-1][1]["write_model"] is False


def test_a_failed_solve_names_the_transport_and_the_run_by_its_slot(
    adapter, tmp_path: Path
) -> None:
    built = adapter.build(
        object(), None, RunSlot(tmp_path, "island_t1"), _context(adapter, tmp_path)
    )
    _Transport.success = False

    with pytest.raises(SolverDivergedError) as raised:
        adapter.run(built)

    assert f"Transport solver '{adapter.name}' failed for run 'island_t1'" in str(raised.value)
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
    (folder / "island.nam").write_text("name")

    adapter.cleanup(solved_run(folder))
    adapter.cleanup(SolverRun(slot=RunSlot(tmp_path, "island")))

    assert not folder.exists()
