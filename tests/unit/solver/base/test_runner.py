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
from hydromodpy.core.state.run_state import RunState, SlotRequest
from hydromodpy.solver.base import runner as runner_module
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SimulationPlan, SolverRun
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.base.runner import (
    ProcessCallbacks,
    SimulationRunner,
    options_for,
    run_name,
    slot_for,
    solve_one,
)
from tests._helpers.fake_solvers import FakeAdapter
from tests._helpers.model_factory import make_model

FLOW = ProcessRun(
    id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
)
SECOND_FLOW = ProcessRun(
    id="flow_second::modflow6", process_id="flow_second", process_type="flow", solver="modflow6"
)
TRANSPORT = ProcessRun(
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
    def build(self, model, options, slot, ctx):
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

    def build(self, model, options, slot, ctx):
        self.received.append(("build", (model, options, slot, ctx)))
        return super().build(model, options, slot, ctx)


def test_a_flow_run_needs_the_model_that_prepare_solver_builds(monkeypatch) -> None:
    """The runner refuses a flow run without ``setup.model`` before the adapter is called."""
    adapter = _RecordingAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)

    for setup in ({}, {"model": None}):
        with pytest.raises(ConfigError, match="prepare_solver"):
            SimulationRunner().execute(_plan(FLOW), _state(**setup))

    assert adapter.calls == []


def test_a_flow_run_hands_the_adapter_its_model_and_creates_no_flow(monkeypatch) -> None:
    adapter = _RecordingAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    model = object()
    state = _state(model=model, flow=None)

    SimulationRunner().execute(_plan(FLOW), state)

    name, (built_model, options, slot, ctx) = adapter.received[-1]
    assert name == "build"
    assert built_model is model
    assert options is None
    assert isinstance(slot, RunSlot)
    assert ctx.run == FLOW and ctx.solver_run is None and ctx.upstream == ()
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
    ("a transport of one", (FLOW, TRANSPORT), TRANSPORT, {"run_id": "island"}, "island"),
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


def test_a_setup_without_a_workspace_solves_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    slot = slot_for(_plan(FLOW), FLOW, SimpleNamespace(run_id="island"))

    assert slot.folder == tmp_path
    assert slot.bin_dir is None


class _Options(FakeAdapter):
    options: ClassVar[type | None] = object


OPTIONS: tuple[tuple[str, object, ProcessRun, str | None], ...] = (
    ("a flow with settings", _Options(), FLOW, "table of modflow6"),
    ("a flow without settings", FakeAdapter(), FLOW, None),
    ("a transport", _Options(), TRANSPORT, None),
)


@pytest.mark.parametrize(
    ("case", "adapter", "run", "expected"), OPTIONS, ids=[c for c, *_ in OPTIONS]
)
def test_options_for(case: str, adapter: object, run: ProcessRun, expected: str | None) -> None:
    del case
    cfg = SimpleNamespace(solver=SimpleNamespace(options_of=lambda name: f"table of {name}"))

    assert options_for(adapter, run, cfg) == expected


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

    result = solve_one(adapter, model, None, _slot(tmp_path), _ctx(), previous=previous)

    assert adapter.calls == calls
    assert result.model is model
    assert result.solved


def test_solve_one_without_a_previous_run_builds(tmp_path: Path) -> None:
    adapter = _Mutable()

    solve_one(adapter, MODEL, None, _slot(tmp_path), _ctx())

    assert adapter.calls == ["validate", "build", "run"]


def test_solve_one_stops_before_the_solve_after_a_rerun(tmp_path: Path) -> None:
    adapter = _Mutable()
    previous = SolverRun(slot=_slot(tmp_path), model=MODEL, written=True, solved=True)

    result = solve_one(
        adapter,
        MODEL.with_properties(K=2e-5),
        None,
        _slot(tmp_path, stop=True),
        _ctx(),
        previous=previous,
    )

    assert adapter.calls == ["validate", "rerun"]
    assert result.solved is False


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
def test_a_solver_error_names_its_run(named: str | None, expected: str, tmp_path: Path) -> None:
    with pytest.raises(SolverDivergedError, match="for run 'island'") as caught:
        solve_one(_Diverging(named), MODEL, None, _slot(tmp_path), _ctx())

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


class _PerRunAdapter(FakeAdapter):
    """Answers each run with the run written for its id and records the order."""

    def __init__(self, produced: dict[str, dict[str, Any]]) -> None:
        super().__init__()
        self.produced = produced
        self.ran: list[str] = []
        self.upstream: dict[str, tuple[SolverRun, ...]] = {}

    def build(self, model, options, slot, ctx):
        self.ran.append(ctx.run.id)
        self.upstream[ctx.run.id] = ctx.upstream
        return SolverRun(slot=slot, model=model, **self.produced[ctx.run.id])

    def run(self, solver_run):
        return replace(solver_run, written=True, solved=True)


def _flow_then_transport() -> SimulationPlan:
    return _plan(FLOW, TRANSPORT)


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
    monkeypatch, converged, sealed, outcome
) -> None:
    adapter = _PerRunAdapter(
        {
            FLOW.id: {"solver_model": object(), "initial_state_converged": converged},
            TRANSPORT.id: {"solver_model": object()},
        }
    )
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    monkeypatch.setitem(runner_module._COMPONENT_ENSURERS, "transport", lambda _state: None)
    state = _state(model=object())
    state.cfg = SimpleNamespace(read_as_sealed=sealed)
    runner = SimulationRunner()

    if outcome == "refused":
        with pytest.raises(SolverDivergedError, match="did not converge") as caught:
            runner.execute(_flow_then_transport(), state)
        assert caught.value.run_id == TRANSPORT.id
        assert adapter.ran == [FLOW.id]
        return
    if outcome == "warns":
        with pytest.warns(RuntimeWarning, match="did not converge"):
            runner.execute(_flow_then_transport(), state)
    else:
        runner.execute(_flow_then_transport(), state)
    assert adapter.ran == [FLOW.id, TRANSPORT.id]


def test_a_start_that_did_not_converge_is_forgotten_by_the_next_execution(monkeypatch) -> None:
    produced = {
        FLOW.id: {"solver_model": object(), "initial_state_converged": False},
        TRANSPORT.id: {"solver_model": object()},
    }
    adapter = _PerRunAdapter(produced)
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    monkeypatch.setitem(runner_module._COMPONENT_ENSURERS, "transport", lambda _state: None)
    runner = SimulationRunner()
    with pytest.raises(SolverDivergedError):
        runner.execute(_flow_then_transport(), _state(model=object()))

    produced[FLOW.id] = {"solver_model": object(), "initial_state_converged": True}
    runner.execute(_flow_then_transport(), _state(model=object()))

    assert adapter.ran[-1] == TRANSPORT.id


def test_a_transport_receives_the_solver_run_of_its_flow(monkeypatch) -> None:
    flow_model = object()
    adapter = _PerRunAdapter(
        {FLOW.id: {"solver_model": flow_model}, TRANSPORT.id: {"solver_model": object()}}
    )
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    monkeypatch.setitem(runner_module._COMPONENT_ENSURERS, "transport", lambda _state: None)
    state = _state(model=object())

    SimulationRunner().execute(_flow_then_transport(), state)

    assert adapter.upstream[FLOW.id] == ()
    (flow_run,) = adapter.upstream[TRANSPORT.id]
    assert flow_run is state.execution.solver_runs[FLOW.id]
    assert flow_run.solver_model is flow_model


@pytest.mark.parametrize(
    "recorded",
    [{}, {FLOW.id: {"solver_model": None}}],
    ids=["the flow has not run", "the flow produced no model"],
)
def test_a_transport_whose_flow_produced_nothing_is_refused(monkeypatch, recorded) -> None:
    adapter = _PerRunAdapter({TRANSPORT.id: {"solver_model": object()}})
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    monkeypatch.setitem(runner_module._COMPONENT_ENSURERS, "transport", lambda _state: None)
    state = _state(model=object())
    state.execution.solver_runs.update(
        {
            run_id: SolverRun(slot=RunSlot(Path("."), "x"), **members)
            for run_id, members in recorded.items()
        }
    )

    with pytest.raises(PipelineError, match="has produced no model") as caught:
        SimulationRunner().execute(_plan(TRANSPORT), state)

    assert caught.value.run_id == TRANSPORT.id
    assert adapter.ran == []
