"""End-to-end: the pipeline resumes from a checkpoint after a crash.

A tiny four-step pipeline is built from synthetic steps that each append
their name to the state payload. The third step raises on the first
attempt; when re-run with ``resume_from=3`` the pipeline must restore
state at step 2 and execute step 3 onwards exactly once.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.workflow.internals.checkpoint import _strip_unpicklable
from hydromodpy.workflow.internals.state import (
    PipelineState,
    UnpicklableMarker,
)
from hydromodpy.workflow.runner import Pipeline


@dataclass
class _Append:
    name: str

    def run(self, state: PipelineState) -> PipelineState:
        data: Mapping[str, Any] = state.data  # type: ignore[assignment]
        history = list(data.get("history", []))
        history.append(self.name)
        return state.with_data(history=history)


@dataclass
class _Crash:
    name: str
    fail_once: list[bool]

    def run(self, state: PipelineState) -> PipelineState:
        if self.fail_once and self.fail_once[0]:
            self.fail_once[0] = False
            raise RuntimeError(f"{self.name} crashed")
        data: Mapping[str, Any] = state.data  # type: ignore[assignment]
        history = list(data.get("history", []))
        history.append(self.name)
        return state.with_data(history=history)


def test_pipeline_resume_after_step_crash(tmp_path: Path) -> None:
    crash_flag = [True]
    steps = [
        _Append("a"),
        _Append("b"),
        _Append("c"),
        _Crash("d", fail_once=crash_flag),
        _Append("e"),
    ]
    pipeline = Pipeline(steps, workspace=tmp_path, checkpoint=True)

    initial = PipelineState(run_id="rid-1")

    # First run - step "d" crashes after "a","b","c" were checkpointed.
    try:
        pipeline.run(initial)
    except Exception:
        pass

    # Second run - resume from the failing step; "d" now succeeds.
    final = pipeline.run(initial, resume_from=3)

    assert final.data["history"] == ["a", "b", "c", "d", "e"]
    # Steps a/b/c should have been checkpointed on the first run.
    checkpoint_dir = tmp_path / ".hmp" / "checkpoints" / "rid-1"
    files = sorted(p.name for p in checkpoint_dir.iterdir())
    assert any(name.startswith("00_") for name in files)
    assert any(name.startswith("02_") for name in files)


@dataclass
class _StashUnpicklable:
    """Step that stores a non-picklable handle under ``data["resource"]``."""

    name: str = "stash"

    def run(self, state: PipelineState) -> PipelineState:
        # Lambdas are not picklable: forces _strip_unpicklable to emit a marker.
        return state.with_data(resource=lambda: "live-handle")


@dataclass
class _RecordResource:
    """Step that records the runtime type of ``data["resource"]``."""

    name: str
    fail_once: list[bool] = field(default_factory=lambda: [False])

    def run(self, state: PipelineState) -> PipelineState:
        if self.fail_once and self.fail_once[0]:
            self.fail_once[0] = False
            raise RuntimeError(f"{self.name} crashed")
        data: Mapping[str, Any] = state.data  # type: ignore[assignment]
        observed = type(data["resource"]).__name__
        return state.with_data(observed_type=observed)


def test_pipeline_rebinds_unpicklable_values_after_resume(tmp_path: Path) -> None:
    """Markers left by ``_strip_unpicklable`` are rebuilt before each step."""
    rebuilt_calls: list[Path | None] = []

    def factory(workspace: Path | None, _state: PipelineState) -> dict[str, Any]:
        rebuilt_calls.append(workspace)
        return {"rebuilt": True, "workspace": str(workspace)}

    PipelineState.register_rebuild("resource", factory)
    try:
        crash_flag = [True]
        steps = [
            _StashUnpicklable(),
            _RecordResource("crash_or_record", fail_once=crash_flag),
        ]
        pipeline = Pipeline(steps, workspace=tmp_path, checkpoint=True)

        initial = PipelineState(run_id="rebind-1")

        # First run crashes on step 1 after step 0 wrote a marker checkpoint.
        try:
            pipeline.run(initial)
        except Exception:
            pass

        # Resume from step 1: the marker must be rebuilt before step.run().
        final = pipeline.run(initial, resume_from=1)
    finally:
        PipelineState.unregister_rebuild("resource")

    assert rebuilt_calls == [tmp_path]
    assert final.data["observed_type"] == "dict"
    assert final.data["resource"] == {"rebuilt": True, "workspace": str(tmp_path)}


def test_strip_unpicklable_emits_marker_with_type_name() -> None:
    """``_strip_unpicklable`` records the original type name in the marker."""
    state = PipelineState(run_id="strip-1", data={"k": lambda: None, "n": 7})
    stripped = _strip_unpicklable(state)
    assert isinstance(stripped.data["k"], UnpicklableMarker)
    assert stripped.data["k"].type_name == "function"
    assert stripped.data["n"] == 7
