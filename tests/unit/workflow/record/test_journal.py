"""The step journal of a run directory: one row per step, with a status and an outputs hash."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import JournalError
from hydromodpy.workflow.record.journal import WorkflowJournal, WorkflowStepRow


@pytest.fixture
def journal(tmp_path: Path) -> WorkflowJournal:
    return WorkflowJournal(tmp_path)


def test_outputs_hash_follows_folder_content(tmp_path: Path) -> None:
    folder = tmp_path / "store.zarr"
    folder.mkdir()
    (folder / "data.bin").write_bytes(b"hello")
    before = WorkflowJournal.compute_outputs_hash(tmp_path, ("store.zarr",))
    (folder / "data.bin").write_bytes(b"world")
    after = WorkflowJournal.compute_outputs_hash(tmp_path, ("store.zarr",))
    assert before != after


def test_outputs_hash_of_a_missing_path(tmp_path: Path) -> None:
    digest = WorkflowJournal.compute_outputs_hash(tmp_path, ("does/not/exist",))
    assert len(digest) == 64


def test_row_is_frozen() -> None:
    row = WorkflowStepRow(
        step_id="s",
        run_id="r",
        step_order=0,
        step_name="resolve",
        status="running",
        inputs_hash=None,
        outputs_hash=None,
        artifact_uris=(),
        started_at=None,
        ended_at=None,
        duration_s=None,
        error_message=None,
    )
    with pytest.raises(AttributeError):
        row.status = "completed"  # type: ignore[misc]


def test_refusals(journal: WorkflowJournal) -> None:
    step_id = journal.start_step(run_id="r1", step_order=0, step_name="resolve", inputs_hash=None)
    with pytest.raises(JournalError):
        journal.finish_step(step_id=step_id, status="bogus")
    with pytest.raises(JournalError):
        journal.finish_step(step_id="not-a-uuid", status="completed")
