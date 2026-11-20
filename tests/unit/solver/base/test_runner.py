"""The runner of a plan: the slot of each run, one solve through the contract, the refusals.

A plan holds runs. Each flow run gets a scratch slot named from the run id, a
trial asks for its own name, and a transport run follows exactly one flow run of
the family its backend requires. The backends here are fakes registered in an
isolated ``solvers`` registry under the names the shipped backends carry.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from hydromodpy.core.exceptions import (
    ConfigError,
    PipelineError,
    SolverDivergedError,
    SolverInputError,
)
from hydromodpy.core.runtime.interrupts import StopRequested
from hydromodpy.core.state.layout import stop_flag_for
from hydromodpy.core.state.run_state import SlotRequest
from hydromodpy.solver.base.plan import ProcessRun, RunSlot, SimulationPlan, SolverRun
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.base.runner import (
    ProcessCallbacks,
    SimulationRunner,
    hand_off_of,
    options_for,
    run_name,
    slot_for,
    solve_one,
)
from tests._helpers.fake_solvers import FakeAdapter, fake_adapter
from tests._helpers.model_factory import make_model

FLOW = ProcessRun(
    id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
)
NWT_FLOW = ProcessRun(
    id="flow_main::modflow_nwt",
    process_id="flow_main",
    process_type="flow",
    solver="modflow_nwt",
)
SECOND_FLOW = ProcessRun(
    id="flow_second::modflow6", process_id="flow_second", process_type="flow", solver="modflow6"
)
MT3DMS = ProcessRun(
    id="transport_main::mt3dms",
    process_id="transport_main",
    process_type="transport",
    solver="mt3dms",
    depends_on=(NWT_FLOW.id,),
)
MODPATH = ProcessRun(
    id="transport_main::modpath",
    process_id="transport_main",
    process_type="transport",
    solver="modpath",
    depends_on=(FLOW.id,),
)
MODEL = make_model()


def plan_of(*runs: ProcessRun) -> SimulationPlan:
    return SimulationPlan(name="demo", description="demo", runs=runs)


def state_with(**setup: Any) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=None,
        setup=SimpleNamespace(**setup),
        execution=SimpleNamespace(solver_runs={}),
        sim_id=None,
    )


def use_adapter(monkeypatch, adapter: FakeAdapter) -> None:
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)


class FailingAdapter(FakeAdapter):
    def build(self, model, options, slot, upstream=()):
        raise RuntimeError("solver failed")


class RecordingAdapter(FakeAdapter):
    """Records each call with what it received."""

    def __init__(self) -> None:
        super().__init__()
        self.received: list[tuple[str, tuple[Any, ...]]] = []

    def validate(self, model, options, slot):
        super().validate(model, options, slot)
        self.received.append(("validate", (model, options, slot)))

    def build(self, model, options, slot, upstream=()):
        self.received.append(("build", (model, options, slot, upstream)))
        return super().build(model, options, slot, upstream)


class MutableAdapter(FakeAdapter):
    """A backend that reruns K and Sy, and declines when it is told to."""

    mutable: ClassVar[frozenset[str]] = frozenset({"K", "Sy"})

    def __init__(self, declines: bool = False) -> None:
        super().__init__()
        self.declines = declines

    def rerun(self, previous, model, slot):
        self.calls.append("rerun")
        if self.declines:
            return None
        return replace(previous, model=model, slot=slot, solved=False)


class DivergingAdapter(FakeAdapter):
    def __init__(self, run_id: str | None) -> None:
        super().__init__()
        self.run_id = run_id

    def run(self, solver_run):
        raise SolverDivergedError(
            f"Flow solver failed for run '{solver_run.slot.name}'.", run_id=self.run_id
        )


def test_after_process_runs_on_failure(monkeypatch) -> None:
    use_adapter(monkeypatch, FailingAdapter())
    events: list[str] = []
    plan = plan_of(
        ProcessRun(
            id="custom_main::broken",
            process_id="custom_main",
            process_type="custom",
            solver="broken",
        )
    )
    runner = SimulationRunner(
        callbacks=ProcessCallbacks(
            before_process=lambda name: events.append(f"before:{name}"),
            after_process=lambda name: events.append(f"after:{name}"),
        )
    )

    with pytest.raises(RuntimeError, match="solver failed"):
        runner.execute(plan, state_with())

    assert events == ["before:custom", "after:custom"]


def test_failing_after_process_does_not_hide_the_solver_error(monkeypatch, hmp_log_records) -> None:
    use_adapter(monkeypatch, FailingAdapter())

    def broken_after(name: str) -> None:
        raise OSError("callback broke")

    plan = plan_of(replace(FLOW, process_type="custom", solver="broken"))
    runner = SimulationRunner(callbacks=ProcessCallbacks(after_process=broken_after))

    with pytest.raises(RuntimeError, match="solver failed"):
        runner.execute(plan, state_with())

    warned = [r.getMessage() for r in hmp_log_records if r.levelname == "WARNING"]
    assert "after_process callback failed while unwinding process custom" in warned


def test_mesh_process_needs_no_adapter(monkeypatch) -> None:
    def no_adapter(process_type, solver_name):
        raise AssertionError("mesh process should not request a solver adapter")

    monkeypatch.setattr(solvers, "create", no_adapter)
    state = state_with(workspace=None, settings=None, geographic=None, domain=None)
    state.setup.mesh_summary = {"output_mesh": "mesh.msh", "n_cells": 12}
    plan = plan_of(
        ProcessRun(
            id="mesh_main::catchment",
            process_id="mesh_main",
            process_type="mesh",
            solver="catchment",
            backend="catchment",
        )
    )

    SimulationRunner().execute(plan, state)

    # A mesh run materializes a mesh, not a model: its run carries no solver
    # model, and what it built is execution metadata.
    run = state.execution.solver_runs["mesh_main::catchment"]
    assert run.solver_model is None
    assert run.metrics == {
        "backend": "catchment",
        "summary": {"output_mesh": "mesh.msh", "n_cells": 12},
    }


def test_mesh_backend_must_be_catchment() -> None:
    plan = plan_of(
        ProcessRun(
            id="mesh_main::other",
            process_id="mesh_main",
            process_type="mesh",
            solver="other",
            backend="other",
        )
    )

    with pytest.raises(ConfigError, match="Unsupported mesh process backend: 'other'"):
        SimulationRunner().execute(plan, state_with())


def test_flow_run_needs_a_model(monkeypatch) -> None:
    # The runner refuses a flow run without ``setup.model`` before the adapter is called.
    adapter = RecordingAdapter()
    use_adapter(monkeypatch, adapter)

    for setup in ({}, {"model": None}):
        with pytest.raises(ConfigError, match="prepare_solver"):
            SimulationRunner().execute(plan_of(FLOW), state_with(**setup))

    assert adapter.calls == []


NAMES = [
    pytest.param((FLOW,), FLOW, {"run_id": "island"}, "island", id="one flow"),
    pytest.param(
        (FLOW, SECOND_FLOW), FLOW, {"run_id": "island"}, "island_f1", id="first of two flows"
    ),
    pytest.param(
        (FLOW, SECOND_FLOW),
        SECOND_FLOW,
        {"run_id": "island"},
        "island_f2",
        id="second of two flows",
    ),
    pytest.param(
        (FLOW,),
        FLOW,
        {"run_id": "island", "slot_request": SlotRequest(name=" island_trial000003 ")},
        "island_trial000003",
        id="name a trial asks for",
    ),
    pytest.param(
        (FLOW, SECOND_FLOW),
        SECOND_FLOW,
        {"run_id": "island", "slot_request": SlotRequest(name="island_trial000003")},
        "island_trial000003_f2",
        id="trial name with two flows",
    ),
    pytest.param(
        (FLOW,),
        FLOW,
        {"run_id": "island", "slot_request": SlotRequest(name="  ")},
        "island",
        id="blank trial name",
    ),
    pytest.param((FLOW,), FLOW, {"run_id": "  "}, "default", id="no run id"),
    pytest.param((FLOW,), FLOW, {}, "default", id="no setup name at all"),
    pytest.param(
        (FLOW,),
        FLOW,
        {"run_id": "Example 12 launcher"},
        "Example 12 launcher",
        id="spaces, which NWT makes safe on its side",
    ),
]


@pytest.mark.parametrize(("runs", "run", "setup", "expected"), NAMES)
def test_run_name(runs, run, setup, expected, tmp_path: Path) -> None:
    workspace = SimpleNamespace(solver_scratch_folder=tmp_path / "scratch", bin_path=None)

    slot = slot_for(plan_of(*runs), run, SimpleNamespace(workspace=workspace, **setup))

    assert slot.name == expected
    assert slot.directory == tmp_path / "scratch" / expected


def ask_for_a_stop(run_dir: Path) -> None:
    flag = stop_flag_for(run_dir)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text('{"schema": "hydromodpy.stop.v1", "at": "2026-11-10T10:00:00+00:00"}')


def test_stop_ends_the_plan(monkeypatch, tmp_path: Path) -> None:
    adapter = FakeAdapter()
    use_adapter(monkeypatch, adapter)
    state = state_with(model=object())
    state.run_dir = tmp_path
    events: list[str] = []
    runner = SimulationRunner(
        callbacks=ProcessCallbacks(
            after_process=lambda name: events.append(f"after:{name}"),
            after_run=lambda run, result, state: ask_for_a_stop(tmp_path),
        )
    )

    with pytest.raises(StopRequested, match="stop requested at 2026-11-10T10:00:00"):
        runner.execute(plan_of(FLOW, SECOND_FLOW), state)

    assert adapter.calls == ["validate", "build", "run"]
    assert list(state.execution.solver_runs) == [FLOW.id]
    assert events == ["after:flow"]


def test_stop_before_start(monkeypatch, tmp_path: Path) -> None:
    adapter = FakeAdapter()
    use_adapter(monkeypatch, adapter)
    state = state_with(model=object())
    state.run_dir = tmp_path
    ask_for_a_stop(tmp_path)

    with pytest.raises(StopRequested):
        SimulationRunner().execute(plan_of(FLOW), state)

    assert adapter.calls == []


class TransportAdapter(FakeAdapter):
    process_type: ClassVar[str] = "transport"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset()
    options: ClassVar[type | None] = object
    requires: ClassVar[tuple[tuple[str, str], ...]] = (("flow", "modflow6"),)


class OptionsAdapter(FakeAdapter):
    options: ClassVar[type | None] = object


OPTIONS = [
    pytest.param(OptionsAdapter(), FLOW, "table of modflow6", id="flow with settings"),
    pytest.param(FakeAdapter(), FLOW, None, id="flow without settings"),
    pytest.param(TransportAdapter(), MODPATH, "params of modpath", id="transport with its table"),
    pytest.param(FakeAdapter(), MODPATH, None, id="transport without settings"),
]


@pytest.mark.parametrize(("adapter", "run", "expected"), OPTIONS)
def test_options_for(adapter, run: ProcessRun, expected: str | None) -> None:
    cfg = SimpleNamespace(
        solver=SimpleNamespace(options_of=lambda name: f"table of {name}"),
        transport=SimpleNamespace(options_of=lambda name: f"params of {name}"),
    )

    assert options_for(adapter, run, cfg) == expected


def test_no_table_no_options() -> None:
    run = ProcessRun(
        id="custom_main::broken", process_id="custom_main", process_type="custom", solver="broken"
    )

    cfg = SimpleNamespace(solver=None, transport=None)

    assert options_for(OptionsAdapter(), run, cfg) is None


RERUNS = [
    pytest.param(
        MutableAdapter(),
        MODEL.with_properties(K=2e-5),
        ["validate", "rerun", "run"],
        id="K within mutable",
    ),
    pytest.param(
        MutableAdapter(),
        MODEL.with_properties(Ss=1e-5),
        ["validate", "build", "run"],
        id="Ss outside mutable",
    ),
    pytest.param(
        MutableAdapter(declines=True),
        MODEL.with_properties(K=2e-5),
        ["validate", "rerun", "build", "run"],
        id="backend declines",
    ),
    pytest.param(
        FakeAdapter(),
        MODEL.with_properties(K=2e-5),
        ["validate", "build", "run"],
        id="backend not mutable",
    ),
]


@pytest.mark.parametrize(("adapter", "model", "calls"), RERUNS)
def test_solve_one_rerun_choice(
    adapter: FakeAdapter, model: Any, calls: list[str], tmp_path: Path
) -> None:
    slot = RunSlot(tmp_path, "island")
    previous = SolverRun(slot=slot, model=MODEL, written=True, solved=True)

    result = solve_one(adapter, model, None, slot, (), previous=previous)

    assert adapter.calls == calls
    assert result.model is model
    assert result.solved


def test_previous_run_goes_to_its_own(monkeypatch) -> None:
    adapter = MutableAdapter()
    use_adapter(monkeypatch, adapter)
    model = MODEL.with_properties(K=2e-5)
    previous = SolverRun(
        slot=RunSlot(Path("old"), "island"), model=MODEL, written=True, solved=True
    )

    SimulationRunner().execute(plan_of(FLOW), state_with(model=model), previous={FLOW.id: previous})
    SimulationRunner().execute(plan_of(FLOW), state_with(model=model), previous={"other": previous})

    assert adapter.calls == ["validate", "rerun", "run", "validate", "build", "run"]


SOLVER_ERRORS = [
    pytest.param(None, FLOW.id, id="named by the runner"),
    pytest.param("flow_other::modflow6", "flow_other::modflow6", id="named by the backend"),
]


@pytest.mark.parametrize(("named", "expected"), SOLVER_ERRORS)
def test_error_names_its_run(monkeypatch, named: str | None, expected: str) -> None:
    # The message names the run by its slot. The runner fills an id the backend left.
    use_adapter(monkeypatch, DivergingAdapter(named))

    with pytest.raises(SolverDivergedError, match="for run 'default'") as caught:
        SimulationRunner().execute(plan_of(FLOW), state_with(model=object()))

    assert caught.value.run_id == expected


def register_backends(
    isolated_solvers: Any, *, trace: list[str], converged: bool | None = None
) -> None:
    """Register the fake flow and transports under the names the shipped backends carry."""

    def flow_build(self: FakeAdapter, model, options, slot, upstream=()):
        trace.append("flow")
        return SolverRun(
            slot=slot,
            model=model,
            solver_model=object(),
            initial_state_converged=converged,
        )

    def transport_build(self: FakeAdapter, model, options, slot, upstream=()):
        trace.append("transport")
        if not upstream:
            raise PipelineError("A fake transport received no flow to follow.")
        (followed,) = upstream
        return SolverRun(
            slot=slot,
            model=model,
            solver_model=object(),
            output_dir=followed.output_dir if followed.written else followed.slot.directory,
        )

    for name, process_type, extra in (
        ("modflow6", "flow", {}),
        ("modflow_nwt", "flow", {}),
        ("mt3dms", "transport", {"reads": ("face_flow",), "requires": (("flow", "modflow_nwt"),)}),
        ("modpath", "transport", {"reads": ("face_flow",), "requires": (("flow", "modflow6"),)}),
    ):
        build = transport_build if process_type == "transport" else flow_build
        isolated_solvers.solvers.register(
            fake_adapter(name, process_type, build=build, **extra), replace=True
        )


HAND_OFFS = [
    pytest.param((FLOW,), FLOW, frozenset(), id="a flow that no transport follows"),
    pytest.param(
        (NWT_FLOW, MT3DMS), NWT_FLOW, frozenset({"face_flow"}), id="a flow an MT3DMS follows"
    ),
    pytest.param((FLOW, MODPATH), FLOW, frozenset({"face_flow"}), id="a flow a MODPATH follows"),
    pytest.param(
        (NWT_FLOW, MT3DMS, replace(MT3DMS, id="transport_second::modpath", solver="modpath")),
        NWT_FLOW,
        frozenset({"face_flow"}),
        id="a flow two transports follow",
    ),
    pytest.param(
        (FLOW, replace(FLOW, id="flow_second::modflow6", process_id="flow_second")),
        FLOW,
        frozenset(),
        id="a flow a run of another family follows",
    ),
]


@pytest.mark.parametrize(("runs", "run", "expected"), HAND_OFFS)
def test_hand_off_is_the_reads_of_dependent_runs(
    isolated_solvers, runs: tuple[ProcessRun, ...], run: ProcessRun, expected: frozenset[str]
) -> None:
    register_backends(isolated_solvers, trace=[])

    assert hand_off_of(plan_of(*runs), run) == expected


STARTS = [
    pytest.param(True, False, id="converged"),
    pytest.param(None, False, id="no steady start"),
    pytest.param(True, True, id="sealed"),
]


@pytest.mark.parametrize(("converged", "sealed"), STARTS)
def test_transport_after_a_start(isolated_solvers, converged, sealed) -> None:
    trace: list[str] = []
    register_backends(isolated_solvers, trace=trace, converged=converged)
    state = state_with(model=object())
    state.cfg = SimpleNamespace(read_as_sealed=sealed)

    SimulationRunner().execute(plan_of(FLOW, MODPATH), state)

    assert trace == ["flow", "transport"]


def test_transport_refused_after_unconverged_start(isolated_solvers) -> None:
    trace: list[str] = []
    register_backends(isolated_solvers, trace=trace, converged=False)
    state = state_with(model=object())
    state.cfg = SimpleNamespace(read_as_sealed=False)

    with pytest.raises(SolverDivergedError, match="did not converge") as caught:
        SimulationRunner().execute(plan_of(FLOW, MODPATH), state)

    assert caught.value.run_id == MODPATH.id
    assert trace == ["flow"]


def test_transport_warns_when_sealed(isolated_solvers) -> None:
    trace: list[str] = []
    register_backends(isolated_solvers, trace=trace, converged=False)
    state = state_with(model=object())
    state.cfg = SimpleNamespace(read_as_sealed=True)

    with pytest.warns(RuntimeWarning, match="did not converge"):
        SimulationRunner().execute(plan_of(FLOW, MODPATH), state)

    assert trace == ["flow", "transport"]


def test_unconverged_start_not_remembered(isolated_solvers) -> None:
    # The refusal is read off the runs of this execution, not remembered across them.
    trace: list[str] = []
    register_backends(isolated_solvers, trace=trace, converged=False)
    runner = SimulationRunner()
    with pytest.raises(SolverDivergedError):
        runner.execute(plan_of(FLOW, MODPATH), state_with(model=object()))

    trace.clear()
    register_backends(isolated_solvers, trace=trace, converged=True)

    runner.execute(plan_of(FLOW, MODPATH), state_with(model=object()))

    assert trace == ["flow", "transport"]


def test_transport_follows_required_family(isolated_solvers) -> None:
    # MT3DMS follows the flow MODFLOW 6 solves. Hand it NWT's run and the runner refuses it.
    trace: list[str] = []
    register_backends(isolated_solvers, trace=trace)

    def mt3dms_build(self: FakeAdapter, model, options, slot, upstream=()):
        trace.append("cross")
        return SolverRun(slot=slot, model=model, solver_model=object())

    cross_backend = fake_adapter(
        "mt3dms",
        "transport",
        build=mt3dms_build,
        reads=("face_flow",),
        requires=(("flow", "modflow6"),),
    )
    isolated_solvers.solvers.register(cross_backend, replace=True)
    cross = replace(MT3DMS, depends_on=(NWT_FLOW.id,))

    with pytest.raises(SolverInputError, match="follows the \\(flow, modflow6\\) flow"):
        SimulationRunner().execute(plan_of(NWT_FLOW, cross), state_with(model=object()))

    assert trace == ["flow"]


FLOWS_WITHOUT_A_MODEL = [
    pytest.param({}, id="flow has not run"),
    pytest.param({FLOW.id: {"solver_model": None}}, id="flow produced no model"),
]


@pytest.mark.parametrize("recorded", FLOWS_WITHOUT_A_MODEL)
def test_transport_needs_flow_model(isolated_solvers, recorded: dict[str, Any]) -> None:
    trace: list[str] = []
    register_backends(isolated_solvers, trace=trace)
    state = state_with(model=object())
    state.execution.solver_runs.update(
        {
            run_id: SolverRun(slot=RunSlot(Path("."), "x"), **members)
            for run_id, members in recorded.items()
        }
    )

    with pytest.raises(PipelineError, match="has produced no model") as caught:
        SimulationRunner().execute(plan_of(MODPATH), state)

    assert caught.value.run_id == MODPATH.id
    assert trace == []


def test_transport_without_a_flow_dependency_is_refused(isolated_solvers) -> None:
    trace: list[str] = []
    register_backends(isolated_solvers, trace=trace)
    orphan = replace(MODPATH, depends_on=())

    with pytest.raises(SolverInputError, match="expected exactly one flow dependency, got 0"):
        SimulationRunner().execute(plan_of(FLOW, orphan), state_with(model=object()))

    assert trace == ["flow"]


def test_transport_slot_needs_flow() -> None:
    with pytest.raises(SolverInputError, match="expected exactly one flow dependency, got 0"):
        slot_for(plan_of(NWT_FLOW, MT3DMS), MT3DMS, SimpleNamespace())


def test_run_outside_plan_refused() -> None:
    with pytest.raises(SolverInputError, match="not present in the provided simulation plan"):
        run_name(plan_of(FLOW, SECOND_FLOW), replace(SECOND_FLOW, id="flow_other::modflow6"), "x")
