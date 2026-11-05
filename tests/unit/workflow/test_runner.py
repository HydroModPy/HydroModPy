"""Pipeline: the step loop, its errors, its journal and its resume."""

from __future__ import annotations

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
from hydromodpy.workflow.record.journal import WorkflowJournal
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


def test_linear_pipeline_runs_all_steps() -> None:
    state = PipelineState(run_id="r", data={"counter": 0})
    pipeline = Pipeline([_AddOne(), _AddOne(), _Multiply(5)])
    final = pipeline.run(state)
    assert final.data["counter"] == 10  # (0+1+1)*5
    assert final.step_name == "multiply"
    assert final.step_index == 2


def test_pipeline_preserves_run_id() -> None:
    state = PipelineState(run_id="my-run-42", data={"counter": 7})
    pipeline = Pipeline([_AddOne()])
    final = pipeline.run(state)
    assert final.run_id == "my-run-42"


def test_pipeline_records_elapsed_ms_for_each_step() -> None:
    state = PipelineState(run_id="r", data={"counter": 0})
    pipeline = Pipeline([_AddOne(), _AddOne()])
    final = pipeline.run(state)
    assert final.elapsed_ms >= 0.0


def test_pipeline_run_without_workspace_skips_ledger() -> None:
    # No workspace → no ledger / no checkpoint store. Must still run.
    state = PipelineState(run_id="r", data={"counter": 0})
    pipeline = Pipeline([_AddOne()])
    final = pipeline.run(state)
    assert final.data["counter"] == 1


def test_pipeline_workspace_does_not_create_pickle_state(
    tmp_path: Path,
) -> None:
    state = PipelineState(run_id="r", data={"counter": 0})
    pipeline = Pipeline([_AddOne()], workspace=tmp_path)
    final = pipeline.run(state)

    assert final.data["counter"] == 1
    checkpoint_dir = tmp_path / ".hmp" / "checkpoints" / "r"
    if checkpoint_dir.exists():
        assert not any(p.suffix in (".pkl", ".pkl.zst") for p in checkpoint_dir.iterdir())


def test_pipeline_wraps_step_failure_in_step_error() -> None:
    state = PipelineState(run_id="r")
    pipeline = Pipeline([_AddOne(), _Fail()])
    with pytest.raises(StepError) as excinfo:
        pipeline.run(state)
    err = excinfo.value
    assert err.step_name == "fail"
    assert err.run_id == "r"
    assert isinstance(err.cause, RuntimeError)
    assert isinstance(err.__cause__, RuntimeError)


def test_pipeline_resume_from_replays_in_memory_prefix() -> None:
    # In the state-from-artifacts model, the in-memory prefix is re-executed
    # idempotently. counter=100 -> +1 +1 = 102 -> *10 = 1020.
    state = PipelineState(run_id="r", data={"counter": 100})
    pipeline = Pipeline([_AddOne(), _AddOne(), _Multiply(10)])
    final = pipeline.run(state, resume_from=2)
    assert final.data["counter"] == 1020
    assert final.step_name == "multiply"


def test_state_advance_preserves_run_id_and_updates_step_metadata() -> None:
    state = PipelineState(run_id="abc", data={"x": 1})
    nxt = state.advance(step_index=5, step_name="foo", x=2)
    assert nxt.run_id == "abc"
    assert nxt.step_index == 5
    assert nxt.step_name == "foo"
    assert nxt.data == {"x": 2}


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


def test_step_error_carries_step_name_and_cause() -> None:
    cause = ValueError("bad")
    err = StepError("validate", cause, run_id="r-42")
    assert err.step_name == "validate"
    assert err.cause is cause
    assert err.run_id == "r-42"
    assert "validate" in str(err)
    assert "bad" in str(err)


def test_step_error_propagates_extra_context() -> None:
    err = StepError("x", RuntimeError("boom"), sim_id="s1", run_id="r1", extra="meta")
    assert err.sim_id == "s1"
    assert err.run_id == "r1"
    assert err.context == {"extra": "meta"}


# ---------------------------------------------------------------------------
# Pipeline wraps step exceptions in StepError
# ---------------------------------------------------------------------------


def test_pipeline_wraps_arbitrary_exception_in_step_error() -> None:
    pipeline = Pipeline([_RaisesValueError()])
    state = PipelineState(run_id="r-1", data={})
    with pytest.raises(StepError) as excinfo:
        pipeline.run(state)
    err = excinfo.value
    assert err.step_name == "boom"
    assert err.run_id == "r-1"
    assert isinstance(err.cause, ValueError)
    assert isinstance(err.__cause__, ValueError)


def test_pipeline_does_not_wrap_keyboard_interrupt() -> None:
    pipeline = Pipeline([_RaisesKeyboardInterrupt()])
    state = PipelineState(run_id="r", data={})
    with pytest.raises(KeyboardInterrupt):
        pipeline.run(state)


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


def test_full_run_records_completed_rows(tmp_path: Path) -> None:
    pipeline = _pipeline([_JournalAddOne(), _JournalAddOne(), _Double()], tmp_path)
    state = PipelineState(run_id="r1", data={"counter": 0})
    final = pipeline.run(state)
    assert final.data["counter"] == 4

    rows = _rows(tmp_path, "r1")
    assert [r.step_name for r in rows] == ["add_one", "add_one", "double"]
    assert all(r.status == "completed" for r in rows)


def test_crash_then_resume_replays_only_remaining(tmp_path: Path) -> None:
    state = PipelineState(run_id="crash-1", data={"counter": 5})
    crashing = _pipeline([_JournalAddOne(), _Crash(), _Double()], tmp_path)
    with pytest.raises(StepError) as info:
        crashing.run(state)
    assert info.value.step_name == "crash"

    rows = _rows(tmp_path, "crash-1")
    statuses = [(r.step_order, r.status) for r in rows]
    assert statuses == [(0, "completed"), (1, "failed")]

    # State-from-artifacts: in-memory step 0 is re-executed from the supplied
    # initial state. We pass the same input (counter=5) so step 0 re-runs to 6,
    # then the recovered step bumps to 7, and double yields 14.
    fixed = _pipeline([_JournalAddOne(), _RecoveredCrash(), _Double()], tmp_path)
    final = fixed.run(PipelineState(run_id="crash-1", data={"counter": 5}), resume_from=1)
    assert final.step_name == "double"
    assert final.data["counter"] == 14

    rows = _rows(tmp_path, "crash-1")
    assert [r.status for r in rows] == ["completed", "completed", "completed"]


def test_resume_without_journal_starts_from_scratch(tmp_path: Path) -> None:
    pipeline = _pipeline([_JournalAddOne()], tmp_path)
    state = PipelineState(run_id="fresh", data={"counter": 99})
    final = pipeline.run(state, resume_from=0)
    assert final.data["counter"] == 100


def test_no_pickle_files_produced(tmp_path: Path) -> None:
    pipeline = _pipeline([_JournalAddOne(), _JournalAddOne()], tmp_path)
    pipeline.run(PipelineState(run_id="no-pkl", data={"counter": 0}))
    pickle_dir = tmp_path / ".hmp" / "checkpoints"
    if pickle_dir.exists():
        for entry in pickle_dir.iterdir():
            assert entry.suffix not in (".pkl", ".pkl.zst")


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


def test_a_rebuilt_prefix_row_carries_what_the_step_declares(tmp_path: Path) -> None:
    """The row of a re-executed prefix step names its artifacts and digests them."""
    writer = _Writer("_preprocessing/head.txt")
    pipeline = Pipeline([writer, _Terminal()], workspace=tmp_path, run_dir=tmp_path)
    pipeline.run(PipelineState(run_id="declared", data={"workspace": str(tmp_path)}), resume_from=1)

    assert writer.run_calls == 1
    head = next(row for row in _prefix_rows(tmp_path, "declared") if row.step_order == 0)
    assert head.artifact_uris == ("_preprocessing/head.txt",)
    assert head.outputs_hash and not head.outputs_hash.startswith("e3b0c44298fc1c14")


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


def test_the_suffix_chains_its_inputs_hash_onto_the_prefix(tmp_path: Path) -> None:
    """A resumed step hashes the same upstream sequence a full run would give it."""
    full_dir = tmp_path / "runs" / "full"
    full = Pipeline(
        [_Writer("_preprocessing/head.txt"), _Terminal()], workspace=tmp_path, run_dir=full_dir
    )
    full.run(PipelineState(run_id="full", data={"workspace": str(tmp_path)}))
    from_scratch = next(row for row in _prefix_rows(full_dir, "full") if row.step_order == 1)

    resumed_dir = tmp_path / "runs" / "resumed"
    resumed_pipeline = Pipeline(
        [_Writer("_preprocessing/head.txt"), _Terminal()],
        workspace=tmp_path,
        run_dir=resumed_dir,
    )
    resumed_pipeline.run(
        PipelineState(run_id="resumed", data={"workspace": str(tmp_path)}),
        resume_from=1,
    )
    resumed = next(row for row in _prefix_rows(resumed_dir, "resumed") if row.step_order == 1)

    assert resumed.inputs_hash == from_scratch.inputs_hash


def test_a_rerun_of_the_same_name_does_not_keep_its_invalidated_head(tmp_path: Path) -> None:
    """A re-run rebuilds its prefix, so the rows it aborted must not survive.

    ``Pipeline.run`` invalidates the whole journal of a model-phase-ready
    re-run before rebuilding it. A prefix row left at ``aborted`` describes a
    run that never happened, and sends the next resume back to step zero.
    """
    from hydromodpy.workflow.record.resume import ResumePlanner

    steps = [_Prebuilt("head"), _Prebuilt("middle"), _Terminal()]
    state = PipelineState(run_id="rerun")
    Pipeline(steps, workspace=tmp_path, run_dir=tmp_path).run(state)
    Pipeline(steps, workspace=tmp_path, run_dir=tmp_path).run(
        state, resume_from=2, model_phase_ready=True
    )

    rows = _prefix_rows(tmp_path, "rerun")
    assert [(r.step_order, r.status) for r in rows] == [
        (0, "completed"),
        (1, "completed"),
        (2, "completed"),
    ]

    plan = ResumePlanner(WorkflowJournal(tmp_path), tmp_path).compute(
        run_id="rerun",
        current_config_sha256=None,
        steps_blueprint=("head", "middle", "terminal"),
    )
    assert plan.restart_index == 3


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


def test_full_run_writes_artefacts_and_journal(tmp_path: Path) -> None:
    blueprint = (
        _Memory("mem0"),
        _Memory("mem1"),
        _Persistent("p2"),
        _Persistent("p3"),
        _Persistent("p4"),
    )
    pipeline = Pipeline(blueprint, workspace=tmp_path, run_dir=tmp_path)
    final = pipeline.run(_initial_state(tmp_path, "run-A"))

    assert final.step_name == "p4"
    for name in ("p2", "p3", "p4"):
        assert (tmp_path / "artefacts" / f"{name}.txt").is_file()

    rows = WorkflowJournal(tmp_path).list_steps("run-A")
    assert [r.step_name for r in rows] == ["mem0", "mem1", "p2", "p3", "p4"]
    assert all(r.status == "completed" for r in rows)


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


def test_no_pickle_files_anywhere(tmp_path: Path) -> None:
    blueprint = (_Memory("mem0"), _Persistent("p1"), _Persistent("p2"))
    pipeline = Pipeline(blueprint, workspace=tmp_path, run_dir=tmp_path)
    pipeline.run(_initial_state(tmp_path, "run-C"))

    checkpoint_root = tmp_path / ".hmp" / "checkpoints"
    if checkpoint_root.exists():
        for entry in checkpoint_root.rglob("*"):
            assert entry.suffix not in (".pkl", ".pkl.zst", ".pickle")
