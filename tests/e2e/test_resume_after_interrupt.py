"""End-to-end: the pipeline resumes from a checkpoint after a crash.

A tiny four-step pipeline is built from synthetic steps that each append
their name to the state payload. The third step raises on the first
attempt; when re-run with ``resume_from=3`` the pipeline must restore
state at step 2 and execute step 3 onwards exactly once.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.pipeline.pipeline import Pipeline
from hydromodpy.pipeline.state import PipelineState


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
