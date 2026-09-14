"""Tests for the ``hmp catalog watch`` worker (running-run heartbeat health)."""

from __future__ import annotations

import uuid
from pathlib import Path

from hydromodpy.cli._workers.catalog import watch_running
from hydromodpy.results.catalog import Catalog


def _running(catalog, name: str, *, heartbeat_sql: str) -> str:
    sid = str(uuid.uuid4())
    catalog.register_simulation(sid, project="p", solver="modflow6", name=name)
    catalog._backend.execute(
        "INSERT INTO workflow_events (run_id, step_name, event_type, ts) "
        f"VALUES (?, 'pipeline', 'heartbeat', {heartbeat_sql})",
        [sid],
    )
    return sid


def test_watch_flags_stale_and_live_runs(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    with Catalog(workspace) as catalog:
        _running(catalog, "stale_run", heartbeat_sql="TIMESTAMP '2000-01-01 00:00:00+00'")
        _running(catalog, "live_run", heartbeat_sql="current_timestamp")

    rows = {r["name"]: r for r in watch_running(workspace)}
    assert rows["stale_run"]["stale"] is True
    assert rows["live_run"]["stale"] is False
    assert rows["live_run"]["age_s"] is not None


def test_watch_empty_when_nothing_running(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    with Catalog(workspace) as catalog:
        sid = str(uuid.uuid4())
        catalog.register_simulation(sid, project="p", solver="modflow6", name="done")
        catalog._backend.execute(
            "UPDATE simulations SET status_id = (SELECT id FROM statuses WHERE code = 'completed') "
            "WHERE sim_id = ?",
            [sid],
        )
    assert watch_running(workspace) == []


def test_watch_reports_from_sidecar_when_catalog_unreadable(tmp_path: Path) -> None:
    from hydromodpy.workflow.tracking.heartbeat import write_sidecar

    # No catalog on disk: watch must still surface the live run from its sidecar.
    workspace = tmp_path / "ws"
    sid = "11111111-2222-3333-4444-555555555555"
    write_sidecar(workspace, sid, run_id=sid, step_name="pipeline")

    rows = watch_running(workspace)
    assert len(rows) == 1
    assert rows[0]["sim_id"] == sid
    assert rows[0]["stale"] is False


def test_watch_fresh_sidecar_overrides_db_stale(tmp_path: Path) -> None:
    from hydromodpy.workflow.tracking.heartbeat import write_sidecar

    workspace = tmp_path / "ws"
    with Catalog(workspace) as catalog:
        sid = _running(
            catalog, "live_by_sidecar", heartbeat_sql="TIMESTAMP '2000-01-01 00:00:00+00'"
        )
    # The DB heartbeat is ancient, but a fresh sidecar proves the run is alive.
    write_sidecar(workspace, sid, run_id=sid, step_name="pipeline")

    rows = {r["sim_id"]: r for r in watch_running(workspace)}
    assert rows[sid]["stale"] is False
