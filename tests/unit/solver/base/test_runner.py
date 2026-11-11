"""The runner of a plan: the slot of each run, one solve through the contract, the refusals."""

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
from hydromodpy.core.state.run_state import RunState, SlotRequest
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SimulationPlan, SolverRun
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


def _plan(*runs: ProcessRun) -> SimulationPlan:
    return SimulationPlan(name="demo", description="demo", runs=runs)


def _state(**setup: Any) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=None,
        setup=SimpleNamespace(**setup),
        execution=SimpleNamespace(solver_runs={}),
        sim_id=None,
    )


def _workspace(tmp_path: Path, bin_path: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(solver_scratch_folder=tmp_path / "scratch", bin_path=bin_path)


class _FailingAdapter(FakeAdapter):
    def build(self, model, options, slot, upstream=()):
        raise RuntimeError("solver failed")


def test_after_process_runs_when_process_run_fails(monkeypatch) -> None:
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: _FailingAdapter())

    events: list[str] = []
    plan = _plan(
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
        runner.execute(plan, _state())

    assert events == ["before:custom", "after:custom"]


class _RecordingAdapter(FakeAdapter):
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


def test_a_flow_run_needs_the_model_that_prepare_solver_builds(monkeypatch) -> None:
    """The runner refuses a flow run without ``setup.model`` before the adapter is called."""
    adapter = _RecordingAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)

    for setup in ({}, {"model": None}):
        with pytest.raises(ConfigError, match="prepare_solver"):
            SimulationRunner().execute(_plan(FLOW), _state(**setup))

    assert adapter.calls == []


def test_a_flow_run_hands_the_adapter_its_model_and_nothing_of_the_run(monkeypatch) -> None:
    adapter = _RecordingAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    model = object()
    state = _state(model=model, flow=None)

    SimulationRunner().execute(_plan(FLOW), state)

    name, (built_model, options, slot, upstream) = adapter.received[-1]
    assert name == "build"
    assert built_model is model
    assert options is None
    assert isinstance(slot, RunSlot)
    assert upstream == ()
    assert slot.hand_off == frozenset()
    assert state.setup.flow is None


def test_validate_build_and_run_are_called_in_this_order(monkeypatch) -> None:
    adapter = FakeAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    state = _state(model=object())

    ((_, result),) = SimulationRunner().execute(_plan(FLOW), state)

    assert adapter.calls == ["validate", "build", "run"]
    assert result.solved and result.written
    assert state.execution.solver_runs == {FLOW.id: result}


def test_a_slot_that_stops_before_the_solve_skips_run(monkeypatch) -> None:
    adapter = FakeAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    state = _state(model=object(), slot_request=SlotRequest(stop_before_solve=True))

    ((_, result),) = SimulationRunner().execute(_plan(FLOW), state)

    assert adapter.calls == ["validate", "build"]
    assert (result.written, result.solved) == (False, False)
    assert state.execution.solver_runs[FLOW.id] is result


NAMES: tuple[tuple[str, tuple[ProcessRun, ...], ProcessRun, dict[str, Any], str], ...] = (
    ("one flow", (FLOW,), FLOW, {"run_id": "island"}, "island"),
    ("first of two flows", (FLOW, SECOND_FLOW), FLOW, {"run_id": "island"}, "island_f1"),
    ("second of two flows", (FLOW, SECOND_FLOW), SECOND_FLOW, {"run_id": "island"}, "island_f2"),
    (
        "the name a trial asks for",
        (FLOW,),
        FLOW,
        {"run_id": "island", "slot_request": SlotRequest(name=" island_trial000003 ")},
        "island_trial000003",
    ),
    (
        "a trial name with two flows",
        (FLOW, SECOND_FLOW),
        SECOND_FLOW,
        {"run_id": "island", "slot_request": SlotRequest(name="island_trial000003")},
        "island_trial000003_f2",
    ),
    (
        "a blank trial name",
        (FLOW,),
        FLOW,
        {"run_id": "island", "slot_request": SlotRequest(name="  ")},
        "island",
    ),
    ("no run id", (FLOW,), FLOW, {"run_id": "  "}, "default"),
    ("no setup name at all", (FLOW,), FLOW, {}, "default"),
    (
        "a name with spaces, which NWT makes safe on its side",
        (FLOW,),
        FLOW,
        {"run_id": "Example 12 launcher"},
        "Example 12 launcher",
    ),
)


@pytest.mark.parametrize(
    ("case", "runs", "run", "setup", "expected"), NAMES, ids=[c for c, *_ in NAMES]
)
def test_the_run_name(
    case: str,
    runs: tuple[ProcessRun, ...],
    run: ProcessRun,
    setup: dict[str, Any],
    expected: str,
    tmp_path: Path,
) -> None:
    del case
    slot = slot_for(_plan(*runs), run, SimpleNamespace(workspace=_workspace(tmp_path), **setup))

    assert slot.name == expected
    assert slot.directory == tmp_path / "scratch" / expected


def test_a_run_outside_its_plan_has_no_name_among_several() -> None:
    with pytest.raises(SolverInputError, match="not present in the provided simulation plan"):
        run_name(_plan(FLOW, SECOND_FLOW), replace(SECOND_FLOW, id="flow_other::modflow6"), "x")


def test_the_slot_reads_the_folder_and_the_binaries_on_the_workspace(tmp_path: Path) -> None:
    shared = tmp_path / "scratch" / "_shared_recharge"
    setup = SimpleNamespace(
        workspace=_workspace(tmp_path, bin_path=str(tmp_path / "bin")),
        run_id="island",
        slot_request=SlotRequest(name="trial", shared_forcing_dir=shared),
    )

    slot = slot_for(_plan(FLOW), FLOW, setup)

    assert slot.folder == tmp_path / "scratch"
    assert slot.bin_dir == tmp_path / "bin"
    assert slot.shared_forcing_dir == shared
    assert slot.stop_before_solve is False


def test_a_slot_outside_a_trial_keeps_its_forcing_beside_the_model(tmp_path: Path) -> None:
    slot = slot_for(_plan(FLOW), FLOW, SimpleNamespace(workspace=_workspace(tmp_path)))

    assert (slot.shared_forcing_dir, slot.bin_dir, slot.stop_before_solve) == (None, None, False)
    assert slot.hand_off == frozenset()


MESH = ProcessRun(
    id="mesh_main::catchment", process_id="mesh_main", process_type="mesh", solver="catchment"
)
STOP_FLAGS: tuple[tuple[str, ProcessRun, Path | None, str | None], ...] = (
    ("a flow in a run folder", FLOW, Path("runs/island"), "runs/island/.hmp/stop.json"),
    ("a flow without a run folder, a trial", FLOW, None, None),
    ("a mesh run in a run folder", MESH, Path("runs/island"), "runs/island/.hmp/stop.json"),
)


@pytest.mark.parametrize(
    ("case", "run", "run_dir", "expected"), STOP_FLAGS, ids=[c for c, *_ in STOP_FLAGS]
)
def test_the_stop_flag_of_the_slot_is_that_of_the_run_folder(
    case: str, run: ProcessRun, run_dir: Path | None, expected: str | None, tmp_path: Path
) -> None:
    del case
    run_dir = None if run_dir is None else tmp_path / run_dir
    setup = SimpleNamespace(workspace=_workspace(tmp_path))

    slot = slot_for(_plan(run), run, setup, run_dir=run_dir)

    assert slot.stop_flag == (None if expected is None else tmp_path / expected)


def test_a_slot_asked_without_a_run_folder_has_no_stop_flag(tmp_path: Path) -> None:
    slot = slot_for(_plan(FLOW), FLOW, SimpleNamespace(workspace=_workspace(tmp_path)))

    assert slot.stop_flag is None


def test_the_slot_of_a_transport_reads_the_stop_flag_of_the_run_folder(tmp_path: Path) -> None:
    upstream = (SolverRun(slot=RunSlot(tmp_path / "scratch", "island")),)

    slot = slot_for(
        _plan(NWT_FLOW, MT3DMS), MT3DMS, SimpleNamespace(), upstream=upstream, run_dir=tmp_path
    )

    assert slot.stop_flag == stop_flag_for(tmp_path)


def _ask_for_a_stop(run_dir: Path) -> None:
    flag = stop_flag_for(run_dir)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text('{"schema": "hydromodpy.stop.v1", "at": "2026-11-10T10:00:00+00:00"}')


def test_a_stop_asked_during_a_run_ends_the_plan_before_the_next_run(
    monkeypatch, tmp_path: Path
) -> None:
    adapter = FakeAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    state = _state(model=object())
    state.run_dir = tmp_path
    events: list[str] = []
    runner = SimulationRunner(
        callbacks=ProcessCallbacks(
            after_process=lambda name: events.append(f"after:{name}"),
            after_run=lambda run, result, state: _ask_for_a_stop(tmp_path),
        )
    )

    with pytest.raises(StopRequested, match="stop requested at 2026-11-10T10:00:00"):
        runner.execute(_plan(FLOW, SECOND_FLOW), state)

    assert adapter.calls == ["validate", "build", "run"]
    assert list(state.execution.solver_runs) == [FLOW.id]
    assert events == ["after:flow"]


def test_a_stop_asked_before_the_plan_starts_no_run(monkeypatch, tmp_path: Path) -> None:
    adapter = FakeAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    state = _state(model=object())
    state.run_dir = tmp_path
    _ask_for_a_stop(tmp_path)

    with pytest.raises(StopRequested):
        SimulationRunner().execute(_plan(FLOW), state)

    assert adapter.calls == []


def test_a_run_without_a_folder_cannot_be_stopped_by_a_flag(monkeypatch, tmp_path: Path) -> None:
    adapter = FakeAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    _ask_for_a_stop(tmp_path)

    SimulationRunner().execute(_plan(FLOW), _state(model=object()))

    assert adapter.calls == ["validate", "build", "run"]


def test_a_setup_without_a_workspace_solves_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    slot = slot_for(_plan(FLOW), FLOW, SimpleNamespace(run_id="island"))

    assert slot.folder == tmp_path
    assert slot.bin_dir is None


def _register_hand_off_backends(isolated_solvers: object) -> None:
    """Register the fake flow and the two transports that read ``face_flow`` of it.

    The isolated registry is the object the runner reads through ``solvers``, so
    the names the table binds answer like the shipped backends do, without
    importing one.
    """

    def flow_build(self: FakeAdapter, model, options, slot, upstream=()):
        return SolverRun(slot=slot, model=model, solver_model=object())

    def transport_build(self: FakeAdapter, model, options, slot, upstream=()):
        (followed,) = upstream
        return SolverRun(
            slot=slot,
            model=model,
            solver_model=object(),
            output_dir=followed.output_dir,
        )

    for name, process_type, members in (
        ("modflow6", "flow", {"build": flow_build}),
        ("modflow_nwt", "flow", {"build": flow_build}),
        ("mt3dms", "transport", {"build": transport_build, "reads": ("face_flow",)}),
        ("modpath", "transport", {"build": transport_build, "reads": ("face_flow",)}),
    ):
        cls = fake_adapter(name, process_type, **members)
        isolated_solvers.solvers.register(cls, replace=True)


HAND_OFFS: tuple[tuple[str, tuple[ProcessRun, ...], ProcessRun, frozenset[str]], ...] = (
    ("a flow that no transport follows", (FLOW,), FLOW, frozenset()),
    ("a flow an MT3DMS follows", (NWT_FLOW, MT3DMS), NWT_FLOW, frozenset({"face_flow"})),
    ("a flow a MODPATH follows", (FLOW, MODPATH), FLOW, frozenset({"face_flow"})),
    (
        "a flow two transports follow",
        (NWT_FLOW, MT3DMS, replace(MT3DMS, id="transport_second::modpath", solver="modpath")),
        NWT_FLOW,
        frozenset({"face_flow"}),
    ),
    (
        "a flow a run of another family follows",
        (FLOW, replace(FLOW, id="flow_second::modflow6", process_id="flow_second")),
        FLOW,
        frozenset(),
    ),
)


@pytest.mark.parametrize(
    ("case", "runs", "run", "expected"), HAND_OFFS, ids=[c for c, *_ in HAND_OFFS]
)
def test_the_hand_off_is_the_reads_of_the_runs_that_depend_on_one(
    isolated_solvers,
    case: str,
    runs: tuple[ProcessRun, ...],
    run: ProcessRun,
    expected: frozenset[str],
) -> None:
    del case
    _register_hand_off_backends(isolated_solvers)

    assert hand_off_of(_plan(*runs), run) == expected


def test_the_hand_off_of_a_flow_without_a_transport_is_read_twice_the_same(
    isolated_solvers,
) -> None:
    """The reads are computed from the registry once and named once: no dependency, nothing."""
    _register_hand_off_backends(isolated_solvers)

    assert hand_off_of(_plan(FLOW), FLOW) == frozenset()
    assert hand_off_of(_plan(FLOW), FLOW) == frozenset()


def test_the_slot_of_a_transport_is_the_slot_of_its_flow(tmp_path: Path) -> None:
    flow_slot = RunSlot(tmp_path / "scratch", "island", bin_dir=tmp_path / "bin")
    upstream = (SolverRun(slot=flow_slot),)

    slot = slot_for(_plan(NWT_FLOW, MT3DMS), MT3DMS, SimpleNamespace(), upstream=upstream)

    assert (slot.folder, slot.name, slot.bin_dir) == (
        flow_slot.folder,
        flow_slot.name,
        flow_slot.bin_dir,
    )
    assert slot.stop_before_solve is False
    assert slot.hand_off == frozenset()


def test_the_slot_of_a_transport_keeps_its_own_stop_before_solve(tmp_path: Path) -> None:
    flow_slot = RunSlot(tmp_path / "scratch", "island")
    upstream = (SolverRun(slot=flow_slot),)

    slot = slot_for(
        _plan(NWT_FLOW, MT3DMS),
        MT3DMS,
        SimpleNamespace(slot_request=SlotRequest(stop_before_solve=True)),
        upstream=upstream,
    )

    assert slot.stop_before_solve is True
    assert flow_slot.stop_before_solve is False


def test_a_transport_without_its_flow_run_has_no_slot() -> None:
    with pytest.raises(SolverInputError, match="expected exactly one flow dependency, got 0"):
        slot_for(_plan(NWT_FLOW, MT3DMS), MT3DMS, SimpleNamespace())


class _TransportOptions(FakeAdapter):
    process_type: ClassVar[str] = "transport"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset()
    options: ClassVar[type | None] = object
    requires: ClassVar[tuple[tuple[str, str], ...]] = (("flow", "modflow6"),)


class _Options(FakeAdapter):
    options: ClassVar[type | None] = object


OPTIONS: tuple[tuple[str, object, ProcessRun, str | None], ...] = (
    ("a flow with settings", _Options(), FLOW, "table of modflow6"),
    ("a flow without settings", FakeAdapter(), FLOW, None),
    ("a transport with its table", _TransportOptions(), MODPATH, "params of modpath"),
    ("a transport without settings", FakeAdapter(), MODPATH, None),
)


@pytest.mark.parametrize(
    ("case", "adapter", "run", "expected"), OPTIONS, ids=[c for c, *_ in OPTIONS]
)
def test_options_for(case: str, adapter: object, run: ProcessRun, expected: str | None) -> None:
    del case
    cfg = SimpleNamespace(
        solver=SimpleNamespace(options_of=lambda name: f"table of {name}"),
        transport=SimpleNamespace(options_of=lambda name: f"params of {name}"),
    )

    assert options_for(adapter, run, cfg) == expected


def test_options_for_a_process_without_a_table_is_none() -> None:
    run = ProcessRun(
        id="custom_main::broken", process_id="custom_main", process_type="custom", solver="broken"
    )

    assert options_for(_Options(), run, SimpleNamespace(solver=None, transport=None)) is None


def _ctx(run: ProcessRun = FLOW) -> RunContext:
    return RunContext(plan=_plan(run), run=run, state=RunState())


def _slot(tmp_path: Path, *, stop: bool = False) -> RunSlot:
    return RunSlot(tmp_path, "island", stop_before_solve=stop)


class _Mutable(FakeAdapter):
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


MODEL = make_model()
RERUNS: tuple[tuple[str, FakeAdapter, Any, list[str]], ...] = (
    (
        "K within mutable",
        _Mutable(),
        MODEL.with_properties(K=2e-5),
        ["validate", "rerun", "run"],
    ),
    (
        "Ss outside mutable",
        _Mutable(),
        MODEL.with_properties(Ss=1e-5),
        ["validate", "build", "run"],
    ),
    (
        "the backend declines",
        _Mutable(declines=True),
        MODEL.with_properties(K=2e-5),
        ["validate", "rerun", "build", "run"],
    ),
    (
        "a backend that is not mutable",
        FakeAdapter(),
        MODEL.with_properties(K=2e-5),
        ["validate", "build", "run"],
    ),
)


@pytest.mark.parametrize(("case", "adapter", "model", "calls"), RERUNS, ids=[c for c, *_ in RERUNS])
def test_solve_one_reruns_only_when_the_change_fits_mutable(
    case: str, adapter: FakeAdapter, model: Any, calls: list[str], tmp_path: Path
) -> None:
    del case
    previous = SolverRun(slot=_slot(tmp_path), model=MODEL, written=True, solved=True)

    result = solve_one(adapter, model, None, _slot(tmp_path), (), previous=previous)

    assert adapter.calls == calls
    assert result.model is model
    assert result.solved


REUSED: tuple[tuple[str, Any, Any, bool, bool], ...] = (
    ("a rerun", lambda: _Mutable(), MODEL.with_properties(K=2e-5), False, True),
    ("a build outside mutable", lambda: _Mutable(), MODEL.with_properties(Ss=1e-5), False, False),
    (
        "a declined rerun",
        lambda: _Mutable(declines=True),
        MODEL.with_properties(K=2e-5),
        False,
        False,
    ),
    (
        "a rerun stopped before its solve",
        lambda: _Mutable(),
        MODEL.with_properties(K=2e-5),
        True,
        True,
    ),
)


@pytest.mark.parametrize(
    ("case", "adapter_of", "model", "stop", "reran"), REUSED, ids=[c for c, *_ in REUSED]
)
def test_solve_one_says_whether_the_run_came_from_rerun(
    case: str, adapter_of: Any, model: Any, stop: bool, reran: bool, tmp_path: Path
) -> None:
    """The run_solver step writes ``reused = "rerun"`` on the solve line of such a run."""
    del case
    previous = SolverRun(slot=_slot(tmp_path), model=MODEL, written=True, solved=True)

    result = solve_one(adapter_of(), model, None, _slot(tmp_path, stop=stop), (), previous=previous)

    assert result.reran is reran


def test_solve_one_without_a_previous_run_builds(tmp_path: Path) -> None:
    adapter = _Mutable()

    solve_one(adapter, MODEL, None, _slot(tmp_path), ())

    assert adapter.calls == ["validate", "build", "run"]


def test_solve_one_stops_before_the_solve_after_a_rerun(tmp_path: Path) -> None:
    adapter = _Mutable()
    previous = SolverRun(slot=_slot(tmp_path), model=MODEL, written=True, solved=True)

    result = solve_one(
        adapter,
        MODEL.with_properties(K=2e-5),
        None,
        _slot(tmp_path, stop=True),
        (),
        previous=previous,
    )

    assert adapter.calls == ["validate", "rerun"]
    assert result.solved is False


def test_solve_one_hands_the_upstream_run_to_the_transport_it_builds(tmp_path: Path) -> None:
    """A transport build receives the SolverRun of the flow it follows, and nothing else."""
    flow_run = SolverRun(slot=_slot(tmp_path), solver_model=object(), written=True, solved=True)
    adapter = _RecordingAdapter()

    solve_one(adapter, MODEL, None, flow_run.slot, (flow_run,))

    name, (model, options, slot, upstream) = adapter.received[-1]
    assert (name, model, options, slot) == ("build", MODEL, None, flow_run.slot)
    assert upstream == (flow_run,)


class _Diverging(FakeAdapter):
    def __init__(self, run_id: str | None) -> None:
        super().__init__()
        self.run_id = run_id

    def run(self, solver_run):
        raise SolverDivergedError(
            f"Flow solver failed for run '{solver_run.slot.name}'.", run_id=self.run_id
        )


@pytest.mark.parametrize(
    ("named", "expected"),
    [(None, FLOW.id), ("flow_other::modflow6", "flow_other::modflow6")],
    ids=["named by the runner", "named by the backend"],
)
def test_a_solver_error_names_its_run(monkeypatch, named: str | None, expected: str) -> None:
    """The message names the run by its slot; the runner fills an id the backend left."""
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: _Diverging(named))

    with pytest.raises(SolverDivergedError, match="for run 'default'") as caught:
        SimulationRunner().execute(_plan(FLOW), _state(model=object()))

    assert caught.value.run_id == expected


def test_the_runner_hands_previous_runs_to_their_own_run_only(monkeypatch) -> None:
    adapter = _Mutable()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    model = MODEL.with_properties(K=2e-5)
    previous = SolverRun(
        slot=RunSlot(Path("old"), "island"), model=MODEL, written=True, solved=True
    )

    SimulationRunner().execute(_plan(FLOW), _state(model=model), previous={FLOW.id: previous})
    SimulationRunner().execute(_plan(FLOW), _state(model=model), previous={"other": previous})

    assert adapter.calls == ["validate", "rerun", "run", "validate", "build", "run"]


# ---------------------------------------------------------------------------
# A transport run follows one flow run, of the family its backend requires.
#
# The tests register a fake flow and two fake transports under the names the
# shipped backends carry, in the isolated ``solvers`` registry, so the runner
# is read without importing a backend or the paths of another lot.
# ---------------------------------------------------------------------------


def _register_backends(
    isolated_solvers: Any,
    *,
    trace: list[str],
    converged: bool | None = None,
) -> None:
    """Register the fake flow and transports these tests read, under their own names."""

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


def _transport_run(solver: str, *, depends_on: tuple[ProcessRun, ...] = ()) -> ProcessRun:
    return ProcessRun(
        id=f"transport_main::{solver}",
        process_id="transport_main",
        process_type="transport",
        solver=solver,
        depends_on=tuple(one.id for one in depends_on),
    )


@pytest.mark.parametrize(
    ("converged", "sealed", "outcome"),
    [
        (True, False, "runs"),
        (None, False, "runs"),
        (False, False, "refused"),
        (False, True, "warns"),
        (True, True, "runs"),
    ],
    ids=["converged", "no steady start", "not converged", "not converged, sealed", "sealed"],
)
def test_a_transport_run_behind_a_start_that_did_not_converge(
    isolated_solvers, converged, sealed, outcome
) -> None:
    trace: list[str] = []
    _register_backends(isolated_solvers, trace=trace, converged=converged)
    state = _state(model=object())
    state.cfg = SimpleNamespace(read_as_sealed=sealed)
    runner = SimulationRunner()

    if outcome == "refused":
        with pytest.raises(SolverDivergedError, match="did not converge") as caught:
            runner.execute(_plan(FLOW, MODPATH), state)
        assert caught.value.run_id == MODPATH.id
        assert trace == ["flow"]
        return
    if outcome == "warns":
        with pytest.warns(RuntimeWarning, match="did not converge"):
            runner.execute(_plan(FLOW, MODPATH), state)
    else:
        runner.execute(_plan(FLOW, MODPATH), state)
    assert trace == ["flow", "transport"]


def test_a_start_that_did_not_converge_is_forgotten_by_the_next_execution(
    isolated_solvers,
) -> None:
    """The refusal is read off the runs of THIS execution, not remembered across them."""
    trace: list[str] = []
    _register_backends(isolated_solvers, trace=trace, converged=False)
    runner = SimulationRunner()
    with pytest.raises(SolverDivergedError):
        runner.execute(_plan(FLOW, MODPATH), _state(model=object()))

    trace.clear()
    _register_backends(isolated_solvers, trace=trace, converged=True)

    runner.execute(_plan(FLOW, MODPATH), _state(model=object()))

    assert trace == ["flow", "transport"]


def test_a_transport_whose_dependency_is_not_the_family_its_backend_requires_is_refused(
    isolated_solvers,
) -> None:
    """MT3DMS follows the flow MODFLOW 6 solves; hand it NWT's run and the runner refuses it."""
    trace: list[str] = []
    _register_backends(isolated_solvers, trace=trace)

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
    cross = _transport_run("mt3dms", depends_on=(NWT_FLOW,))
    state = _state(model=object())

    with pytest.raises(SolverInputError, match="follows the \\(flow, modflow6\\) flow"):
        SimulationRunner().execute(_plan(NWT_FLOW, cross), state)

    assert trace == ["flow"]


@pytest.mark.parametrize(
    "recorded",
    [{}, {FLOW.id: {"solver_model": None}}],
    ids=["the flow has not run", "the flow produced no model"],
)
def test_a_transport_whose_flow_produced_nothing_is_refused(
    isolated_solvers, recorded: dict[str, Any]
) -> None:
    trace: list[str] = []
    _register_backends(isolated_solvers, trace=trace)
    state = _state(model=object())
    state.execution.solver_runs.update(
        {
            run_id: SolverRun(slot=RunSlot(Path("."), "x"), **members)
            for run_id, members in recorded.items()
        }
    )

    with pytest.raises(PipelineError, match="has produced no model") as caught:
        SimulationRunner().execute(_plan(MODPATH), state)

    assert caught.value.run_id == MODPATH.id
    assert trace == []
