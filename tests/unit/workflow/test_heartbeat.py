"""Unit tests for HeartbeatPulse background thread."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.workflow.events import WorkflowEventStream
from hydromodpy.workflow.heartbeat import HeartbeatPulse
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path: Path) -> SimulationCatalog:
    with simulation_catalog(tmp_path) as cat:
        yield cat


def _register_running_sim(catalog: SimulationCatalog, sim_id: str) -> None:
    catalog.connection.execute(
        """
        INSERT INTO simulations
            (sim_id, project, solver_id, status_id,
             zarr_path, storage_basename)
        VALUES (?, 'p1',
                (SELECT id FROM solvers WHERE code = 'modflow6'),
                (SELECT id FROM statuses WHERE code = 'running'),
                ?, ?)
        """,
        [sim_id, "simulations/x.zarr", "x"],
    )


def _read_heartbeat(catalog: SimulationCatalog, sim_id: str) -> datetime | None:
    row = catalog.connection.execute(
        "SELECT last_heartbeat FROM v_workflow_heartbeats WHERE run_id = ?",
        [sim_id],
    ).fetchone()
    if row is None or row[0] is None:
        return None
    value = row[0]
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _heartbeat_count(catalog: SimulationCatalog, sim_id: str) -> int:
    row = catalog.connection.execute(
        """
        SELECT COUNT(*)
          FROM workflow_events
         WHERE run_id = ? AND event_type = 'heartbeat'
        """,
        [sim_id],
    ).fetchone()
    return int(row[0]) if row else 0


def test_enter_sets_heartbeat_synchronously(catalog: SimulationCatalog) -> None:
    sim_id = "22222222-2222-2222-2222-222222222222"
    _register_running_sim(catalog, sim_id)
    events = WorkflowEventStream(catalog)
    before = datetime.now(UTC)
    with HeartbeatPulse(sim_id, interval_s=5.0, events=events):
        hb = _read_heartbeat(catalog, sim_id)
    assert hb is not None
    assert hb >= before - timedelta(seconds=1)


def test_loop_refreshes_within_interval(catalog: SimulationCatalog) -> None:
    sim_id = "33333333-3333-3333-3333-333333333333"
    _register_running_sim(catalog, sim_id)
    events = WorkflowEventStream(catalog)
    with HeartbeatPulse(sim_id, interval_s=0.2, events=events):
        first = _heartbeat_count(catalog, sim_id)
        time.sleep(0.6)
        second = _heartbeat_count(catalog, sim_id)
    assert first >= 1
    assert second > first


def test_exit_joins_thread_without_leak(catalog: SimulationCatalog) -> None:
    sim_id = "44444444-4444-4444-4444-444444444444"
    _register_running_sim(catalog, sim_id)
    events = WorkflowEventStream(catalog)
    pulse = HeartbeatPulse(sim_id, interval_s=0.2, events=events)
    name_prefix = f"hmp-heartbeat-{sim_id[:8]}"
    with pulse:
        time.sleep(0.05)
        alive = [t for t in threading.enumerate() if t.name == name_prefix]
        assert alive, "heartbeat thread should be running inside the context"
    leftover = [t for t in threading.enumerate() if t.name == name_prefix and t.is_alive()]
    assert leftover == []


def test_pulse_does_not_write_simulation_heartbeat_column(catalog: SimulationCatalog) -> None:
    sim_id = "66666666-6666-6666-6666-666666666666"
    _register_running_sim(catalog, sim_id)
    events = WorkflowEventStream(catalog)

    with HeartbeatPulse(sim_id, interval_s=5.0, events=events):
        pass

    cols = {
        row[1]
        for row in catalog.connection.execute("PRAGMA table_info('simulations')").fetchall()
    }
    assert "last_heartbeat" not in cols
    assert _read_heartbeat(catalog, sim_id) is not None
