"""The MODFLOW-NWT transport adapters, MT3DMS and MODPATH, answer the members of the contract.

A transport run follows one flow run of its own family. Its ``build`` takes the
``Model`` of that flow, its options, the slot of the flow and the ``SolverRun``
of the flow, and reads nothing of the setup, the configuration or the run
store. It works in the folder the flow solved in, under the name of its model.
``run`` writes the input files unless they are written, and a solve that fails
names the run by its slot. A transport serves no calibration observable.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.exceptions import SolverDivergedError, SolverInputError
from hydromodpy.solver.base.adapter_protocol import RERUN_MEMBERS, solver_members
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow_nwt.modpath import modpath
from hydromodpy.solver.modflow_nwt.mt3dms import mt3dms
from tests.unit.solver.modflow_common.solver_runs import keep_all, solved_run


class _Transport:
    """Stands for ``Mt3dms`` and ``Modpath``: records how it is built and driven."""

    instances: list[_Transport] = []
    success = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.model_folder = kwargs.get("model_folder")
        self.model_name = kwargs.get("model_name")
        self.full_path = str(Path(kwargs["model_folder"]) / kwargs["model_name"])
        self.calls: list[tuple] = []
        type(self).instances.append(self)

    def pre_processing(self) -> None:
        self.calls.append(("pre",))

    def processing(self, **kwargs: Any) -> bool:
        self.calls.append(("run", kwargs))
        return type(self).success


ADAPTERS = {
    "mt3dms": (mt3dms.Mt3dmsTransportAdapter, mt3dms, "Mt3dms"),
    "modpath": (modpath.ModpathTransportAdapter, modpath, "Modpath"),
}


@pytest.fixture(params=sorted(ADAPTERS))
def adapter(request, monkeypatch):
    """The adapter of one transport, with its solver class replaced by ``_Transport``."""
    adapter_cls, module, solver_class = ADAPTERS[request.param]
    _Transport.instances = []
    _Transport.success = True
    monkeypatch.setattr(module, solver_class, _Transport)
    return adapter_cls()


def _upstream(tmp_path: Path, model: Any = None) -> SolverRun:
    """The solved flow run a transport of this plan follows."""
    flow_model = SimpleNamespace(
        model_name="island",
        full_path=str(tmp_path / "island"),
        solver_mesh=SimpleNamespace(nrow=10, ncol=10),
    )
    return solved_run(tmp_path / "island", model=model, solver_model=flow_model)


def _model() -> Any:
    return SimpleNamespace(geometry=SimpleNamespace(domain="DOMAIN", geographic="GEOGRAPHIC"))


def test_the_adapter_carries_the_members_of_the_contract(adapter) -> None:
    assert [name for name in solver_members() if not hasattr(adapter, name)] == []
    assert not any(hasattr(adapter, name) for name in RERUN_MEMBERS)
    assert not hasattr(adapter, "observables"), "a transport serves no calibration observable"
    assert not hasattr(adapter, "extract_observables") and not hasattr(adapter, "execute")
    assert adapter.mutable == frozenset()


def test_a_build_sits_beside_the_flow_model_in_the_folder_of_the_slot(
    adapter, tmp_path: Path
) -> None:
    slot = RunSlot(tmp_path, "island_t1", bin_dir=tmp_path / "bin")
    model = _model()
    followed = _upstream(tmp_path, model=model)

    built = adapter.build(model, adapter.options(), slot, (followed,))

    (solver,) = _Transport.instances
    assert solver.kwargs["model_folder"] == str(tmp_path)
    assert solver.kwargs["model_name"] == "island", "the transport reads the files of its flow"
    assert solver.kwargs["bin_path"] == tmp_path / "bin"
    assert built.solver_model is solver and built.model is model
    assert built.options is not None
    assert (built.written, built.solved) == (False, False)
    if adapter.name == "mt3dms":
        assert solver.kwargs["domain"] == "DOMAIN"


def test_a_build_forwards_options_parameters_to_the_engine(adapter, tmp_path: Path) -> None:
    slot = RunSlot(tmp_path, "island_t1", bin_dir=tmp_path / "bin")
    model = _model()
    followed = _upstream(tmp_path, model=model)
    options = adapter.options()

    adapter.build(model, options, slot, (followed,))

    (solver,) = _Transport.instances
    param_dict = solver.kwargs.get("params")
    assert isinstance(param_dict, dict)
    assert param_dict == options.model_dump()


def test_a_build_refuses_a_flow_run_without_its_solver_object(adapter, tmp_path: Path) -> None:
    stripped = replace(_upstream(tmp_path), solver_model=None)

    with pytest.raises(SolverInputError) as raised:
        adapter.build(_model(), None, RunSlot(tmp_path, "island"), (stripped,))

    assert f"Transport '{adapter.name}' follows a flow run whose model is missing" in str(
        raised.value
    )


def test_a_run_writes_the_input_files_and_solves(adapter, tmp_path: Path) -> None:
    followed = _upstream(tmp_path)
    built = adapter.build(_model(), None, followed.slot, (followed,))

    solved = adapter.run(built)

    (solver,) = _Transport.instances
    (_, options) = solver.calls[-1]
    assert options["write_model"] is True and options["run_model"] is True
    assert solved.output_dir == tmp_path / "island"
    assert (solved.written, solved.solved) == (True, True)
    assert solved.solver_model is solver


def test_a_run_whose_files_are_written_does_not_write_them_again(adapter, tmp_path: Path) -> None:
    built = adapter.build(_model(), None, RunSlot(tmp_path, "island"), (_upstream(tmp_path),))

    adapter.run(replace(built, written=True))

    assert _Transport.instances[0].calls[-1][1]["write_model"] is False


def test_a_failed_solve_names_the_transport_and_the_run_by_its_slot(
    adapter, tmp_path: Path
) -> None:
    followed = _upstream(tmp_path)
    built = adapter.build(_model(), None, RunSlot(tmp_path, "island_t1"), (followed,))
    _Transport.success = False

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
    (folder / "island.nam").write_text("name")

    adapter.cleanup(solved_run(folder))
    adapter.cleanup(SolverRun(slot=RunSlot(tmp_path, "island")))

    assert not folder.exists()
