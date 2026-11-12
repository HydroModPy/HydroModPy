"""The workflow journal."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import JournalError
from hydromodpy.workflow.record.journal import WorkflowJournal, WorkflowStepRow

# --- test_journal ---
# Unit tests for the step journal of a run directory.


@pytest.fixture
def journal(tmp_path: Path) -> WorkflowJournal:
    return WorkflowJournal(tmp_path)


def test_finish_with_unknown_status_raises(journal: WorkflowJournal) -> None:
    step_id = journal.start_step(
        run_id="r1",
        step_order=0,
        step_name="resolve",
        inputs_hash=None,
    )
    with pytest.raises(JournalError):
        journal.finish_step(step_id=step_id, status="bogus")


def test_finish_unknown_step_id_raises(journal: WorkflowJournal) -> None:
    with pytest.raises(JournalError):
        journal.finish_step(step_id="not-a-uuid", status="completed")


def test_compute_outputs_hash_directory_changes_when_content_changes(tmp_path: Path) -> None:
    workspace = tmp_path
    folder = workspace / "store.zarr"
    folder.mkdir()
    (folder / "data.bin").write_bytes(b"hello")
    h1 = WorkflowJournal.compute_outputs_hash(workspace, ("store.zarr",))
    (folder / "data.bin").write_bytes(b"world")
    h2 = WorkflowJournal.compute_outputs_hash(workspace, ("store.zarr",))
    assert h1 != h2


def test_compute_outputs_hash_missing_path_still_hashes(tmp_path: Path) -> None:
    h = WorkflowJournal.compute_outputs_hash(tmp_path, ("does/not/exist",))
    assert isinstance(h, str)
    assert len(h) == 64


def test_row_dataclass_is_frozen() -> None:
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
    with pytest.raises(Exception):
        row.status = "completed"  # type: ignore[misc]
