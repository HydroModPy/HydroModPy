"""The pipeline runner: the step loop, its errors, its journal, its resume and its profile.

A step takes a state and returns the next one. The runner journals each step under the run
directory, resumes from a step index (rebuilding persistent steps from their artifacts), stops
when the stop flag of the run is set, and writes one line per step to profile.json.
"""

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


class AddOne:
    def __init__(self, name: str = "add_one") -> None:
        self.name = name

    def run(self, state: PipelineState) -> PipelineState:
        counter = state.data.get("counter", 0) + 1
        return state.advance(step_index=state.step_index + 1, step_name=self.name, counter=counter)


class Scale:
    def __init__(self, factor: int, name: str = "multiply") -> None:
        self.name = name
        self.factor = factor

    def run(self, state: PipelineState) -> PipelineState:
        counter = state.data.get("counter", 0) * self.factor
        return state.advance(step_index=state.step_index + 1, step_name=self.name, counter=counter)


class Terminal:
    name = "terminal"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class Crash:
    name = "crash"

    def run(self, state: PipelineState) -> PipelineState:
        raise RuntimeError("simulated crash")


class Prefix:
    """A prefix step that counts its runs and says whether its products are already in memory."""

    def __init__(self, prebuilt: bool, name: str = "prefix") -> None:
        self.name = name
        self.prebuilt = prebuilt
        self.run_calls = 0

    def is_prebuilt(self, state: PipelineState) -> bool:
        return self.prebuilt

    def run(self, state: PipelineState) -> PipelineState:
        self.run_calls += 1
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class PrefixWithoutHook:
    name = "prefix"

    def __init__(self) -> None:
        self.run_calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.run_calls += 1
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class Writer:
    """A prefix step that leaves one declared file behind."""

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


class Memory:
    """A step kept in memory: a resume runs it again."""

    config_sections: ClassVar[tuple[str, ...]] = ()

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.calls += 1
        history = (*state.data.get("history", ()), ("memory", self.name))
        return state.advance(step_index=state.step_index + 1, step_name=self.name, history=history)


class Persistent:
    """A step that declares its artifacts: a resume rebuilds its state from them."""

    config_sections: ClassVar[tuple[str, ...]] = ()

    def __init__(self, name: str) -> None:
        self.name = name
        self.run_calls = 0
        self.rebuild_calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.run_calls += 1
        target = Path(state.get("workspace")) / "artefacts" / f"{self.name}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.name, encoding="utf-8")
        history = (*state.data.get("history", ()), ("persistent", self.name))
        return state.advance(step_index=state.step_index + 1, step_name=self.name, history=history)

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        return (f"artefacts/{self.name}.txt",)

    def rebuild_state(
        self, *, prior_state: PipelineState, workspace: Path, run_id: str
    ) -> PipelineState:
        self.rebuild_calls += 1
        history = (*prior_state.data.get("history", ()), ("rebuilt", self.name))
        return prior_state.advance(
            step_index=prior_state.step_index + 1, step_name=self.name, history=history
        )


class AsksToStop:
    """A step that writes the stop flag of its run, as another process would."""

    name = "asks_to_stop"

    def run(self, state: PipelineState) -> PipelineState:
        flag = stop_flag_for(Path(state.get("run_dir")))
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(json.dumps({"at": "2026-11-10T08:00:00+00:00"}), encoding="utf-8")
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class Apart:
    """A step with no dependency: it shares its cohort and runs in a thread."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.thread: str | None = None

    def depends_on(self) -> tuple[str, ...]:
        return ()

    def run(self, state: PipelineState) -> PipelineState:
        self.thread = threading.current_thread().name
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def pipeline_in(steps, root: Path) -> Pipeline:
    return Pipeline(steps, workspace=root, run_dir=root)


def rows_of(root: Path, run_id: str):
    return WorkflowJournal(root).list_steps(run_id)


def initial_state(tmp_path: Path, run_id: str) -> PipelineState:
    return PipelineState(run_id=run_id, data={"workspace": str(tmp_path), "history": ()})


def test_steps_satisfy_the_protocol() -> None:
    assert isinstance(AddOne(), Step)
    assert isinstance(Scale(3), Step)


def test_resume_replays_the_in_memory_prefix() -> None:
    # The in-memory prefix is run again, so counter 100 gives +1 +1 = 102, then x10 = 1020.
    state = PipelineState(run_id="r", data={"counter": 100})
    final = Pipeline([AddOne(), AddOne(), Scale(10)]).run(state, resume_from=2)
    assert final.data["counter"] == 1020
    assert final.step_name == "multiply"


ERROR_CODES = [
    pytest.param(PipelineError, "HMPY.E500", id="pipeline"),
    pytest.param(StepError, "HMPY.E501", id="step"),
    pytest.param(CheckpointError, "HMPY.E502", id="checkpoint"),
    pytest.param(LedgerError, "HMPY.E503", id="ledger"),
    pytest.param(ResumeError, "HMPY.E504", id="resume"),
]


@pytest.mark.parametrize(("error_class", "code"), ERROR_CODES)
def test_error_codes(error_class, code) -> None:
    assert error_class.code == code
    assert issubclass(error_class, PipelineError)


def test_pipeline_error_is_a_hydromodpy_error() -> None:
    assert issubclass(PipelineError, HydroModPyError)


def test_step_error_not_rewrapped() -> None:
    class RaisesStepError:
        name = "already_typed"

        def run(self, state):
            raise StepError("already_typed", RuntimeError("inner"), run_id="r")

    with pytest.raises(StepError) as excinfo:
        Pipeline([RaisesStepError()]).run(PipelineState(run_id="r", data={}))
    assert isinstance(excinfo.value.cause, RuntimeError)
    assert excinfo.value.step_name == "already_typed"


PREFIX_RERUNS = [
    pytest.param(lambda: Prefix(prebuilt=True), 1, 0, id="prebuilt prefix step is kept"),
    pytest.param(lambda: Prefix(prebuilt=False), 1, 1, id="unbuilt prefix step is rerun"),
    pytest.param(PrefixWithoutHook, 1, 1, id="prefix step without the hook is rerun"),
    pytest.param(lambda: Prefix(prebuilt=True), 0, 1, id="hook ignored in the executed suffix"),
]


@pytest.mark.parametrize(("make_prefix", "resume_from", "run_calls"), PREFIX_RERUNS)
def test_prefix_step_rerun(make_prefix, resume_from, run_calls) -> None:
    prefix = make_prefix()
    final = Pipeline([prefix, Terminal()]).run(PipelineState(run_id="r1"), resume_from=resume_from)
    assert prefix.run_calls == run_calls
    assert final.step_name == "terminal"


def test_rerun_after_config_edit(tmp_path: Path) -> None:
    # Regression: a plain re-run after an edit of the config (say Sy, then `hmp run`) sets
    # resume_from > 0 because the model phase is skipped. It used to be checked as a stale
    # resume and raised ResumeError. model_phase_ready=True marks it as a fresh run.
    steps = [AddOne(), AddOne(), Scale(2, "double")]
    first = PipelineState(run_id="r", data={"counter": 0, "raw_toml": {"flow": {"sy": 0.001}}})
    pipeline_in(steps, tmp_path).run(first)

    changed = PipelineState(run_id="r", data={"counter": 0, "raw_toml": {"flow": {"sy": 0.0001}}})
    final = pipeline_in(steps, tmp_path).run(changed, resume_from=2, model_phase_ready=True)
    assert final.data["counter"] == 4

    # A genuine resume still checks the checkpoint and refuses the change.
    stale = PipelineState(run_id="r", data={"counter": 0, "raw_toml": {"flow": {"sy": 0.5}}})
    with pytest.raises(ResumeError):
        pipeline_in(steps, tmp_path).run(stale, resume_from=2, model_phase_ready=False)


def test_prebuilt_prefix_is_journalled(tmp_path: Path) -> None:
    # A step skipped because the context already carries it still gets a journal row.
    steps = [Prefix(True, "head"), Prefix(True, "middle"), Terminal()]
    pipeline_in(steps, tmp_path).run(
        PipelineState(run_id="prebuilt"), resume_from=2, model_phase_ready=True
    )

    assert [(r.step_order, r.step_name, r.status) for r in rows_of(tmp_path, "prebuilt")] == [
        (0, "head", "completed"),
        (1, "middle", "completed"),
        (2, "terminal", "completed"),
    ]


def test_executed_row_is_never_replaced(tmp_path: Path) -> None:
    # A resume keeps the evidence the planner checked instead of measuring it again.
    writer = Writer("_preprocessing/head.txt")
    state = PipelineState(run_id="kept", data={"workspace": str(tmp_path)})
    pipeline_in([writer, Terminal()], tmp_path).run(state)
    executed = next(row for row in rows_of(tmp_path, "kept") if row.step_order == 0)

    pipeline_in([writer, Terminal()], tmp_path).run(state, resume_from=1)
    resumed = next(row for row in rows_of(tmp_path, "kept") if row.step_order == 0)

    assert resumed.step_id == executed.step_id
    assert resumed.started_at == executed.started_at
    assert writer.run_calls == 1


def test_resume_rebuilds_persistent_and_reruns_memory(tmp_path: Path) -> None:
    def blueprint():
        return (
            Memory("mem0"),
            Memory("mem1"),
            Persistent("p2"),
            Persistent("p3"),
            Persistent("p4"),
        )

    pipeline_in(blueprint(), tmp_path).run(initial_state(tmp_path, "run-B"))

    # Fresh step objects, so their counters tell a rebuild from a rerun.
    recovery = blueprint()
    final = pipeline_in(recovery, tmp_path).run(initial_state(tmp_path, "run-B"), resume_from=3)

    mem0, mem1, p2, p3, p4 = recovery
    assert (mem0.calls, mem1.calls) == (1, 1)
    assert (p2.rebuild_calls, p2.run_calls) == (1, 0)
    assert (p3.run_calls, p4.run_calls) == (1, 1)
    assert ("rebuilt", "p2") in final.data["history"]
    assert ("persistent", "p3") in final.data["history"]


def test_stop_flag_ends_run(tmp_path: Path) -> None:
    steps = [AddOne(), AsksToStop(), Scale(2, "double")]
    state = PipelineState(run_id="r", data={"counter": 1, "run_dir": tmp_path})
    with pytest.raises(StopRequested):
        pipeline_in(steps, tmp_path).run(state)

    assert [(row.step_name, row.status) for row in rows_of(tmp_path, "r")] == [
        ("add_one", "completed"),
        ("asks_to_stop", "completed"),
    ]
    assert [line.name for line in read_profile(tmp_path).lines] == ["add_one", "asks_to_stop"]
    # The resume plan starts at the step that never ran.
    blueprint = ("add_one", "asks_to_stop", "double")
    assert resolve_resume_step_index(tmp_path, tmp_path, "r", steps_blueprint=blueprint) == 2


def test_failed_step_keeps_its_profile_line(tmp_path: Path) -> None:
    with pytest.raises(StepError):
        pipeline_in([AddOne(), Crash()], tmp_path).run(
            PipelineState(run_id="r", data={"counter": 1})
        )
    assert [line.name for line in read_profile(tmp_path).lines] == ["add_one", "crash"]

    pipeline_in([AddOne(), AddOne("crash"), Scale(2, "double")], tmp_path).run(
        PipelineState(run_id="r", data={"counter": 1}), resume_from=1
    )
    assert [(line.name, line.reused) for line in read_profile(tmp_path).lines] == [
        ("add_one", "no"),
        ("crash", "no"),
        ("add_one", "prefix"),
        ("crash", "no"),
        ("double", "no"),
    ]


def test_rebuilt_step_is_a_prefix_line(tmp_path: Path) -> None:
    steps = [Persistent("a"), Persistent("b"), Persistent("c")]
    pipeline_in(steps, tmp_path).run(initial_state(tmp_path, "r"))
    pipeline_in(steps, tmp_path).run(initial_state(tmp_path, "r"), resume_from=2)

    lines = read_profile(tmp_path).lines
    assert [(line.name, line.reused) for line in lines[3:]] == [
        ("a", "prefix"),
        ("b", "prefix"),
        ("c", "no"),
    ]


def test_cohort_in_threads_reaches_the_collector() -> None:
    # A calibration trial has no run directory: its profile lines go to the collector it opened.
    steps = [Apart("left"), Apart("right")]
    with collected_profile() as lines:
        Pipeline(steps).run(PipelineState(run_id="r", data={}))
    assert sorted(line.name for line in lines) == ["left", "right"]
    assert any(step.thread != threading.current_thread().name for step in steps)


@pytest.mark.parametrize(("with_run_dir", "expected"), [(True, ["a", "b"]), (False, [])])
def test_figures_are_drawn_after_each_executed_step(
    monkeypatch, tmp_path: Path, with_run_dir, expected
) -> None:
    drawn: list[str] = []
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.display.draw_after",
        lambda _state, step: drawn.append(step) or [],
    )
    steps = [Persistent("a"), Persistent("b")]
    pipeline = Pipeline(steps, workspace=tmp_path, run_dir=tmp_path if with_run_dir else None)

    pipeline.run(initial_state(tmp_path, "figs"))

    assert drawn == expected
