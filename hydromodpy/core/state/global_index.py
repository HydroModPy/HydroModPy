"""Machine-wide global index federating N HydroModPy projects.

The global index lives at ``<state_dir>/hydromodpy/index.duckdb`` and keeps a
single table ``projects``. One row is one **project root**, because a project
root is what holds the index database the federation reads:
``<project>/.hmp/index.duckdb``. A workspace root holds the shared ``data/``
tree and a ``projects/`` directory but no index database of its own, so it is
never a row: registering a workspace root **expands** to the project roots it
contains, one row each.

:meth:`GlobalIndex.register` owns that admission rule, and
:func:`auto_register_projects` goes through it, so the manual and the automatic
path never disagree on what a directory means. The rule reads a directory, not
a promise about its contents: a workspace root expands, and any other existing
directory is one project root whether or not it already carries
``project.toml`` or its index database. That last clause is load-bearing, since
the workflow registers its project root during setup, before the run has
written either file. A path that does not exist is refused.

On :meth:`GlobalIndex.refresh_federation` every registered project index is
ATTACHed READ_ONLY and the federated view ``all_simulations`` is rebuilt. A
project whose index database is not there yet is skipped with a warning until
its first run creates it, and :meth:`GlobalIndex.prune` drops the rows whose
database is gone for good. Cross-project queries then hit that view from one
process without copying any data.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

import duckdb
import pandas as pd
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.io.db_retry import _is_lock_contention, connect_with_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.migrations import INDEX_COMPONENT, SchemaIntegrityError
from hydromodpy.core.state.migrations import discover_migrations as _discover_index_migrations
from hydromodpy.core.state.migrations import ensure_schema as _ensure_index_schema
from hydromodpy.core.state.paths import (
    INDEX_FILENAME,
    catalog_path_for,
    project_roots_under,
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


def _alias_from_project_id(project_id: str) -> str:
    short = re.sub(r"[^A-Za-z0-9]", "", str(project_id))[:8].lower()
    if not short:
        short = "prj"
    return f"p_{short}"


def _resolve_local_path(project_uri: str) -> Path:
    return resolve_workspace(project_uri)


def _project_roots_to_register(uri: str) -> list[Path]:
    """Return the project roots ``uri`` stands for, or refuse a path that is not there.

    Single admission rule for the registry, manual and automatic paths alike,
    and one filesystem walk to answer it: :func:`project_roots_under` expands a
    workspace root into the projects it holds, possibly none on a fresh
    scaffold, and takes any other directory for a single project root. Marker
    files are deliberately not required, because the workflow registers its
    project root during setup, before the run writes ``project.toml`` or the
    index database; demanding one there would drop the registration in silence.
    A path that does not exist is the one case a filesystem can honestly call a
    mistake, so it is the one case refused.
    """
    local = Path(_resolve_local_path(uri)).expanduser().resolve()
    if not local.is_dir():
        raise FileNotFoundError(f"Cannot register {uri!r}: {local} is not an existing directory.")
    return project_roots_under(local)


class ProjectRecord(BaseModel):
    """One row of the ``projects`` table: one registered project root."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    project_uri: str
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
        Open the index in read-only mode. ``register``, ``unregister`` and
        ``prune`` will then raise :class:`RuntimeError`. ``search``, ``find``
        and ``list_projects`` keep working without holding the write-lock.
        When the default write-lock acquisition is contended for more than a
        few seconds the constructor logs a warning and silently falls back to
        this mode.
    refresh_federation
        Attach the registered project catalogs and rebuild ``all_simulations``
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
    >>> idx.register("~/hmp_workspace", label="default")
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
        if self._read_only:
            self._warn_if_schema_is_stale()
        else:
            self._ensure_schema_or_rebuild()
        self._attached_aliases: set[str] = set()
        self._fts_loaded: bool = False
        self._ensure_fts_extension()
        if refresh_federation:
            self.refresh_federation()

    def _ensure_schema_or_rebuild(self) -> None:
        """Migrate the index, rebuilding it when its schema ledger disagrees.

        The global index holds one registry of project roots and federates
        live: everything else it can show is read through the project catalogs
        it attaches. So a schema it cannot migrate is not a loss to protect but
        a file to redo, and refusing to boot on a stale checksum leaves every
        federated query answering from a database nobody can write to.

        The registered URIs are carried over, since they are the only rows the
        rebuild cannot read back from anywhere else.
        """
        try:
            _ensure_index_schema(self._conn)
            return
        except SchemaIntegrityError as exc:
            logger.warning(
                "Global index at %s carries a schema this version cannot migrate (%s); "
                "rebuilding it and keeping the registered projects.",
                self._db_path,
                exc,
            )
        salvaged = self._salvage_project_rows()
        self._conn.close()
        self._db_path.unlink(missing_ok=True)
        self._db_path.with_name(f"{self._db_path.name}.wal").unlink(missing_ok=True)
        self._conn = self._open_connection()
        _ensure_index_schema(self._conn)
        for uri, label in salvaged:
            self._conn.execute(
                "INSERT INTO projects (project_uri, label) VALUES (?, ?) ON CONFLICT DO NOTHING",
                [uri, label],
            )
        logger.warning(
            "Global index rebuilt at %s with %d registered project(s).",
            self._db_path,
            len(salvaged),
        )

    def _warn_if_schema_is_stale(self) -> None:
        """Say so when a read-only handle opens an index it cannot migrate.

        A read-only open never migrates, so without this the federated list
        answers from whatever the old schema holds and looks healthy. The
        first writable command rebuilds the file; until then, say it out loud.
        """
        if not self._has_view("schema_migrations"):
            return
        applied = {
            int(version): str(checksum)
            for version, checksum in self._conn.execute(
                "SELECT version, checksum FROM schema_migrations WHERE component = ?",
                [INDEX_COMPONENT],
            ).fetchall()
        }
        stale = [
            migration.version
            for migration in _discover_index_migrations()
            if applied.get(migration.version) not in (None, migration.checksum)
        ]
        if stale:
            logger.warning(
                "Global index at %s was written under another schema (migration %s); "
                "what it lists is stale until a writable 'hmp' command rebuilds it.",
                self._db_path,
                ", ".join(f"{version:04d}" for version in stale),
            )

    def _salvage_project_rows(self) -> list[tuple[str, str | None]]:
        """Return the ``(uri, label)`` pairs the unusable index still holds.

        The schema of a file this version refuses to migrate is unknown by
        definition, so both the current ``projects`` table and the ``workspaces``
        table it replaced are tried; finding neither simply means there is
        nothing to carry over. This registry is the one piece of state no disk
        scan can rebuild, so a rebuild that silently emptied it would lose the
        only record of which projects this machine knows.
        """
        for query in (
            "SELECT project_uri, label FROM projects",
            "SELECT workspace_uri, label FROM workspaces",
        ):
            try:
                rows = self._conn.execute(query).fetchall()
            except duckdb.Error:
                continue
            return [(str(row[0]), None if row[1] is None else str(row[1])) for row in rows]
        return []

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
        ``find``, ``list_projects``) stay responsive instead of blocking for
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
                "Run 'hmp workspace register'/'forget'/'prune' from a single process.",
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
        """Detach the attached project catalogs and close the connection."""
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

    def register(self, uri: str, label: str | None = None) -> list[str]:
        """Register every project root reachable from ``uri``.

        This is the one door into the registry: :func:`auto_register_projects`
        goes through the same insertion, so an automatic and a manual
        registration answer the same for the same directory. What is
        admissible is decided here, once, and callers only format the refusal.

        What ``uri`` may be:

        - a **workspace root**, carrying ``workspace.toml`` or a ``projects/``
          directory, expands, since it holds no index database of its own: it
          contributes the project roots it holds, and a freshly scaffolded
          workspace legitimately contributes none;
        - any other existing directory becomes exactly one row, whether or not
          it already carries ``project.toml`` or ``.hmp/index.duckdb``. The
          workflow registers its project root during setup, before the run has
          written either, and a row whose database appears later is what
          :meth:`refresh_federation` skips with a warning meanwhile;
        - a path that does not exist is refused with
          :class:`FileNotFoundError`.

        URIs are stored resolved, so the same directory spelled two ways stays
        one row and re-registering a known project root is a no-op.

        Parameters
        ----------
        uri
            Workspace or project root, as a path or a ``file://`` URI accepted
            by :func:`~hydromodpy.core.state.paths.resolve_workspace`.
        label
            Optional human-readable label persisted on every inserted row.

        Returns
        -------
        list[str]
            UUIDs of the rows this call inserted, in registration order. Empty
            when everything reachable from ``uri`` was already registered, and
            for a workspace root holding no project yet.

        Raises
        ------
        RuntimeError
            If the index was opened in read-only mode.
        FileNotFoundError
            If ``uri`` does not resolve to an existing directory.
        """
        project_ids = self._insert_project_roots(uri, label=label)
        self.refresh_federation()
        return project_ids

    def _insert_project_roots(self, uri: str, *, label: str | None) -> list[str]:
        """Insert one row per project root behind ``uri``, skipping known ones."""
        self._check_writable("register")
        project_ids: list[str] = []
        for root in _project_roots_to_register(uri):
            try:
                row = self._conn.execute(
                    "INSERT INTO projects (project_uri, label) VALUES (?, ?) RETURNING project_id",
                    [str(root), label],
                ).fetchone()
            except duckdb.ConstraintException:
                logger.debug("Project %s already registered in the global index", root)
                continue
            if row is None:
                raise RuntimeError(f"Failed to register project {root}")
            project_ids.append(str(row[0]))
        return project_ids

    def unregister(self, project_id: str) -> None:
        """Remove one project from the registry.

        Parameters
        ----------
        project_id
            UUID returned by :meth:`register`.

        Raises
        ------
        RuntimeError
            If the index was opened in read-only mode.
        """
        self._check_writable("unregister")
        self._conn.execute("DELETE FROM projects WHERE project_id = ?", [project_id])
        self.refresh_federation()

    def list_projects(self) -> list[ProjectRecord]:
        """Return every registered project root as a typed record.

        Returns
        -------
        list[ProjectRecord]
            Records ordered by ``created_at`` and ``project_uri``.
        """
        rows = self._conn.execute(
            """
            SELECT project_id, project_uri, label, last_scanned_at, created_at
            FROM projects
            ORDER BY created_at, project_uri
            """
        ).fetchall()
        records: list[ProjectRecord] = []
        for row in rows:
            records.append(
                ProjectRecord(
                    project_id=str(row[0]),
                    project_uri=str(row[1]),
                    label=str(row[2]) if row[2] is not None else None,
                    last_scanned_at=row[3],
                    created_at=row[4],
                )
            )
        return records

    def prune(self) -> list[str]:
        """Remove projects whose index database no longer exists.

        Returns
        -------
        list[str]
            Project UUIDs that were removed from the index.

        Raises
        ------
        RuntimeError
            If the index was opened in read-only mode.
        """
        self._check_writable("prune")
        removed: list[str] = []
        for record in self.list_projects():
            catalog_path = catalog_path_for(_resolve_local_path(record.project_uri))
            if not catalog_path.is_file():
                self._conn.execute("DELETE FROM projects WHERE project_id = ?", [record.project_id])
                removed.append(record.project_id)
        if removed:
            self.refresh_federation()
        return removed

    def refresh_federation(self) -> None:
        """Detach previous projects, ATTACH each registered one READ_ONLY,
        and rebuild the federated view ``all_simulations``.

        In read-only mode the view rebuild and FTS index refresh are skipped
        because they would mutate the index DB. Federation still works by
        re-ATTACHing the per-project catalogs and exposing them under
        ``all_simulations`` as a temporary view tied to the connection.
        """
        for alias in list(self._attached_aliases):
            try:
                self._conn.execute(f"DETACH {_quote_identifier(alias)}")
            except duckdb.Error:
                pass
        self._attached_aliases.clear()

        attached_parts: list[tuple[str, str]] = []
        for record in self.list_projects():
            catalog_path = catalog_path_for(_resolve_local_path(record.project_uri))
            if not catalog_path.is_file():
                logger.warning(
                    "Skipping project %s: catalog file missing at %s",
                    record.project_id,
                    catalog_path,
                )
                continue
            alias = _alias_from_project_id(record.project_id)
            try:
                self._conn.execute(
                    f"ATTACH {_quote_literal(catalog_path)} AS {_quote_identifier(alias)} "
                    "(READ_ONLY)"
                )
            except duckdb.Error as exc:
                logger.warning(
                    "Failed to attach project %s at %s: %s",
                    record.project_id,
                    catalog_path,
                    exc,
                )
                continue
            self._attached_aliases.add(alias)
            # Federate via ``v_simulation_summary`` (joins solver/status text
            # codes from the dim tables, so ``find(solver=...)`` filters on
            # actual values). Projects without the view are skipped.
            if self._table_exists(alias, "v_simulation_summary"):
                attached_parts.append((alias, record.project_id))
            else:
                logger.info(
                    "Project %s has no 'v_simulation_summary' view; skipping in federation",
                    record.project_id,
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
            for alias, project_id in attached_parts:
                unions.append(
                    f"SELECT {_quote_literal(project_id)} AS project_id, t.* "
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
            federated counterpart of the per-project ``find``. Unknown columns
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


def _auto_register_enabled() -> bool:
    """Return False when project auto-registration is explicitly disabled."""
    raw = os.environ.get("HMP_AUTO_REGISTER_PROJECT")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def auto_register_projects(
    root: Path | str,
    *,
    label: str | None = None,
) -> list[str]:
    """Best-effort registration of ``root`` in the machine-wide global index.

    Shares :meth:`GlobalIndex.register`'s insertion, hence its admission rule
    and its granularity: a workspace root expands to the project roots it
    holds, any other existing directory becomes one row, and a path that is not
    there is refused. Only the federation refresh is skipped, so a concurrent
    run never attaches catalogs.

    Idempotent thanks to the ``UNIQUE (project_uri)`` constraint on the
    ``projects`` table: an already known root is silently skipped, and so is an
    index another process holds open for writing. Every remaining failure, the
    refused path included, is logged at WARNING and swallowed so the
    surrounding workflow keeps running: a project that did not make it into the
    registry makes ``hmp workspace list`` answer from stale rows, which must be
    said out loud rather than left to a debug log.

    Parameters
    ----------
    root
        Local workspace root or project root to register.
    label
        Optional human-readable label persisted on every inserted row.

    Returns
    -------
    list[str]
        UUIDs of the rows this call inserted. Empty when everything was already
        registered, when ``root`` is a workspace holding no project yet, when
        auto-registration is disabled by ``HMP_AUTO_REGISTER_PROJECT``, or when
        the registration failed.
    """
    uri = str(Path(root))
    if not _auto_register_enabled():
        logger.debug("Project auto-registration disabled by HMP_AUTO_REGISTER_PROJECT=0")
        return []
    try:
        with GlobalIndex(refresh_federation=False) as index:
            if index.read_only:
                logger.debug(
                    "Global index opened read-only; skipping auto-registration of %s",
                    uri,
                )
                return []
            return index._insert_project_roots(uri, label=label)
    except Exception as exc:
        logger.warning(
            "Could not register project %s in the global index: %s. "
            "'hmp workspace list' will not show it; run 'hmp doctor' to inspect the index.",
            uri,
            exc,
        )
        return []


__all__ = ["GlobalIndex", "ProjectRecord", "auto_register_projects"]
