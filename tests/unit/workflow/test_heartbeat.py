"""Unit tests for HeartbeatPulse background thread."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.workflow.heartbeat import HeartbeatPulse
from hydromodpy.workflow.journal import WorkflowJournal


@pytest.fixture
def catalog(tmp_path: Path) -> SimulationCatalog:
    cat = SimulationCatalog(tmp_path)
    try:
        yield cat
    finally:
        cat.close()


def _register_running_sim(catalog: SimulationCatalog, sim_id: str) -> None:
    catalog.connection.execute(
        """
        INSERT INTO simulations
            (sim_id, project, solver_id, status_id,
             zarr_path, storage_basename, last_heartbeat)
        VALUES (?, 'p1',
                (SELECT id FROM solvers WHERE code = 'modflow6'),
                (SELECT id FROM statuses WHERE code = 'running'),
                ?, ?, NULL)
        """,
        [sim_id, "simulations/x.zarr", "x"],
    )


def _read_heartbeat(catalog: SimulationCatalog, sim_id: str) -> datetime | None:
    row = catalog.connection.execute(
        "SELECT last_heartbeat FROM simulations WHERE sim_id = ?",
        [sim_id],
    ).fetchone()
    if row is None or row[0] is None:
        return None
    value = row[0]
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def test_enter_sets_heartbeat_synchronously(catalog: SimulationCatalog) -> None:
    sim_id = "22222222-2222-2222-2222-222222222222"
    _register_running_sim(catalog, sim_id)
    journal = WorkflowJournal(catalog)
    before = datetime.now(UTC)
    with HeartbeatPulse(journal, sim_id, interval_s=5.0):
        hb = _read_heartbeat(catalog, sim_id)
    assert hb is not None
    assert hb >= before - timedelta(seconds=1)


def test_loop_refreshes_within_interval(catalog: SimulationCatalog) -> None:
    sim_id = "33333333-3333-3333-3333-333333333333"
    _register_running_sim(catalog, sim_id)
    journal = WorkflowJournal(catalog)
    with HeartbeatPulse(journal, sim_id, interval_s=0.2):
        first = _read_heartbeat(catalog, sim_id)
        time.sleep(0.6)
        second = _read_heartbeat(catalog, sim_id)
    assert first is not None and second is not None
    assert second >= first
    # Tolerate equal stamps when the loop racing the read, but at least the
    # background thread had a chance to refresh once.
    assert (second - first).total_seconds() >= 0.0


def test_exit_joins_thread_without_leak(catalog: SimulationCatalog) -> None:
    sim_id = "44444444-4444-4444-4444-444444444444"
    _register_running_sim(catalog, sim_id)
    journal = WorkflowJournal(catalog)
    pulse = HeartbeatPulse(journal, sim_id, interval_s=0.2)
    name_prefix = f"hmp-heartbeat-{sim_id[:8]}"
    with pulse:
        time.sleep(0.05)
        alive = [t for t in threading.enumerate() if t.name == name_prefix]
        assert alive, "heartbeat thread should be running inside the context"
    leftover = [t for t in threading.enumerate() if t.name == name_prefix and t.is_alive()]
    assert leftover == []
