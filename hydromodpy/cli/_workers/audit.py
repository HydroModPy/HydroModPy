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

    from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root

    workspace_root = resolve_project_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    catalog_path = catalog_path_for(workspace_root)
    if not catalog_path.exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")
    sql = "SELECT * FROM audit_log"
    params: list[object] = []
    if since:
        sql += " WHERE occurred_at >= ?"
        params.append(since)
    sql += " ORDER BY occurred_at DESC LIMIT ?"
    params.append(int(limit))
    conn = duckdb.connect(str(catalog_path), read_only=True)
    try:
        return conn.execute(sql, params).fetchdf()
    finally:
        conn.close()


def audit_verify(workspace: Any = None, *, strict: bool = False) -> dict:
    """Verify the workspace audit log hash chain.

    Recomputes the chain through
    :func:`hydromodpy.results.catalog.audit.verify_chain` and returns
    ``{"status": "ok"|"failed", "message": str}``. With ``strict`` a broken
    chain raises ``RuntimeError`` instead of returning a ``failed`` status.
    """
    import duckdb

    from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root
    from hydromodpy.results.catalog.audit import verify_chain

    workspace_root = resolve_project_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    catalog_path = catalog_path_for(workspace_root)
    if not catalog_path.exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")
    conn = duckdb.connect(str(catalog_path), read_only=True)
    try:
        ok = verify_chain(conn)
    finally:
        conn.close()
    if ok:
        return {"status": "ok", "message": "audit_log hash chain verifies"}
    msg = "audit_log hash chain verification FAILED"
    if strict:
        raise RuntimeError(msg)
    return {"status": "failed", "message": msg}
