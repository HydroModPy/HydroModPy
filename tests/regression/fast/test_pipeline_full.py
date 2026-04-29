"""Regression test: end-to-end pipeline execution with checkpoint + resume.

This test does not run a real MODFLOW simulation - the pipeline
orchestration is exercised through a representative synthetic workflow
that validates the contract guaranteed by ``Pipeline``:

- linear execution of an 11-step pipeline,
- checkpoint persistence between steps,
- DuckDB ledger capturing status + elapsed time,
- resume-after-crash replays only the remaining steps.

The scientific-content pipeline (``standard_steps``) is covered by the
launcher regression tests alongside this one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import StepError
from hydromodpy.workflow.internals.checkpoint import CheckpointStore
from hydromodpy.workflow.internals.ledger import StepsLedger
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline

# ---------------------------------------------------------------------------
# Synthetic 11-step workflow mirroring the canonical names of the real
# pipeline so regressions stay meaningful.
# ---------------------------------------------------------------------------

CANONICAL_NAMES = (
    "validate",
    "resolve",
    "load_data",
    "build_geographic",
    "build_mesh",
    "setup_process",
    "prepare_solver",
    "run_solver",
    "extract",
    "derive",
    "export",
)


class _NamedStep:
    def __init__(self, name: str, fn) -> None:
        self.name = name
        self._fn = fn

    def run(self, state):
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            data=dict(state.data) | self._fn(state.data),
        )


def _make_pipeline(crash_at: int | None = None):
    steps = []
    for i, name in enumerate(CANONICAL_NAMES):
        if i == crash_at:

            def _crash(data, _i=i):  # noqa: ANN001 - inner helper
                raise RuntimeError(f"synthetic crash at step {_i}")

            steps.append(_NamedStep(name, _crash))
        else:

            def _bump(data, _i=i):  # noqa: ANN001 - inner helper
                history = list(data.get("history", ()))
                history.append(_i)
                return {
                    "history": tuple(history),
                    "last_step": _i,
                }

            steps.append(_NamedStep(name, _bump))
    return steps


@pytest.mark.regression
@pytest.mark.fast
def test_pipeline_full_end_to_end(tmp_path: Path) -> None:
    """Fresh run completes all 11 canonical steps with checkpoints + ledger."""
    pipeline = Pipeline(
        _make_pipeline(),
        workspace=tmp_path,
        checkpoint=True,
    )
    state = PipelineState(run_id="full-1", data={})
    final = pipeline.run(state)

    assert final.step_name == "export"
    assert final.step_index == len(CANONICAL_NAMES) - 1
    assert final.data["history"] == tuple(range(len(CANONICAL_NAMES)))

    cp = CheckpointStore(tmp_path, "full-1")
    assert cp.completed_indices() == list(range(len(CANONICAL_NAMES)))

    with StepsLedger(tmp_path) as led:
        assert led.last_completed("full-1") == len(CANONICAL_NAMES) - 1
        rows = led.rows_for("full-1")
    assert [row[2] for row in rows] == list(CANONICAL_NAMES)
    assert all(row[3] == "completed" for row in rows)


@pytest.mark.regression
@pytest.mark.fast
def test_pipeline_crash_then_resume_converges(tmp_path: Path) -> None:
    """A mid-pipeline crash + resume yields the same final state as a clean run."""
    # Clean run for reference.
    ref_final = Pipeline(_make_pipeline(), workspace=tmp_path, checkpoint=True).run(
        PipelineState(run_id="ref", data={}),
    )

    # Crash at step 5 (setup_process), then resume with a healthy pipeline.
    crash_pipeline = Pipeline(
        _make_pipeline(crash_at=5),
        workspace=tmp_path,
        checkpoint=True,
    )
    with pytest.raises(StepError, match="synthetic crash at step 5"):
        crash_pipeline.run(PipelineState(run_id="crash", data={}))

    cp = CheckpointStore(tmp_path, "crash")
    assert cp.completed_indices() == [0, 1, 2, 3, 4]

    resumed_pipeline = Pipeline(
        _make_pipeline(),
        workspace=tmp_path,
        checkpoint=True,
    )
    resumed_final = resumed_pipeline.run(
        PipelineState(run_id="crash"),
        resume_from=5,
    )

    assert resumed_final.data["history"] == ref_final.data["history"]
    assert resumed_final.data["last_step"] == ref_final.data["last_step"]
    assert resumed_final.step_name == "export"
