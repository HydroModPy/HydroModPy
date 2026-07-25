"""Machine-wide global index federating N HydroModPy workspaces.

The global index lives at ``<state_dir>/hydromodpy/index.duckdb`` and keeps
a single table ``workspaces`` of registered workspace URIs. On
:meth:`GlobalIndex.refresh_federation` it ATTACHes each registered
project index database in READ_ONLY mode and rebuilds the federated
view ``all_simulations``. Cross-workspace queries then hit the federated
view from one process without copying any data.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

import duckdb
import pandas as pd
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.io.db_retry import _is_lock_contention, connect_with_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.migrations import ensure_schema as _ensure_index_schema
from hydromodpy.core.state.paths import (
    INDEX_FILENAME,
    catalog_path_for,
    resolve_workspace,
    state_dir,
)

_CONTENDED_RETRIES = 5
_CONTENDED_BACKOFF = 0.05
_CONTENDED_MAX_BACKOFF = 0.5

if TYPE_CHECKING:
    from typing import Self

logger = get_logger(__name__)

_FTS_TABLE = "_fts_simulations"
_FTS_DOC_COLUMN = "description"


def _default_index_path() -> Path:
    return state_dir() / INDEX_FILENAME


def _quote_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _alias_from_workspace_id(workspace_id: str) -> str:
    short = re.sub(r"[^A-Za-z0-9]", "", str(workspace_id))[:8].lower()
    if not short:
        short = "ws"
    return f"w_{short}"


def _resolve_local_path(workspace_uri: str) -> Path:
    return resolve_workspace(workspace_uri)


class WorkspaceRecord(BaseModel):
    """One row of the ``workspaces`` table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str
    workspace_uri: str
    label: str | None
    last_scanned_at: datetime | None
    created_at: datetime


class GlobalIndex:
    """Machine-wide global index over N project index databases.

    Parameters
    ----------
    db_path
        Optional override for the index DuckDB file. Defaults to
        ``<state_dir>/hydromodpy/index.duckdb`` where ``state_dir`` honors
        ``XDG_STATE_HOME`` and falls back to ``~/.local/state``.
    read_only
        Open the index in read-only mode. ``register_workspace``,
        ``unregister_workspace``, ``forget``, and ``prune`` will then raise
        :class:`RuntimeError`. ``search``, ``find`` and ``list_workspaces``
        keep working without holding the write-lock. When the default
        write-lock acquisition is contended for more than a few seconds the
        constructor logs a warning and silently falls back to this mode.
    refresh_federation
        Attach registered workspace catalogs and rebuild ``all_simulations``
        during construction. Disable this for metadata-only writes.

    Raises
    ------
    duckdb.IOException
        If the index database cannot be opened for reasons other than lock
        contention.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> idx = hmp.index()
    >>> idx.register_workspace("~/hmp_workspace", label="default")
    >>> idx.find(solver="modflow_nwt")
    """

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        read_only: bool = False,
        refresh_federation: bool = True,
    ) -> None:
        self._db_path: Path = (
            Path(db_path).expanduser().resolve() if db_path is not None else _default_index_path()
        )
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._read_only: bool = bool(read_only)
        if self._read_only and not self._db_path.is_file():
            self._bootstrap_empty_db()
        self._conn: duckdb.DuckDBPyConnection = self._open_connection()
        if not self._read_only:
            _ensure_index_schema(self._conn)
        self._attached_aliases: set[str] = set()
        self._fts_loaded: bool = False
        self._ensure_fts_extension()
        if refresh_federation:
            self.refresh_federation()

    def _bootstrap_empty_db(self) -> None:
        """Create an empty DuckDB file with the index schema for read-only use."""
        try:
            conn = duckdb.connect(str(self._db_path))
            try:
                _ensure_index_schema(conn)
            finally:
                conn.close()
        except duckdb.IOException as exc:
            if not _is_lock_contention(exc):
                raise

    def _open_connection(self) -> duckdb.DuckDBPyConnection:
        """Open the index DuckDB connection honoring ``read_only``.

        When write mode is requested, a short retry window is allowed. If the
        write-lock is still contended after ``_CONTENDED_RETRIES`` attempts
        we fall back to read-only so callers performing pure reads (``search``,
        ``find``, ``list_workspaces``) stay responsive instead of blocking for
        the default exponential backoff.
        """
        if self._read_only:
            return duckdb.connect(str(self._db_path), read_only=True)
        try:
            return connect_with_retry(
                str(self._db_path),
                retries=_CONTENDED_RETRIES,
                backoff=_CONTENDED_BACKOFF,
                max_backoff=_CONTENDED_MAX_BACKOFF,
            )
        except duckdb.IOException as exc:
            if not _is_lock_contention(exc):
                raise
            logger.warning(
                "Global index write-lock contended for >5s at %s; "
                "falling back to read-only snapshot. "
                "Run 'hmp index register'/'forget'/'prune' from a single process.",
                self._db_path,
            )
            self._read_only = True
            return duckdb.connect(str(self._db_path), read_only=True)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Underlying DuckDB connection."""
        return self._conn

    @property
    def read_only(self) -> bool:
        """Whether the index was opened in read-only mode."""
        return self._read_only

    def _check_writable(self, op: str) -> None:
        """Raise when a mutation is attempted on a read-only handle."""
        if self._read_only:
            raise RuntimeError(
                f"GlobalIndex is open in read-only mode; '{op}' requires write access. "
                "Close other 'hmp' processes holding the index, then reopen."
            )

    def close(self) -> None:
        """Detach attached workspaces and close the connection."""
        for alias in list(self._attached_aliases):
            try:
                self._conn.execute(f"DETACH {_quote_identifier(alias)}")
            except duckdb.Error:
                pass
        self._attached_aliases.clear()
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def register_workspace(self, uri: str, label: str | None = None) -> str:
        """Register one workspace by URI, return its workspace_id.

        Parameters
        ----------
        uri
            Workspace URI accepted by :func:`resolve_workspace`. Local
            directories work as plain paths.
        label
            Optional human-readable label persisted next to the registration.

        Returns
        -------
        str
            Generated workspace UUID.

        Raises
        ------
        RuntimeError
            If the index was opened in read-only mode.
        """
        workspace_id = self._insert_workspace_record(uri, label)
        self.refresh_federation()
        return workspace_id

    def _insert_workspace_record(self, uri: str, label: str | None = None) -> str:
        """Insert one workspace row without rebuilding federation views."""
        self._check_writable("register_workspace")
        row = self._conn.execute(
            "INSERT INTO workspaces (workspace_uri, label) VALUES (?, ?) RETURNING workspace_id",
            [uri, label],
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Failed to register workspace {uri!r}")
        return str(row[0])

    def unregister_workspace(self, workspace_id: str) -> None:
        """Remove one workspace from the registry.

        Parameters
        ----------
        workspace_id
            UUID returned by :meth:`register_workspace`.

        Raises
        ------
        RuntimeError
            If the index was opened in read-only mode.
        """
        self._check_writable("unregister_workspace")
        self._conn.execute("DELETE FROM workspaces WHERE workspace_id = ?", [workspace_id])
        self.refresh_federation()

    def forget(self, workspace_id: str) -> None:
        """Alias of :meth:`unregister_workspace`.

        Parameters
        ----------
        workspace_id
            UUID returned by :meth:`register_workspace`.
        """
        self.unregister_workspace(workspace_id)

    def list_workspaces(self) -> list[WorkspaceRecord]:
        """Return every registered workspace as a typed record.

        Returns
        -------
        list[WorkspaceRecord]
            Records ordered by ``created_at`` and ``workspace_uri``.
        """
        rows = self._conn.execute(
            """
            SELECT workspace_id, workspace_uri, label, last_scanned_at, created_at
            FROM workspaces
            ORDER BY created_at, workspace_uri
            """
        ).fetchall()
        records: list[WorkspaceRecord] = []
        for row in rows:
            records.append(
                WorkspaceRecord(
                    workspace_id=str(row[0]),
                    workspace_uri=str(row[1]),
                    label=str(row[2]) if row[2] is not None else None,
                    last_scanned_at=row[3],
                    created_at=row[4],
                )
            )
        return records

    def prune(self) -> list[str]:
        """Remove workspaces whose index database no longer exists.

        Returns
        -------
        list[str]
            Workspace UUIDs that were removed from the index.

        Raises
        ------
        RuntimeError
            If the index was opened in read-only mode.
        """
        self._check_writable("prune")
        removed: list[str] = []
        for record in self.list_workspaces():
            catalog_path = catalog_path_for(_resolve_local_path(record.workspace_uri))
            if not catalog_path.is_file():
                self._conn.execute(
                    "DELETE FROM workspaces WHERE workspace_id = ?", [record.workspace_id]
                )
                removed.append(record.workspace_id)
        if removed:
            self.refresh_federation()
        return removed

    def refresh_federation(self) -> None:
        """Detach previous workspaces, ATTACH each registered one READ_ONLY,
        and rebuild the federated view ``all_simulations``.

        In read-only mode the view rebuild and FTS index refresh are skipped
        because they would mutate the index DB. Federation still works by
        re-ATTACHing the per-workspace catalogs and exposing them under
        ``all_simulations`` as a temporary view tied to the connection.
        """
        for alias in list(self._attached_aliases):
            try:
                self._conn.execute(f"DETACH {_quote_identifier(alias)}")
            except duckdb.Error:
                pass
        self._attached_aliases.clear()

        attached_parts: list[tuple[str, str]] = []
        for record in self.list_workspaces():
            catalog_path = catalog_path_for(_resolve_local_path(record.workspace_uri))
            if not catalog_path.is_file():
                logger.warning(
                    "Skipping workspace %s: catalog file missing at %s",
                    record.workspace_id,
                    catalog_path,
                )
                continue
            alias = _alias_from_workspace_id(record.workspace_id)
            try:
                self._conn.execute(
                    f"ATTACH {_quote_literal(catalog_path)} AS {_quote_identifier(alias)} "
                    "(READ_ONLY)"
                )
            except duckdb.Error as exc:
                logger.warning(
                    "Failed to attach workspace %s at %s: %s",
                    record.workspace_id,
                    catalog_path,
                    exc,
                )
                continue
            self._attached_aliases.add(alias)
            # Federate via ``v_simulation_summary`` (joins solver/status text
            # codes from the dim tables, so ``find(solver=...)`` filters on
            # actual values). Workspaces without the view are skipped.
            if self._table_exists(alias, "v_simulation_summary"):
                attached_parts.append((alias, record.workspace_id))
            else:
                logger.info(
                    "Workspace %s has no 'v_simulation_summary' view; skipping in federation",
                    record.workspace_id,
                )

        view_kw = "TEMPORARY VIEW" if self._read_only else "VIEW"
        try:
            self._conn.execute(f"DROP {view_kw} IF EXISTS all_simulations")
        except duckdb.Error:
            # Read-only sessions sometimes refuse DROP on non-temporary views;
            # CREATE OR REPLACE below handles the rebuild.
            pass
        if attached_parts:
            unions = []
            for alias, workspace_id in attached_parts:
                unions.append(
                    f"SELECT {_quote_literal(workspace_id)} AS workspace_id, t.* "
                    f"FROM {_quote_identifier(alias)}.v_simulation_summary AS t"
                )
            self._conn.execute(
                f"CREATE OR REPLACE {view_kw} all_simulations AS " + " UNION ALL ".join(unions)
            )
        if not self._read_only:
            self._maybe_refresh_fts()

    def find(
        self,
        *,
        scientific_objective: str | None = None,
        solver: str | None = None,
        status: str | None = None,
        name_like: str | None = None,
        **filters: object,
    ) -> pd.DataFrame:
        """Run a federated SELECT against ``all_simulations`` with keyword filters.

        Parameters
        ----------
        scientific_objective, solver, status
            Optional equality filters on the matching text columns.
        name_like
            Optional ``LIKE`` pattern on ``name`` (``%`` / ``_`` wildcards).
        filters
            Extra filters keyed by column name. A bare ``col=v`` is equality; a
            suffixed key applies a comparison: ``col_gt`` (>), ``col_gte`` (>=),
            ``col_lt`` (<), ``col_lte`` (<=), ``col_like`` (LIKE). So
            ``find(nse_gt=0.8, status="completed", name_like="cheze%")`` is the
            federated counterpart of the per-workspace ``find``. Unknown columns
            are silently skipped. Trashed runs are hidden unless ``status`` is
            given explicitly.

        Returns
        -------
        pandas.DataFrame
            Federated rows. Empty when the view is not yet built.
        """
        if not self._has_view("all_simulations"):
            return pd.DataFrame()

        available = self._view_columns("all_simulations")
        clauses: list[str] = []
        params: list[object] = []

        def add_eq(column: str, value: object | None) -> None:
            if value is not None and column in available:
                clauses.append(f"{_quote_identifier(column)} = ?")
                params.append(value)

        add_eq("scientific_objective", scientific_objective)
        add_eq("solver", solver)
        add_eq("status", status)
        if name_like is not None and "name" in available:
            clauses.append("name LIKE ?")
            params.append(name_like)

        operators = {"_gte": ">=", "_lte": "<=", "_gt": ">", "_lt": "<", "_like": "LIKE"}
        for key, value in filters.items():
            column, op = key, "="
            for suffix, sql_op in operators.items():
                if key.endswith(suffix) and len(key) > len(suffix):
                    column, op = key[: -len(suffix)], sql_op
                    break
            if column not in available:
                logger.debug("Unknown filter column %s; skipping", column)
                continue
            clauses.append(f"{_quote_identifier(column)} {op} ?")
            params.append(value)

        # Hide trashed runs unless a status filter explicitly selects them.
        if status is None and "status" in available:
            clauses.append("status <> 'trashed'")

        sql = "SELECT * FROM all_simulations"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return self._conn.execute(sql, params).fetchdf()

    def search(self, term: str) -> pd.DataFrame:
        """Full-text search across simulation descriptions via DuckDB FTS.

        Parameters
        ----------
        term
            Query expression accepted by DuckDB BM25 matching.

        Returns
        -------
        pandas.DataFrame
            Matched rows. Empty when the FTS extension or index is unavailable.
        """
        if not self._has_view("all_simulations"):
            return pd.DataFrame()
        if _FTS_DOC_COLUMN not in self._view_columns("all_simulations"):
            return pd.DataFrame()
        if not self._fts_index_exists():
            return pd.DataFrame()
        sql = (
            "SELECT a.* FROM all_simulations a "
            f"JOIN {_FTS_TABLE} f ON a.sim_id = f.sim_id "
            f"WHERE fts_main_{_FTS_TABLE}.match_bm25(f.sim_id, ?) IS NOT NULL"
        )
        try:
            return self._conn.execute(sql, [term]).fetchdf()
        except duckdb.Error as exc:
            logger.warning("FTS search failed: %s", exc)
            return pd.DataFrame()

    def _ensure_fts_extension(self) -> None:
        try:
            self._conn.execute("INSTALL fts")
            self._conn.execute("LOAD fts")
            self._fts_loaded = True
        except duckdb.Error as exc:
            logger.warning("DuckDB fts extension unavailable: %s", exc)
            self._fts_loaded = False

    def _maybe_refresh_fts(self) -> None:
        if not self._fts_loaded:
            return
        if not self._has_view("all_simulations"):
            self._conn.execute(f"DROP TABLE IF EXISTS {_FTS_TABLE}")
            return
        if _FTS_DOC_COLUMN not in self._view_columns("all_simulations"):
            self._conn.execute(f"DROP TABLE IF EXISTS {_FTS_TABLE}")
            return
        self._conn.execute(f"DROP TABLE IF EXISTS {_FTS_TABLE}")
        self._conn.execute(
            f"CREATE TABLE {_FTS_TABLE} AS "
            f"SELECT sim_id, {_quote_identifier(_FTS_DOC_COLUMN)} AS {_FTS_DOC_COLUMN} "
            "FROM all_simulations"
        )
        try:
            self._conn.execute(
                f"PRAGMA create_fts_index('{_FTS_TABLE}', 'sim_id', '{_FTS_DOC_COLUMN}', "
                "overwrite=1, stemmer='porter')"
            )
        except duckdb.Error as exc:
            logger.debug("Could not build FTS index: %s", exc)

    def _fts_index_exists(self) -> bool:
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM information_schema.schemata "
                f"WHERE schema_name = 'fts_main_{_FTS_TABLE}'"
            ).fetchone()
            return bool(row and int(row[0]) > 0)
        except duckdb.Error:
            return False

    def _table_exists(self, alias: str, table: str) -> bool:
        try:
            self._conn.execute(
                f"SELECT 1 FROM {_quote_identifier(alias)}.{_quote_identifier(table)} LIMIT 0"
            )
            return True
        except duckdb.Error:
            return False

    def _has_view(self, name: str) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [name],
        ).fetchone()
        return bool(row and int(row[0]) > 0)

    def _view_columns(self, name: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [name],
        ).fetchall()
        return {str(r[0]) for r in rows}


def _generate_workspace_id() -> str:
    """Deterministic helper kept for tests if needed."""
    return str(uuid.uuid4())


def _auto_register_enabled() -> bool:
    """Return False when workspace auto-registration is explicitly disabled."""
    raw = os.environ.get("HMP_AUTO_REGISTER_WORKSPACE")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def auto_register_workspace(
    workspace_root: Path | str,
    *,
    label: str | None = None,
) -> str | None:
    """Best-effort register ``workspace_root`` in the machine-wide global index.

    Idempotent thanks to the ``UNIQUE (workspace_uri)`` constraint on the
    ``workspaces`` table: a duplicate registration is silently ignored. Any
    other failure (read-only fallback, missing state dir, IO error) is logged
    at DEBUG and swallowed so the surrounding workflow keeps running.

    Parameters
    ----------
    workspace_root
        Local directory of the workspace to register. The string form is
        stored as the ``workspace_uri``.
    label
        Optional human-readable label persisted next to the registration.

    Returns
    -------
    str | None
        Newly assigned ``workspace_id`` on first registration, ``None`` when
        the URI already existed or when the index could not be opened.
    """
    uri = str(Path(workspace_root))
    if not _auto_register_enabled():
        logger.debug("Workspace auto-registration disabled by HMP_AUTO_REGISTER_WORKSPACE=0")
        return None
    try:
        with GlobalIndex(refresh_federation=False) as index:
            if index.read_only:
                logger.debug(
                    "Global index opened read-only; skipping auto-registration of %s",
                    uri,
                )
                return None
            try:
                return index._insert_workspace_record(uri, label=label)
            except duckdb.ConstraintException:
                logger.debug("Workspace %s already registered in the global index", uri)
                return None
    except Exception as exc:
        logger.debug("Auto-registration of %s in the global index failed: %s", uri, exc)
        return None


__all__ = ["GlobalIndex", "WorkspaceRecord", "auto_register_workspace"]
