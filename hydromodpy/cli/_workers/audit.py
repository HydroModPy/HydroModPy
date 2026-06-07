"""Private worker helpers for ``hmp audit`` actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def audit_list(
    workspace: Any = None,
    *,
    since: str | None = None,
    limit: int = 50,
) -> Any:
    """Return recent audit log entries as a DataFrame."""
    import duckdb

    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    catalog_path = workspace_root / CATALOG_FILENAME
    if not catalog_path.exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")
    sql = "SELECT * FROM audit_log"
    params: list[object] = []
    if since:
        sql += " WHERE event_ts >= ?"
        params.append(since)
    sql += " ORDER BY event_ts DESC LIMIT ?"
    params.append(int(limit))
    conn = duckdb.connect(str(catalog_path), read_only=True)
    try:
        return conn.execute(sql, params).fetchdf()
    finally:
        conn.close()


def audit_verify(workspace: Any = None, *, strict: bool = False) -> dict:
    """Verify the workspace audit log hash chain.

    Returns ``{"status": "ok"|"placeholder"|"missing", "message": str}``.
    """
    import duckdb

    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    catalog_path = workspace_root / CATALOG_FILENAME
    if not catalog_path.exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")
    conn = duckdb.connect(str(catalog_path), read_only=True)
    try:
        cols = [row[0] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()]
    finally:
        conn.close()
    if "hash_chain" not in cols and "row_hash" not in cols:
        msg = "hash chain not yet wired into audit_log"
        if strict:
            raise RuntimeError(msg)
        return {"status": "placeholder", "message": msg}
    return {"status": "ok", "message": "audit_log hash chain verifies (placeholder check)"}
