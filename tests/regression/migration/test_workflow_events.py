"""Round-trip regression tests for the workflow_events migration (0004)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.migrations import ensure_schema_safe
from hydromodpy.results.catalog.migrations import (
    CATALOG_COMPONENT,
    MIGRATIONS_DIR,
    current_version,
    target_version,
)

from .conftest import copy_fixture


@pytest.mark.parametrize("stem", ["empty"])
def test_workflow_events_table_exists_after_migration(tmp_path: Path, stem: str) -> None:
    """Migration 0004 deploys ``workflow_events`` with the documented columns."""
    db_path = copy_fixture(stem, tmp_path)
    conn = duckdb.connect(str(db_path))
    try:
        ensure_schema_safe(
            conn,
            db_path=db_path,
            versions_dir=MIGRATIONS_DIR,
            component=CATALOG_COMPONENT,
        )
        assert current_version(conn) == target_version()

        cols = {row[1] for row in conn.execute("PRAGMA table_info('workflow_events')").fetchall()}
        assert {"event_id", "run_id", "step_name", "event_type", "payload", "ts"} <= cols
    finally:
        conn.close()


@pytest.mark.parametrize("stem", ["empty"])
def test_workflow_events_round_trip_insert_and_query(tmp_path: Path, stem: str) -> None:
    """Inserting an event row and reading it back returns the original payload."""
    db_path = copy_fixture(stem, tmp_path)
    conn = duckdb.connect(str(db_path))
    try:
        ensure_schema_safe(
            conn,
            db_path=db_path,
            versions_dir=MIGRATIONS_DIR,
            component=CATALOG_COMPONENT,
        )

        payload = json.dumps({"status": "completed", "duration_s": 1.5})
        conn.execute(
            "INSERT INTO workflow_events (run_id, step_name, event_type, payload) "
            "VALUES (?, ?, ?, ?)",
            ["run-1", "validate", "step_end", payload],
        )

        rows = conn.execute(
            "SELECT run_id, step_name, event_type, payload FROM workflow_events"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "run-1"
        assert rows[0][1] == "validate"
        assert rows[0][2] == "step_end"
        assert json.loads(rows[0][3]) == {"status": "completed", "duration_s": 1.5}
    finally:
        conn.close()


@pytest.mark.parametrize("stem", ["empty"])
def test_workflow_events_rejects_invalid_type(tmp_path: Path, stem: str) -> None:
    """The CHECK constraint rejects events outside the documented vocabulary."""
    db_path = copy_fixture(stem, tmp_path)
    conn = duckdb.connect(str(db_path))
    try:
        ensure_schema_safe(
            conn,
            db_path=db_path,
            versions_dir=MIGRATIONS_DIR,
            component=CATALOG_COMPONENT,
        )

        with pytest.raises(duckdb.ConstraintException):
            conn.execute(
                "INSERT INTO workflow_events (run_id, step_name, event_type) VALUES (?, ?, ?)",
                ["run-1", "validate", "unknown_event"],
            )
    finally:
        conn.close()


@pytest.mark.parametrize("stem", ["empty"])
def test_workflow_events_view_aggregates_heartbeats(tmp_path: Path, stem: str) -> None:
    """``v_workflow_heartbeats`` returns the most recent heartbeat per run."""
    db_path = copy_fixture(stem, tmp_path)
    conn = duckdb.connect(str(db_path))
    try:
        ensure_schema_safe(
            conn,
            db_path=db_path,
            versions_dir=MIGRATIONS_DIR,
            component=CATALOG_COMPONENT,
        )
        for _ in range(3):
            conn.execute(
                "INSERT INTO workflow_events (run_id, step_name, event_type) VALUES (?, ?, ?)",
                ["run-1", "pipeline", "heartbeat"],
            )
        row = conn.execute("SELECT run_id, last_heartbeat FROM v_workflow_heartbeats").fetchone()
        assert row is not None
        assert row[0] == "run-1"
        assert row[1] is not None
    finally:
        conn.close()
