"""Unit tests for the workflow_steps journal."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import JournalError
from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.workflow.journal import WorkflowJournal, WorkflowStepRow
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path: Path) -> SimulationCatalog:
    with simulation_catalog(tmp_path) as cat:
        yield cat


@pytest.fixture
def journal(catalog: SimulationCatalog) -> WorkflowJournal:
    return WorkflowJournal(catalog)


def test_start_step_inserts_row(journal: WorkflowJournal) -> None:
    step_id = journal.start_step(
        run_id="r1",
        step_order=0,
        step_name="resolve",
        inputs_hash="abc",
    )
    rows = journal.list_steps("r1")
    assert len(rows) == 1
    row = rows[0]
    assert row.step_id == step_id
    assert row.status == "running"
    assert row.step_name == "resolve"
    assert row.inputs_hash == "abc"
    assert row.outputs_hash is None
    assert row.artifact_uris == ()
    assert isinstance(row.started_at, datetime)
    assert row.ended_at is None


def test_start_step_replaces_existing_row(journal: WorkflowJournal) -> None:
    first = journal.start_step(
        run_id="r1",
        step_order=0,
        step_name="resolve",
        inputs_hash="abc",
    )
    journal.finish_step(step_id=first, status="failed", error_message="boom")
    second = journal.start_step(
        run_id="r1",
        step_order=0,
        step_name="resolve",
        inputs_hash="def",
    )
    rows = journal.list_steps("r1")
    assert len(rows) == 1
    assert rows[0].step_id == second
    assert rows[0].status == "running"
    assert rows[0].inputs_hash == "def"
    assert rows[0].error_message is None


def test_finish_completed_persists_hash_and_uris(journal: WorkflowJournal) -> None:
    step_id = journal.start_step(
        run_id="r1",
        step_order=1,
        step_name="extract",
        inputs_hash="hash-inputs",
    )
    journal.finish_step(
        step_id=step_id,
        status="completed",
        outputs_hash="hash-outputs",
        artifact_uris=("simulations/foo.zarr",),
    )
    row = journal.list_steps("r1")[0]
    assert row.status == "completed"
    assert row.outputs_hash == "hash-outputs"
    assert row.artifact_uris == ("simulations/foo.zarr",)
    assert isinstance(row.ended_at, datetime)
    assert row.duration_s is not None and row.duration_s >= 0.0
    assert row.error_message is None


def test_finish_failed_records_message(journal: WorkflowJournal) -> None:
    step_id = journal.start_step(
        run_id="r1",
        step_order=0,
        step_name="run_solver",
        inputs_hash=None,
    )
    journal.finish_step(step_id=step_id, status="failed", error_message="diverged")
    row = journal.list_steps("r1")[0]
    assert row.status == "failed"
    assert row.error_message == "diverged"


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


def test_invalidate_from_cascades(journal: WorkflowJournal) -> None:
    ids = []
    for order, name in enumerate(("resolve", "load", "mesh", "solve")):
        step_id = journal.start_step(
            run_id="r1",
            step_order=order,
            step_name=name,
            inputs_hash=None,
        )
        ids.append(step_id)
        journal.finish_step(step_id=step_id, status="completed")

    touched = journal.invalidate_from("r1", start_order=2, reason="forced")
    assert touched == 2
    rows = journal.list_steps("r1")
    assert [r.status for r in rows] == ["completed", "completed", "aborted", "aborted"]
    assert all(r.error_message == "forced" for r in rows if r.status == "aborted")


def test_legacy_simulation_heartbeat_writer_removed() -> None:
    assert not hasattr(WorkflowJournal, "update_heartbeat")


def test_compute_inputs_hash_is_deterministic_and_sensitive() -> None:
    a = WorkflowJournal.compute_inputs_hash("resolve", 0, "cfg-hash", ["prev"])
    b = WorkflowJournal.compute_inputs_hash("resolve", 0, "cfg-hash", ["prev"])
    c = WorkflowJournal.compute_inputs_hash("resolve", 0, "cfg-hash", ["other"])
    d = WorkflowJournal.compute_inputs_hash("resolve", 0, "cfg-hash2", ["prev"])
    assert a == b
    assert a != c
    assert a != d


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


def test_repeated_full_step_cycles_never_corrupt_the_unique_index(
    journal: WorkflowJournal,
) -> None:
    # Re-running the same simulation name replays the same (run_id, step_order)
    # keys run after run. Deleting and re-inserting that UNIQUE key inside one
    # transaction corrupts DuckDB's ART index after a few cycles (FATAL
    # "Failed to append to UNIQUE_workflow_steps"); the journal must therefore
    # commit the delete before the insert. Ten full cycles stay healthy.
    for cycle in range(10):
        for order in range(6):
            step_id = journal.start_step(
                run_id="chronicle",
                step_order=order,
                step_name=f"step{order}",
                inputs_hash=f"h{cycle}",
            )
            journal.finish_step(step_id=step_id, status="completed")
    rows = journal.list_steps("chronicle")
    assert len(rows) == 6
    assert all(row.status == "completed" for row in rows)
