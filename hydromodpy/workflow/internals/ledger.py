"""DuckDB-backed ledger of pipeline step executions.

The ledger records one row per (run_id, step_index) and tracks the
status, start/end timestamps, elapsed duration, and failure message
(if any). It is persisted at
``<workspace>/.hmp/checkpoints/steps_ledger.duckdb``.

The ledger is resilient to DuckDB being unavailable: in that case the
``StepsLedger`` operations become no-ops so the pipeline keeps running
without introspection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from hydromodpy.core.logging import get_logger


def _now() -> datetime:
    return datetime.now(UTC)


logger = get_logger(__name__)

Status = Literal["pending", "running", "completed", "failed", "skipped"]


class StepsLedger:
    """DuckDB table tracking pipeline step execution for a workspace."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        self.db_path = self.workspace / ".hmp" / "checkpoints" / "steps_ledger.duckdb"
        self._conn = None
        self._enabled = True
        self._connect()

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        import duckdb

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self.db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS steps (
                run_id        VARCHAR,
                step_index    INTEGER,
                step_name     VARCHAR,
                status        VARCHAR,
                started_at    TIMESTAMP,
                ended_at      TIMESTAMP,
                elapsed_ms    DOUBLE,
                error_message VARCHAR,
                PRIMARY KEY (run_id, step_index)
            );
            """
        )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> StepsLedger:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def start(self, run_id: str, step_index: int, step_name: str) -> None:
        if not self._enabled or self._conn is None:
            return
        self._conn.execute(
            """
            INSERT INTO steps (run_id, step_index, step_name, status, started_at)
            VALUES (?, ?, ?, 'running', ?)
            ON CONFLICT (run_id, step_index) DO UPDATE SET
                step_name = EXCLUDED.step_name,
                status = EXCLUDED.status,
                started_at = EXCLUDED.started_at,
                ended_at = NULL,
                elapsed_ms = NULL,
                error_message = NULL
            """,
            [run_id, int(step_index), step_name, _now()],
        )

    def finish(
        self,
        run_id: str,
        step_index: int,
        *,
        status: Status,
        elapsed_ms: float,
        error: str | None = None,
    ) -> None:
        if not self._enabled or self._conn is None:
            return
        self._conn.execute(
            """
            UPDATE steps SET
                status = ?,
                ended_at = ?,
                elapsed_ms = ?,
                error_message = ?
            WHERE run_id = ? AND step_index = ?
            """,
            [status, _now(), float(elapsed_ms), error, run_id, int(step_index)],
        )

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def last_completed(self, run_id: str) -> int | None:
        """Return the highest ``step_index`` that completed for ``run_id``."""
        if not self._enabled or self._conn is None:
            return None
        row = self._conn.execute(
            """
            SELECT MAX(step_index) FROM steps
            WHERE run_id = ? AND status = 'completed'
            """,
            [run_id],
        ).fetchone()
        return None if row is None or row[0] is None else int(row[0])

    def rows_for(self, run_id: str) -> list[tuple]:
        """Return ledger rows for ``run_id`` ordered by step_index."""
        if not self._enabled or self._conn is None:
            return []
        return self._conn.execute(
            """
            SELECT run_id, step_index, step_name, status,
                   started_at, ended_at, elapsed_ms, error_message
            FROM steps
            WHERE run_id = ?
            ORDER BY step_index
            """,
            [run_id],
        ).fetchall()


__all__ = ("StepsLedger", "Status")
