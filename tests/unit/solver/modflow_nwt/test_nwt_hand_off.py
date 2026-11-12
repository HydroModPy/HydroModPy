"""The flow-transport link of MODFLOW-NWT is a fact of the slot hand-off.

A flow run reads no plan. The runner fills ``slot.hand_off`` with the reads of
the runs that follow the flow, and the NWT adapter turns ``face_flow`` into
the LMT package, built with the run. Nine cases, none of which runs a binary:
build on a stand-in ``ModflowNwt``, and ``processing`` on a loose self.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.modflow_common.options import ModflowRunOptions
from hydromodpy.solver.modflow_nwt import adapter as nwt_adapter
from hydromodpy.solver.modflow_nwt.adapter import ModflowNwtFlowAdapter
from tests._helpers.model_factory import make_model


@dataclass
class _FakeNwt:
    """Stands for ``ModflowNwt``: records the link and skips the model build."""

    model_folder: Path
    model_name: str
    bin_path: object = None
    modflow_config: object = None
    instances: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.link_mt3dms = False
        self.input_files: tuple[str, ...] = ()
        self.last_flow_solve_time_seconds = None
        self.full_path = Path(self.model_folder) / self.model_name
        type(self).instances = [*type(self).instances, self]

    def pre_processing(self, model=None, options=None, *, slot=None) -> None:
        self.pre_process_model = model


@pytest.fixture(autouse=True)
def _stand_in_engine(monkeypatch: pytest.MonkeyPatch) -> list[_FakeNwt]:
    """Replace ``ModflowNwt`` in the adapter module, and return the instances seen."""
    _FakeNwt.instances = []
    monkeypatch.setattr(nwt_adapter, "ModflowNwt", _FakeNwt)
    return _FakeNwt.instances


def _slot(path: Path, hand_off: frozenset[str]) -> RunSlot:
    return RunSlot(path, "island", bin_dir=path / "bin", hand_off=hand_off)


def _build(path: Path, hand_off: frozenset[str]) -> SolverRun:
    return ModflowNwtFlowAdapter().build(make_model(), None, _slot(path, hand_off))


def test_a_flow_run_fills_nothing_from_its_upstream(tmp_path: Path) -> None:
    built = _build(tmp_path, frozenset({"face_flow"}))

    assert built.solver_model.model_name == "island"
    assert (built.written, built.solved, built.output_dir) == (False, False, None)


# residenced by the fake engine: the run member of the adapter writes the
# deck and solves; with write_model asked and run_model refused, the run
# keeps the build state.
@dataclass
class _SolvedStandIn:
    processing_calls: list[ModflowRunOptions] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.link_mt3dms = False
        self.full_path = None
        self.last_flow_solve_time_seconds = None

    def processing(self, options: ModflowRunOptions) -> bool:
        self.processing_calls.append(options)
        return True


def test_the_solve_time_of_nwt_is_solve_s_of_the_run_and_no_metric(tmp_path: Path) -> None:
    solver_model = _SolvedStandIn()
    solver_model.full_path = tmp_path / "island"
    solver_model.last_flow_solve_time_seconds = 2.25
    run = SolverRun(
        slot=RunSlot(tmp_path, "island"), solver_model=solver_model, written=True, model=None
    )

    solved = ModflowNwtFlowAdapter().run(run)

    assert solved.solve_s == 2.25
    assert "flow_solve_time_seconds" not in solved.metrics


def _lmt_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        lmt=SimpleNamespace(
            output_file_name="mt3d_link", extension="ftl", output_format="unformatted"
        )
    )


def _processing_self(link_mt3dms: bool) -> SimpleNamespace:
    return SimpleNamespace(
        mf=SimpleNamespace(namefile="island.nam", packagelist=()),
        _params=SimpleNamespace(runtime=_lmt_runtime()),
        flow_regime="steady",
        inputs=None,
        nper=2,
        link_mt3dms=link_mt3dms,
        last_flow_solve_time_seconds=None,
    )


def test_processing_builds_the_lmt_package_only_when_the_run_links_mt3dms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hydromodpy.solver.modflow_nwt.nwt import nwt_solver

    calls: list[dict[str, object]] = []

    class _FakeLmt:
        def __init__(self, model, **kwargs: object) -> None:
            model.packagelist = [*model.packagelist, self]
            calls.append(kwargs)

    monkeypatch.setattr("flopy.modflow.ModflowLmt", _FakeLmt)

    linked = _processing_self(link_mt3dms=True)
    nwt_solver.ModflowNwt.processing(
        linked, ModflowRunOptions(run_model=False, write_model=False, link_mt3dms=True)
    )
    standalone = _processing_self(link_mt3dms=False)
    nwt_solver.ModflowNwt.processing(
        standalone, ModflowRunOptions(run_model=False, write_model=False, link_mt3dms=False)
    )

    assert len(calls) == 1
