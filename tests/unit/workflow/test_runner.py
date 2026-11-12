"""Pipeline: the step loop, its errors, its journal and its resume."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import (
    CheckpointError,
    HydroModPyError,
    LedgerError,
    PipelineError,
    ResumeError,
    StepError,
)
from hydromodpy.core.runtime.interrupts import StopRequested
from hydromodpy.core.state.layout import stop_flag_for
from hydromodpy.results.storage.run_profile import collected_profile, read_profile
from hydromodpy.workflow.record.journal import WorkflowJournal
from hydromodpy.workflow.record.resume import resolve_resume_step_index
from hydromodpy.workflow.runner import Pipeline
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.step import Step

# --- test_pipeline_basic ---
# Unit tests for the :class:`hydromodpy.workflow.runner.Pipeline` orchestrator.
#
# Covers the linear execution contract: state flows between steps, step
# metadata (index, name, elapsed) is populated, and the final state is
# produced by the last step.


class _AddOne:
    """Minimal step that increments ``data['counter']`` by 1."""

    name = "add_one"

    def run(self, state: PipelineState) -> PipelineState:
        counter = state.data.get("counter", 0) + 1
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=counter,
        )


class _Multiply:
    name = "multiply"

    def __init__(self, factor: int) -> None:
        self.factor = factor

    def run(self, state: PipelineState) -> PipelineState:
        counter = state.data.get("counter", 0) * self.factor
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=counter,
        )


class _Fail:
    name = "fail"

    def run(self, state: PipelineState) -> PipelineState:
        raise RuntimeError("boom")


def test_step_protocol_is_satisfied() -> None:
    assert isinstance(_AddOne(), Step)
    assert isinstance(_Multiply(3), Step)


def test_pipeline_resume_from_replays_in_memory_prefix() -> None:
    # In the state-from-artifacts model, the in-memory prefix is re-executed
    # idempotently. counter=100 -> +1 +1 = 102 -> *10 = 1020.
    state = PipelineState(run_id="r", data={"counter": 100})
    pipeline = Pipeline([_AddOne(), _AddOne(), _Multiply(10)])
    final = pipeline.run(state, resume_from=2)
    assert final.data["counter"] == 1020
    assert final.step_name == "multiply"


def test_state_is_immutable() -> None:
    state = PipelineState(run_id="r", data={"x": 1})
    with pytest.raises(Exception):
        state.step_index = 99  # type: ignore[misc]


# --- test_pipeline_errors ---
# Unit tests for the :class:`PipelineError` hierarchy and its wrapping.


class _RaisesValueError:
    name = "boom"

    def run(self, state):
        raise ValueError("upstream cause")


class _RaisesKeyboardInterrupt:
    name = "interrupt"

    def run(self, state):
        raise KeyboardInterrupt()


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------


def test_pipeline_error_inherits_hydromodpy_base() -> None:
    assert issubclass(PipelineError, HydroModPyError)


@pytest.mark.parametrize(
    "subclass",
    [StepError, CheckpointError, LedgerError, ResumeError],
)
def test_pipeline_subclasses_inherit_pipeline_error(subclass) -> None:
    assert issubclass(subclass, PipelineError)


def test_each_pipeline_error_class_has_distinct_code() -> None:
    codes = {
        PipelineError.code,
        StepError.code,
        CheckpointError.code,
        LedgerError.code,
        ResumeError.code,
    }
    assert len(codes) == 5


def test_pipeline_error_codes_match_e500_range() -> None:
    assert PipelineError.code == "HMPY.E500"
    assert StepError.code == "HMPY.E501"
    assert CheckpointError.code == "HMPY.E502"
    assert LedgerError.code == "HMPY.E503"
    assert ResumeError.code == "HMPY.E504"


# ---------------------------------------------------------------------------
# StepError canonical constructor
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Pipeline wraps step exceptions in StepError
# ---------------------------------------------------------------------------


def test_pipeline_does_not_double_wrap_step_error() -> None:
    class _RaisesStepError:
        name = "already_typed"

        def run(self, state):
            raise StepError("already_typed", RuntimeError("inner"), run_id="r")

    pipeline = Pipeline([_RaisesStepError()])
    with pytest.raises(StepError) as excinfo:
        pipeline.run(PipelineState(run_id="r", data={}))
    # Re-raised as-is (not wrapped a second time): cause stays the original.
    assert isinstance(excinfo.value.cause, RuntimeError)
    assert excinfo.value.step_name == "already_typed"


# --- test_pipeline_prebuilt_skip ---
# Rebuild-prefix reuse: steps whose products are already in memory are skipped.


class _PrefixStep:
    """Prefix step recording run() calls, optionally reporting prebuilt state."""

    name = "prefix"

    def __init__(self, prebuilt: bool) -> None:
        self.prebuilt = prebuilt
        self.run_calls = 0

    def is_prebuilt(self, state: PipelineState) -> bool:
        return self.prebuilt

    def run(self, state: PipelineState) -> PipelineState:
        self.run_calls += 1
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class _LegacyPrefixStep:
    """Prefix step without the is_prebuilt hook."""

    name = "prefix"

    def __init__(self) -> None:
        self.run_calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.run_calls += 1
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class _Terminal:
    name = "terminal"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


@pytest.mark.parametrize(
    ("make_prefix", "resume_from", "run_calls"),
    [
        pytest.param(
            lambda: _PrefixStep(prebuilt=True), 1, 0, id="a prebuilt prefix step is not rerun"
        ),
        pytest.param(
            lambda: _PrefixStep(prebuilt=False), 1, 1, id="an unbuilt prefix step is rerun"
        ),
        pytest.param(
            lambda: _LegacyPrefixStep(), 1, 1, id="a prefix step without the hook is rerun"
        ),
        pytest.param(
            lambda: _PrefixStep(prebuilt=True),
            0,
            1,
            id="the prebuilt hook is ignored in the executed suffix",
        ),
    ],
)
def test_a_prefix_step_is_rerun_unless_it_is_prebuilt(make_prefix, resume_from, run_calls) -> None:
    prefix = make_prefix()
    pipeline = Pipeline([prefix, _Terminal()])
    final = pipeline.run(PipelineState(run_id="r1"), resume_from=resume_from)
    assert prefix.run_calls == run_calls
    assert final.step_name == "terminal"


# --- test_pipeline_journal_resume ---
# Pipeline resume driven by the step journal of the run directory.
#
# Each scenario exercises a small synthetic pipeline whose run directory is the
# temporary folder, then asserts the journal rows and the absence of pickle
# artifacts.


class _JournalAddOne:
    name = "add_one"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=state.data.get("counter", 0) + 1,
        )


class _Double:
    name = "double"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=state.data.get("counter", 0) * 2,
        )


class _Crash:
    name = "crash"

    def run(self, state: PipelineState) -> PipelineState:
        raise RuntimeError("simulated crash")


class _RecoveredCrash:
    name = "crash"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=state.data.get("counter", 0) + 1,
        )


def _pipeline(steps, root: Path) -> Pipeline:
    return Pipeline(steps, workspace=root, run_dir=root)


def _rows(root: Path, run_id: str):
    return WorkflowJournal(root).list_steps(run_id)


def test_model_phase_ready_rerun_survives_config_change(tmp_path: Path) -> None:
    """A plain re-run with an edited config must not abort as a stale resume.

    Regression: the model-phase-ready optimization sets ``resume_from > 0`` (it
    only skips the in-process model phase). That used to trip
    ``manifest.verify_state`` against the prior same-name run's checkpoint and
    raise ``ResumeError`` whenever the config changed (e.g. edit Sy, re-run
    ``hmp run``). ``model_phase_ready=True`` marks it as a fresh run instead.
    """
    from hydromodpy.core.exceptions import ResumeError

    steps = [_JournalAddOne(), _JournalAddOne(), _Double()]
    _pipeline(steps, tmp_path).run(
        PipelineState(run_id="r", data={"counter": 0, "raw_toml": {"flow": {"sy": 0.001}}})
    )

    changed = PipelineState(run_id="r", data={"counter": 0, "raw_toml": {"flow": {"sy": 0.0001}}})
    final = _pipeline(steps, tmp_path).run(changed, resume_from=2, model_phase_ready=True)
    assert final.data["counter"] == 4

    # A genuine resume still verifies the checkpoint and rejects the change.
    stale = PipelineState(run_id="r", data={"counter": 0, "raw_toml": {"flow": {"sy": 0.5}}})
    with pytest.raises(ResumeError):
        _pipeline(steps, tmp_path).run(stale, resume_from=2, model_phase_ready=False)


# --- test_pipeline_prefix_journal ---
# The journal of a finished run describes its head, not only its tail.
#
# The model phase of a run driven by the facade is built before the pipeline
# starts, so its steps reach the rebuild branch and never went through the
# journalling execute path. Without a row, a finished run journals its tail
# only and a later resume has nothing telling it what the head left on disk.


class _Prebuilt:
    """Prefix step whose products already sit on the in-memory context."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.run_calls = 0

    def is_prebuilt(self, state: PipelineState) -> bool:
        return True

    def run(self, state: PipelineState) -> PipelineState:
        self.run_calls += 1
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class _Writer:
    """Prefix step that leaves one declared file behind."""

    name = "writer"

    def __init__(self, relative: str) -> None:
        self.relative = relative
        self.run_calls = 0

    def is_prebuilt(self, state: PipelineState) -> bool:
        return False

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        return (self.relative,)

    def run(self, state: PipelineState) -> PipelineState:
        self.run_calls += 1
        target = Path(state.data["workspace"]) / self.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("built\n", encoding="utf-8")
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def _prefix_rows(run_dir: Path, run_id: str):
    return WorkflowJournal(run_dir).list_steps(run_id)


def test_a_prebuilt_prefix_is_journalled(tmp_path: Path) -> None:
    """A step skipped because the context already carries it still gets a row."""
    steps = [_Prebuilt("head"), _Prebuilt("middle"), _Terminal()]
    pipeline = Pipeline(steps, workspace=tmp_path, run_dir=tmp_path)
    pipeline.run(PipelineState(run_id="prebuilt"), resume_from=2, model_phase_ready=True)

    rows = _prefix_rows(tmp_path, "prebuilt")
    assert [(r.step_order, r.step_name, r.status) for r in rows] == [
        (0, "head", "completed"),
        (1, "middle", "completed"),
        (2, "terminal", "completed"),
    ]


def test_a_row_written_by_a_real_execution_is_never_replaced(tmp_path: Path) -> None:
    """A resume keeps the evidence the planner verified instead of re-measuring it."""
    writer = _Writer("_preprocessing/head.txt")
    state = PipelineState(run_id="kept", data={"workspace": str(tmp_path)})
    Pipeline([writer, _Terminal()], workspace=tmp_path, run_dir=tmp_path).run(state)
    executed = next(row for row in _prefix_rows(tmp_path, "kept") if row.step_order == 0)

    Pipeline([writer, _Terminal()], workspace=tmp_path, run_dir=tmp_path).run(state, resume_from=1)
    resumed = next(row for row in _prefix_rows(tmp_path, "kept") if row.step_order == 0)

    assert resumed.step_id == executed.step_id
    assert resumed.started_at == executed.started_at
    assert writer.run_calls == 1


# --- test_pipeline_state_from_artifacts ---
# End-to-end resume relies on ``rebuild_state`` only.
#
# Builds a pipeline mixing in-memory steps with persistent steps that
# declare ``artifacts()`` and ``rebuild_state``. On resume, the runner must
# re-execute the in-memory steps and rebuild from disk the persistent ones,
# never touching the deleted pickle layer.


class _Memory:
    """In-memory step: re-executed at resume."""

    config_sections: ClassVar[tuple[str, ...]] = ()

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.calls += 1
        history = list(state.data.get("history", ()))
        history.append(("memory", self.name))
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            history=tuple(history),
        )


class _Persistent:
    """Persistent step: declares artifacts and supports rebuild_state."""

    config_sections: ClassVar[tuple[str, ...]] = ()

    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self._fail = fail
        self.run_calls = 0
        self.rebuild_calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        if self._fail:
            raise RuntimeError(f"{self.name} crashed")
        self.run_calls += 1
        workspace = Path(state.get("workspace"))
        target = workspace / "artefacts" / f"{self.name}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.name, encoding="utf-8")
        history = list(state.data.get("history", ()))
        history.append(("persistent", self.name))
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            history=tuple(history),
        )

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        return (f"artefacts/{self.name}.txt",)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        self.rebuild_calls += 1
        history = list(prior_state.data.get("history", ()))
        history.append(("rebuilt", self.name))
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            history=tuple(history),
        )


def _initial_state(tmp_path: Path, run_id: str) -> PipelineState:
    return PipelineState(
        run_id=run_id,
        data={"workspace": str(tmp_path), "history": ()},
    )


def test_resume_rebuilds_persistent_and_reexec_memory(tmp_path: Path) -> None:
    blueprint = (
        _Memory("mem0"),
        _Memory("mem1"),
        _Persistent("p2"),
        _Persistent("p3"),
        _Persistent("p4"),
    )
    pipeline = Pipeline(blueprint, workspace=tmp_path, run_dir=tmp_path)
    pipeline.run(_initial_state(tmp_path, "run-B"))

    # second pipeline objects (fresh counters) to observe rebuild vs re-exec
    recovery = (
        _Memory("mem0"),
        _Memory("mem1"),
        _Persistent("p2"),
        _Persistent("p3"),
        _Persistent("p4"),
    )
    pipeline = Pipeline(recovery, workspace=tmp_path, run_dir=tmp_path)
    final = pipeline.run(_initial_state(tmp_path, "run-B"), resume_from=3)

    mem0, mem1, p2, p3, p4 = recovery
    assert mem0.calls == 1
    assert mem1.calls == 1
    assert p2.rebuild_calls == 1
    assert p2.run_calls == 0
    assert p3.run_calls == 1
    assert p4.run_calls == 1
    assert ("rebuilt", "p2") in final.data["history"]
    assert ("persistent", "p3") in final.data["history"]


# --- test_the_pipeline_reads_the_stop_flag_and_writes_the_profile ---
# The flag of the run is read before each cohort, so a stop asked while a step runs ends
# the run before the next step, the seal included. Each step has its line in
# ``profile.json`` as soon as it ends, and a step rebuilt from an earlier attempt is
# marked ``prefix``.


class _AsksToStop:
    """A step that writes the stop flag of its run, as another process would."""

    name = "asks_to_stop"

    def run(self, state: PipelineState) -> PipelineState:
        _flagged(Path(state.get("run_dir")), when="2026-11-10T08:00:00+00:00")
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def _flagged(run_dir: Path, *, when: str | None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    if when is not None:
        flag = stop_flag_for(run_dir)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(json.dumps({"at": when}), encoding="utf-8")


def test_a_stop_asked_by_step_two_ends_the_run_before_step_three(tmp_path: Path) -> None:
    steps = [_JournalAddOne(), _AsksToStop(), _Double()]
    state = PipelineState(run_id="r", data={"counter": 1, "run_dir": tmp_path})
    with pytest.raises(StopRequested):
        _pipeline(steps, tmp_path).run(state)

    assert [(row.step_name, row.status) for row in _rows(tmp_path, "r")] == [
        ("add_one", "completed"),
        ("asks_to_stop", "completed"),
    ]
    assert [line.name for line in read_profile(tmp_path).lines] == ["add_one", "asks_to_stop"]
    # The resume plan starts at the step that never ran.
    blueprint = ("add_one", "asks_to_stop", "double")
    assert resolve_resume_step_index(tmp_path, tmp_path, "r", steps_blueprint=blueprint) == 2


def test_a_failed_step_keeps_its_line_and_a_resume_adds_to_the_profile(tmp_path: Path) -> None:
    with pytest.raises(StepError):
        _pipeline([_JournalAddOne(), _Crash()], tmp_path).run(
            PipelineState(run_id="r", data={"counter": 1})
        )
    assert [line.name for line in read_profile(tmp_path).lines] == ["add_one", "crash"]

    _pipeline([_JournalAddOne(), _RecoveredCrash(), _Double()], tmp_path).run(
        PipelineState(run_id="r", data={"counter": 1}), resume_from=1
    )
    assert [(line.name, line.reused) for line in read_profile(tmp_path).lines] == [
        ("add_one", "no"),
        ("crash", "no"),
        ("add_one", "prefix"),
        ("crash", "no"),
        ("double", "no"),
    ]


def test_a_rebuilt_step_is_a_prefix_line_and_a_run_step_is_not(tmp_path: Path) -> None:
    steps = [_Persistent("a"), _Persistent("b"), _Persistent("c")]
    _pipeline(steps, tmp_path).run(_initial_state(tmp_path, "r"))
    _pipeline(steps, tmp_path).run(_initial_state(tmp_path, "r"), resume_from=2)

    lines = read_profile(tmp_path).lines
    assert [(line.name, line.reused) for line in lines[3:]] == [
        ("a", "prefix"),
        ("b", "prefix"),
        ("c", "no"),
    ]


# --- a pipeline without a run directory profiles into the collector of its context ---
# A calibration trial has no run directory: its step lines reach the collector the
# trial opened, and no collector means no line, as before.


class _Apart:
    """A step that depends on no other, so it shares its cohort and runs in a thread."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.thread: str | None = None

    def depends_on(self) -> tuple[str, ...]:
        return ()

    def run(self, state: PipelineState) -> PipelineState:
        self.thread = threading.current_thread().name
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def test_the_steps_of_a_cohort_in_threads_reach_the_collector() -> None:
    steps = [_Apart("left"), _Apart("right")]
    with collected_profile() as lines:
        Pipeline(steps).run(PipelineState(run_id="r", data={}))
    assert sorted(line.name for line in lines) == ["left", "right"]
    assert any(step.thread != threading.current_thread().name for step in steps)
