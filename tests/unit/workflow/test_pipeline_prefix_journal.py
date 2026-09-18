"""The journal of a finished run describes its head, not only its tail.

The model phase of a run driven by the facade is built before the pipeline
starts, so its steps reach the rebuild branch and never went through the
journalling execute path. Without a row, a finished run journals its tail
only and a later resume has nothing telling it what the head left on disk.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.results.catalog import Catalog
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline
from hydromodpy.workflow.tracking.journal import WorkflowJournal


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


class _Terminal:
    name = "terminal"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def _rows(workspace: Path, run_id: str):
    catalog = Catalog(workspace)
    try:
        return WorkflowJournal(catalog).list_steps(run_id)
    finally:
        catalog.close()


def test_a_prebuilt_prefix_is_journalled(tmp_path: Path) -> None:
    """A step skipped because the context already carries it still gets a row."""
    steps = [_Prebuilt("head"), _Prebuilt("middle"), _Terminal()]
    pipeline = Pipeline(steps, workspace=tmp_path)
    pipeline.run(PipelineState(run_id="prebuilt"), resume_from=2, model_phase_ready=True)

    rows = _rows(tmp_path, "prebuilt")
    assert [(r.step_order, r.step_name, r.status) for r in rows] == [
        (0, "head", "completed"),
        (1, "middle", "completed"),
        (2, "terminal", "completed"),
    ]


def test_a_rebuilt_prefix_row_carries_what_the_step_declares(tmp_path: Path) -> None:
    """The row of a re-executed prefix step names its artefacts and digests them."""
    writer = _Writer("_preprocessing/head.txt")
    pipeline = Pipeline([writer, _Terminal()], workspace=tmp_path)
    pipeline.run(PipelineState(run_id="declared", data={"workspace": str(tmp_path)}), resume_from=1)

    assert writer.run_calls == 1
    head = next(row for row in _rows(tmp_path, "declared") if row.step_order == 0)
    assert head.artifact_uris == ("_preprocessing/head.txt",)
    assert head.outputs_hash and not head.outputs_hash.startswith("e3b0c44298fc1c14")


def test_a_row_written_by_a_real_execution_is_never_replaced(tmp_path: Path) -> None:
    """A resume keeps the evidence the planner verified instead of re-measuring it."""
    writer = _Writer("_preprocessing/head.txt")
    state = PipelineState(run_id="kept", data={"workspace": str(tmp_path)})
    Pipeline([writer, _Terminal()], workspace=tmp_path).run(state)
    executed = next(row for row in _rows(tmp_path, "kept") if row.step_order == 0)

    Pipeline([writer, _Terminal()], workspace=tmp_path).run(state, resume_from=1)
    resumed = next(row for row in _rows(tmp_path, "kept") if row.step_order == 0)

    assert resumed.step_id == executed.step_id
    assert resumed.started_at == executed.started_at
    assert writer.run_calls == 1


def test_the_suffix_chains_its_inputs_hash_onto_the_prefix(tmp_path: Path) -> None:
    """A resumed step hashes the same upstream sequence a full run would give it."""
    full = Pipeline([_Writer("_preprocessing/head.txt"), _Terminal()], workspace=tmp_path)
    full.run(PipelineState(run_id="full", data={"workspace": str(tmp_path)}))
    from_scratch = next(row for row in _rows(tmp_path, "full") if row.step_order == 1)

    resumed_pipeline = Pipeline(
        [_Writer("_preprocessing/head.txt"), _Terminal()],
        workspace=tmp_path,
    )
    resumed_pipeline.run(
        PipelineState(run_id="resumed", data={"workspace": str(tmp_path)}),
        resume_from=1,
    )
    resumed = next(row for row in _rows(tmp_path, "resumed") if row.step_order == 1)

    assert resumed.inputs_hash == from_scratch.inputs_hash
