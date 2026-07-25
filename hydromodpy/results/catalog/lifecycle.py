"""Simulation lifecycle helpers (open / finalize / delete / cleanup / close).

Open Zarr handles are tracked on the facade so ``finalize`` can release them
before sealing the store, and so ``close`` guarantees no leaked file
descriptors at project shutdown. Deleting a run deletes one directory:
``runs/<name>`` holds every byte the run produced.

``finalize`` closes a completed run by sealing its directory through
:mod:`hydromodpy.results.manifest`: the run parameters, ``provenance.json``
and finally ``manifest.json``. A run directory without a manifest never
finished.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import RUNS_DIRNAME
from hydromodpy.results.catalog.audit import audited, emit_audit_event
from hydromodpy.results.catalog.constants import PER_SIM_TABLE_NAMES
from hydromodpy.results.catalog.parquet_views import ensure_parquet_views
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class PinnedRunError(Exception):
    """Raised when a destructive action targets a ``pinned`` run without force."""

    def __init__(self, sim_id: str) -> None:
        self.sim_id = sim_id
        super().__init__(f"Run {sim_id[:8]} is pinned; pass force=True (CLI --force) to act on it.")


class LifecycleMixin:
    """Open/finalize/delete/cleanup/close for :class:`Catalog`.

    Relies on the facade attributes ``self._backend`` (CatalogBackend port
    driving every SQL read/write and the transaction context manager),
    ``self._db`` (raw DuckDB connection still used by audit.emit so the
    hash chain shares the same session), ``self._workspace``,
    ``self._runs_dir``, ``self._paths``, and ``self._open_zarr_handles``.
    """

    def _track_zarr_handle(self, handle: SimulationZarr) -> SimulationZarr:
        handle._on_close = self._untrack_zarr_handle
        self._open_zarr_handles.append(handle)
        return handle

    def _untrack_zarr_handle(self, handle: SimulationZarr) -> None:
        try:
            self._open_zarr_handles.remove(handle)
        except ValueError:
            pass

    def _close_open_zarr_handles(self) -> None:
        if not self._open_zarr_handles:
            return
        while self._open_zarr_handles:
            handle = self._open_zarr_handles.pop()
            try:
                handle.close()
            except Exception:
                logger.warning("Could not close SimulationZarr handle", exc_info=True)

    def open_zarr(self, sim_id: str | UUID) -> SimulationZarr:
        fields = self._paths.fields_path_for(sim_id)
        if not fields.exists():
            fields.parent.mkdir(parents=True, exist_ok=True)
            created = SimulationZarr.create(fields, n_cells=0, n_layers=1)
            created.close()
        return self._track_zarr_handle(SimulationZarr(fields))

    def _fetch_simulation_row(self, sim_id: str) -> dict | None:
        """Return the ``simulations`` row as a plain dict for ACDD composition."""
        rows = self._backend.fetch_all(
            """SELECT s.sim_id, s.name, s.description, s.project,
                      sol.code AS solver, s.scientific_objective,
                      s.study_area_name, s.period_start, s.period_end,
                      s.time_unit, s.crs_wkt, s.crs_epsg,
                      s.bbox_xmin, s.bbox_ymin, s.bbox_xmax, s.bbox_ymax,
                      s.contact_email, s.doi, s.config_hash
                 FROM simulations s
                 LEFT JOIN solvers sol ON s.solver_id = sol.id
                WHERE s.sim_id = ?""",
            [sim_id],
        )
        if not rows:
            return None
        cols = (
            "sim_id",
            "name",
            "description",
            "project",
            "solver",
            "scientific_objective",
            "study_area_name",
            "period_start",
            "period_end",
            "time_unit",
            "crs_wkt",
            "crs_epsg",
            "bbox_xmin",
            "bbox_ymin",
            "bbox_xmax",
            "bbox_ymax",
            "contact_email",
            "doi",
            "config_hash",
        )
        return dict(zip(cols, rows[0], strict=False))

    def _fetch_runs_environment_row(self, sim_id: str) -> dict | None:
        """Return the ``runs_environment`` row as a plain dict, or None."""
        try:
            rows = self._backend.fetch_all(
                """SELECT user_name, hostname, hydromodpy_version, git_commit,
                          rng_seed, solver_binary_sha256, solver_version_text,
                          solver_name
                     FROM runs_environment
                    WHERE sim_id = ?""",
                [sim_id],
            )
        except Exception:
            return None
        if not rows:
            return None
        cols = (
            "user_name",
            "hostname",
            "hydromodpy_version",
            "git_commit",
            "rng_seed",
            "solver_binary_sha256",
            "solver_version_text",
            "solver_name",
        )
        return dict(zip(cols, rows[0], strict=False))

    def cleanup(
        self,
        *,
        status: str | None = None,
        older_than: str | None = None,
    ) -> int:
        query = (
            "SELECT s.sim_id FROM simulations s JOIN statuses st ON s.status_id = st.id WHERE 1=1"
        )
        params: list = []
        if status is not None:
            query += " AND st.code = ?"
            params.append(status)
        if older_than is not None:
            query += " AND s.created_at < ?"
            params.append(older_than)

        rows = self._backend.fetch_all(query, params)
        for (sid,) in rows:
            self.delete(str(sid))
        return len(rows)

    @audited("sim.finalize", payload_keys=("status", "duration_s"))
    @with_lock_retry()
    def finalize(
        self,
        sim_id: str | UUID,
        status: str = "completed",
        duration_s: float | None = None,
    ) -> None:
        sid = str(sim_id)
        rel_zarr_path: str | None = None
        if status == "completed":
            fields = self._paths.fields_path_for(sid)
            if fields.is_dir():
                try:
                    self._close_open_zarr_handles()
                    sz = SimulationZarr(fields)
                    try:
                        sim_row = self._fetch_simulation_row(sid)
                        runs_env = self._fetch_runs_environment_row(sid)
                        sz.write_acdd_root_attrs(
                            sim_row=sim_row,
                            runs_env=runs_env,
                        )
                        sz.consolidate_metadata()
                    finally:
                        sz.close()
                    rel_zarr_path = (
                        f"{RUNS_DIRNAME}/{self._paths.dirname_for(sid)}/{FIELDS_STORE_NAME}"
                    )
                except Exception as exc:
                    # Wrap the partial transition in a transaction and record it
                    # in the audit log: the @audited decorator only fires on a
                    # successful return, so this failure path would otherwise
                    # flip the run to 'partial' with no trail.
                    with self._backend.transaction():
                        self._backend.execute(
                            """UPDATE simulations
                                  SET status_id = (SELECT id FROM statuses WHERE code = 'partial'),
                                      duration_s = ?,
                                      ended_at = current_timestamp,
                                      updated_at = current_timestamp
                                WHERE sim_id = ?""",
                            [duration_s, sid],
                        )
                        emit_audit_event(
                            self._db,
                            event_type="sim.finalize",
                            sim_id=sid,
                            payload={"status": "partial", "error": "zarr_seal_failed"},
                        )
                    raise RuntimeError(f"Could not seal Zarr store for sim {sid}") from exc

        # Transactional block driven by the backend port (BEGIN/COMMIT/ROLLBACK
        # are routed through CatalogBackend.transaction() so the same code
        # path stays valid when the adapter changes).
        with self._backend.transaction():
            if status == "completed":
                existing = self._backend.fetch_one(
                    "SELECT scientific_objective FROM simulations WHERE sim_id = ?",
                    [sid],
                )
                if existing is not None and not existing[0]:
                    logger.debug(
                        "Simulation %s completed without a scientific_objective; "
                        "defaulting to 'unspecified'. Set one with "
                        "Catalog.write_scientific_objective() to enable ML stratification.",
                        sid[:8],
                    )
                    self._backend.execute(
                        "UPDATE simulations SET scientific_objective = 'unspecified' WHERE sim_id = ?",
                        [sid],
                    )

            if rel_zarr_path is not None:
                self._backend.execute(
                    """UPDATE simulations
                          SET status_id = (SELECT id FROM statuses WHERE code = ?),
                              duration_s = ?,
                              zarr_path = ?,
                              ended_at = current_timestamp,
                              updated_at = current_timestamp
                        WHERE sim_id = ?""",
                    [status, duration_s, rel_zarr_path, sid],
                )
            else:
                self._backend.execute(
                    """UPDATE simulations
                          SET status_id = (SELECT id FROM statuses WHERE code = ?),
                              duration_s = ?,
                              ended_at = current_timestamp,
                              updated_at = current_timestamp
                        WHERE sim_id = ?""",
                    [status, duration_s, sid],
                )

        if status == "completed":
            self._write_simulation_snapshot(sid)
            self._seal_run_directory(sid)

    def _seal_run_directory(self, sid: str) -> None:
        """Write ``parameters.parquet``, ``provenance.json`` and ``manifest.json``.

        The manifest lands last and atomically, so its presence certifies a
        complete run directory. A failure here leaves the run unsealed, which
        is exactly the signal a reader needs: log it, never mask it by
        pretending the seal exists.
        """
        from hydromodpy.results.manifest import seal_run

        try:
            seal_run(self, sid)
        except Exception as exc:
            logger.error(
                "Could not seal run directory for sim %s; it stays readable but "
                "unsealed and will not be re-indexable from disk alone: %s",
                sid[:8],
                exc,
                exc_info=True,
            )

    def _write_simulation_snapshot(self, sid: str) -> None:
        """Write a one-row ``simulation.parquet``: the index row, on disk.

        Dropped next to the per-run Parquet views. The view builder only globs
        the named views (``PARQUET_VIEW_NAMES``), so this extra file is inert.
        It is what :func:`hydromodpy.results.catalog.reindex.rebuild_index`
        reads back to restore the ``simulations`` row of this run.
        """
        try:
            tables_dir = self._paths.tables_dir_for(sid)
            tables_dir.mkdir(parents=True, exist_ok=True)
            dest_sql = (tables_dir / "simulation.parquet").as_posix().replace("'", "''")
            sid_sql = str(sid).replace("'", "''")
            self._backend.execute(
                f"COPY (SELECT * FROM simulations WHERE sim_id = '{sid_sql}') "
                f"TO '{dest_sql}' (FORMAT PARQUET)"
            )
        except Exception as exc:
            # Surface this: the run is complete but a rebuilt index will not be
            # able to see it. We do not fail finalize over a recovery aid, but
            # it must be visible, not silent.
            logger.warning(
                "Could not write the index-row snapshot for sim %s; the run will "
                "not be re-indexable from disk: %s",
                sid[:8],
                exc,
            )

    @with_lock_retry()
    def delete(
        self,
        sim_id: str | UUID,
        *,
        remove_storage: bool = True,
        audit_event_type: str = "sim.delete",
        audit_payload: dict | None = None,
    ) -> None:
        """Delete a simulation row and (optionally) its on-disk artefacts.

        With ``remove_storage`` true (the default) the hard purge is
        crash-safe: it journals the intent (``purge_journal`` phase
        ``pending`` + a ``sim.purge.begin`` audit row), removes the bytes,
        then cascade-deletes every per-sim DuckDB table and clears the
        journal in a final transaction tagged with ``audit_event_type``
        (``sim.delete`` for routine deletes, ``sim.purge`` for
        ``hmp privacy purge``). Because the simulation row survives until
        that last commit, no delete/crash sequence can leave a byte under
        ``runs/`` unreachable: any interrupted purge leaves a
        ``purge_journal`` row that :meth:`replay_purge_journal` finishes.

        With ``remove_storage`` false there is nothing on disk to orphan, so
        the cascade runs in a single transaction with one audit row.
        """
        sid = str(sim_id)
        if remove_storage:
            self._purge_with_journal(sid, audit_event_type, audit_payload)
            return

        row = self._backend.fetch_one("SELECT project FROM simulations WHERE sim_id = ?", [sid])
        project_name = row[0] if row else None
        self._paths.forget(sid)
        payload: dict = {"remove_storage": False}
        if audit_payload:
            payload.update(audit_payload)
        with self._backend.transaction():
            self._cascade_delete_rows(sid)
            emit_audit_event(
                self._db,
                event_type=audit_event_type,  # type: ignore[arg-type]
                sim_id=sid,
                project=project_name,
                payload=payload,
            )

    def _table_exists(self, table: str) -> bool:
        """Return True when ``table`` is present in the catalog schema."""
        row = self._backend.fetch_one(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
            [table],
        )
        return row is not None

    def _cascade_delete_rows(self, sid: str) -> None:
        """Delete every per-sim row (12 tables + calibration + workflow ledger).

        Caller owns the tx. ``workflow_steps`` and ``workflow_events`` key on
        ``run_id`` (the sim_id string) and are guarded by table existence since
        they may be absent on older schemas.
        """
        for table in PER_SIM_TABLE_NAMES:
            self._backend.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])
        self._backend.execute("DELETE FROM calibration_iterations WHERE sim_id = ?", [sid])
        for table in ("workflow_steps", "workflow_events"):
            if self._table_exists(table):
                self._backend.execute(f"DELETE FROM {table} WHERE run_id = ?", [sid])
        # Clear any calibration session that named this sim as its best, so the
        # purge does not leave a dangling best_sim_id (there is no DB-level FK).
        self._backend.execute(
            "UPDATE calibration_sessions SET best_sim_id = NULL, best_params_hash = NULL "
            "WHERE best_sim_id = ?",
            [sid],
        )
        self._backend.execute("DELETE FROM simulations WHERE sim_id = ?", [sid])

    def _remove_run_directory(self, run_dir: Path) -> None:
        """Idempotently remove one run directory (fields, tables, figures)."""
        if not run_dir.is_dir():
            return
        try:
            shutil.rmtree(run_dir)
        except OSError as exc:
            raise RuntimeError(f"Could not remove run directory: {run_dir}") from exc
        # Refresh views so a project whose last per-run Parquet file was just
        # removed drops back to the empty-typed view form.
        ensure_parquet_views(self._db, self._runs_dir)

    def _purge_with_journal(
        self, sid: str, audit_event_type: str, audit_payload: dict | None
    ) -> None:
        """Crash-safe two-phase hard purge (journal -> rmtree -> cascade)."""
        row = self._backend.fetch_one("SELECT project FROM simulations WHERE sim_id = ?", [sid])
        if row is None:
            # Row already gone: clear any dangling journal entry and stop.
            with self._backend.transaction():
                self._backend.execute("DELETE FROM purge_journal WHERE sim_id = ?", [sid])
            return

        # Resolve the run directory while the row still exists so the name
        # lookup works; clearing the cache first would miss the real folder.
        run_dir = self._paths.run_dir_for(sid)
        project_name = row[0]
        payload: dict = {"remove_storage": True}
        if audit_payload:
            payload.update(audit_payload)

        # Phase 1: journal the intent and commit. Row + bytes still present, so
        # a crash here leaves a restorable row plus a 'pending' journal entry.
        # ``@with_lock_retry`` on delete() can re-enter this method, so only the
        # first entry emits ``sim.purge.begin`` (the journal row is the guard).
        already_journaled = (
            self._backend.fetch_one("SELECT 1 FROM purge_journal WHERE sim_id = ?", [sid])
            is not None
        )
        with self._backend.transaction():
            self._backend.execute("DELETE FROM purge_journal WHERE sim_id = ?", [sid])
            self._backend.execute(
                "INSERT INTO purge_journal (sim_id, phase) VALUES (?, 'pending')", [sid]
            )
            if not already_journaled:
                emit_audit_event(
                    self._db,
                    event_type="sim.purge.begin",
                    sim_id=sid,
                    project=project_name,
                    payload=payload,
                )

        # Phase 2: remove the bytes (idempotent) and mark the journal.
        self._remove_run_directory(run_dir)
        with self._backend.transaction():
            self._backend.execute(
                "UPDATE purge_journal SET phase = 'rmtree_done' WHERE sim_id = ?", [sid]
            )

        # Phase 3: cascade-delete the rows and clear the journal atomically.
        self._paths.forget(sid)
        with self._backend.transaction():
            self._cascade_delete_rows(sid)
            self._backend.execute("DELETE FROM purge_journal WHERE sim_id = ?", [sid])
            emit_audit_event(
                self._db,
                event_type=audit_event_type,  # type: ignore[arg-type]
                sim_id=sid,
                project=project_name,
                payload=payload,
            )

    @with_lock_retry()
    def replay_purge_journal(self) -> list[str]:
        """Finish any interrupted hard purge. Returns the resolved sim_ids.

        Idempotent crash recovery: for every ``purge_journal`` row, remove the
        bytes (skipped when phase is already ``rmtree_done``), then cascade the
        row delete and clear the journal. Run by ``gc``.
        """
        rows = self._backend.fetch_all("SELECT CAST(sim_id AS VARCHAR), phase FROM purge_journal")
        resolved: list[str] = []
        for sid, phase in rows:
            sim_row = self._backend.fetch_one(
                "SELECT project FROM simulations WHERE sim_id = ?", [sid]
            )
            if sim_row is None:
                with self._backend.transaction():
                    self._backend.execute("DELETE FROM purge_journal WHERE sim_id = ?", [sid])
                resolved.append(sid)
                continue
            run_dir = self._paths.run_dir_for(sid)
            if phase != "rmtree_done":
                self._remove_run_directory(run_dir)
            self._paths.forget(sid)
            with self._backend.transaction():
                self._cascade_delete_rows(sid)
                self._backend.execute("DELETE FROM purge_journal WHERE sim_id = ?", [sid])
                emit_audit_event(
                    self._db,
                    event_type="sim.purge.commit",
                    sim_id=sid,
                    project=sim_row[0],
                    payload={"replayed": True},
                )
            resolved.append(sid)
        return resolved

    def _is_pinned(self, sim_id: str | UUID) -> bool:
        """Return True when ``sim_id`` carries the reserved ``pinned`` tag."""
        row = self._backend.fetch_one(
            "SELECT 1 FROM tags WHERE sim_id = ? AND tag = 'pinned'",
            [str(sim_id)],
        )
        return row is not None

    @with_lock_retry()
    def trash(self, sim_id: str | UUID, *, force: bool = False) -> None:
        """Move a simulation to the trash (status flip, no bytes moved).

        The row keeps its UUID and storage; its name is freed (saved in
        ``original_name``) so the bare name can be reused, and it stays
        listable and restorable. A ``pinned`` run is refused unless ``force``.
        """
        sid = str(sim_id)
        if self._is_pinned(sid) and not force:
            raise PinnedRunError(sid)
        row = self._backend.fetch_one(
            "SELECT name, project FROM simulations WHERE sim_id = ?", [sid]
        )
        if row is None:
            raise KeyError(f"No simulation with sim_id={sid[:8]}")
        with self._backend.transaction():
            self._backend.execute(
                "UPDATE simulations SET "
                "original_status_id = COALESCE(original_status_id, status_id), "
                "status_id = (SELECT id FROM statuses WHERE code = 'trashed'), "
                "trashed_at = current_timestamp, "
                "original_name = COALESCE(original_name, name), "
                "name = NULL, updated_at = current_timestamp "
                "WHERE sim_id = ?",
                [sid],
            )
            emit_audit_event(
                self._db,
                event_type="sim.trash",
                sim_id=sid,
                project=row[1],
                payload={"original_name": row[0]},
            )

    @with_lock_retry()
    def restore(self, sim_id: str | UUID) -> str:
        """Restore a trashed simulation, returning its (possibly versioned) name.

        If the original name was taken since, the stem is version-bumped so the
        restore never collides. The pre-trash status is restored from
        ``original_status_id`` (a ``failed`` or ``partial`` run comes back as
        such), falling back to inferring from ``ended_at`` for rows trashed
        before that column existed.
        """
        from hydromodpy.results.catalog.registration import _resolve_registration_name
        from hydromodpy.results.catalog.storage_paths import run_dirname

        sid = str(sim_id)
        row = self._backend.fetch_one(
            "SELECT original_name, project, ended_at, original_status_id, "
            "(SELECT code FROM statuses WHERE id = s.original_status_id) "
            "FROM simulations s "
            "JOIN statuses st ON s.status_id = st.id "
            "WHERE sim_id = ? AND st.code = 'trashed'",
            [sid],
        )
        if row is None:
            raise KeyError(f"No trashed simulation with sim_id={sid[:8]}")
        original_name, project, ended_at = row[0], row[1], row[2]
        original_status_id, original_status_code = row[3], row[4]
        if original_status_id is not None and original_status_code != "trashed":
            restored_status = str(original_status_code)
        else:
            restored_status = "completed" if ended_at is not None else "failed"
        with self._backend.transaction():
            final_name, name_stem, version_int, _ = _resolve_registration_name(
                self._backend, project, original_name or sid[:8], "version"
            )
            dirname = run_dirname(final_name)
            self._paths.move(sid, dirname)
            self._backend.execute(
                "UPDATE simulations SET name = ?, name_stem = ?, version_int = ?, "
                "storage_basename = ?, zarr_path = ?, "
                "original_name = NULL, trashed_at = NULL, original_status_id = NULL, "
                "status_id = (SELECT id FROM statuses WHERE code = ?), "
                "updated_at = current_timestamp WHERE sim_id = ?",
                [
                    final_name,
                    name_stem,
                    version_int,
                    dirname,
                    f"{RUNS_DIRNAME}/{dirname}/{FIELDS_STORE_NAME}",
                    restored_status,
                    sid,
                ],
            )
            emit_audit_event(
                self._db,
                event_type="sim.restore",
                sim_id=sid,
                project=project,
                payload={"name": final_name},
            )
        return final_name

    def list_trash(self) -> list[dict]:
        """Return trashed runs (id, original_name, project, trashed_at)."""
        rows = self._backend.fetch_all(
            "SELECT CAST(sim_id AS VARCHAR), original_name, project, trashed_at "
            "FROM simulations s JOIN statuses st ON s.status_id = st.id "
            "WHERE st.code = 'trashed' ORDER BY trashed_at DESC",
        )
        return [
            {"sim_id": r[0], "original_name": r[1], "project": r[2], "trashed_at": r[3]}
            for r in rows
        ]

    def empty_trash(self, *, force: bool = False) -> list[str]:
        """Hard-delete every trashed run, returning the purged sim_ids.

        Pinned runs are skipped unless ``force``. Each purge goes through the
        crash-safe two-phase :meth:`delete` (journal -> rmtree -> cascade) with
        a ``sim.purge`` commit audit. An interrupted purge is finished by
        :meth:`replay_purge_journal`.
        """
        purged: list[str] = []
        for entry in self.list_trash():
            sid = entry["sim_id"]
            if self._is_pinned(sid) and not force:
                continue
            self.delete(sid, audit_event_type="sim.purge")
            purged.append(sid)
        return purged

    # -- gc / doctor read+write helpers ------------------------------------
    # These keep the domain reads and writes inside the catalog layer so the
    # CLI gc/watch/doctor paths never issue raw DuckDB SQL or reach for
    # ``catalog.connection``.

    def list_expired_trash(self) -> list[str]:
        """Return sim_ids of trashed, non-pinned runs past the retention window."""
        from datetime import UTC, datetime, timedelta

        from hydromodpy.results.catalog.constants import TRASH_RETENTION_DAYS

        cutoff = datetime.now(UTC) - timedelta(days=TRASH_RETENTION_DAYS)
        rows = self._backend.fetch_all(
            "SELECT CAST(s.sim_id AS VARCHAR) FROM simulations s "
            "JOIN statuses st ON s.status_id = st.id "
            "LEFT JOIN tags t ON t.sim_id = s.sim_id AND t.tag = 'pinned' "
            "WHERE st.code = 'trashed' AND s.trashed_at IS NOT NULL "
            "AND s.trashed_at < ? AND t.sim_id IS NULL",
            [cutoff],
        )
        return [str(r[0]) for r in rows]

    def list_pending_purges(self) -> list[str]:
        """Return sim_ids with an interrupted hard-purge journal row."""
        rows = self._backend.fetch_all("SELECT CAST(sim_id AS VARCHAR) FROM purge_journal")
        return [str(r[0]) for r in rows]

    def list_orphan_calibration_sessions(self) -> list[str]:
        """Return session_ids whose ``best_sim_id`` no longer exists."""
        rows = self._backend.fetch_all(
            "SELECT CAST(cs.session_id AS VARCHAR) FROM calibration_sessions cs "
            "LEFT JOIN simulations s ON s.sim_id = cs.best_sim_id "
            "WHERE cs.best_sim_id IS NOT NULL AND s.sim_id IS NULL"
        )
        return [str(r[0]) for r in rows]

    def list_referenced_geographic_fingerprints(self) -> set[str]:
        """Return every geographic fingerprint still referenced by a simulation."""
        rows = self._backend.fetch_all(
            "SELECT DISTINCT geographic_fingerprint FROM simulations "
            "WHERE geographic_fingerprint IS NOT NULL"
        )
        return {str(r[0]) for r in rows}

    def list_run_dirnames(self) -> set[str]:
        """Return the directory name of every known run."""
        rows = self._backend.fetch_all(
            "SELECT storage_basename FROM simulations WHERE storage_basename IS NOT NULL"
        )
        return {str(r[0]) for r in rows}

    def list_stale_running(self, minutes: int) -> list[dict]:
        """Return running runs whose newest heartbeat is older than ``minutes``.

        Each entry has ``sim_id``, ``name``, ``created_at``, ``last_heartbeat``
        and ``age_s`` (seconds since the last heartbeat, or ``None``). The
        sidecar reconciliation (fresh sidecar means still alive) is left to the
        caller so this stays a pure catalog read.
        """
        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
        rows = self._backend.fetch_all(
            "SELECT CAST(s.sim_id AS VARCHAR), s.name, s.created_at, wh.last_heartbeat, "
            "CASE WHEN wh.last_heartbeat IS NULL THEN NULL "
            "ELSE EXTRACT(EPOCH FROM (current_timestamp - wh.last_heartbeat)) END "
            "FROM simulations s JOIN statuses st ON s.status_id = st.id "
            "LEFT JOIN v_workflow_heartbeats wh ON wh.run_id = CAST(s.sim_id AS VARCHAR) "
            "WHERE st.code = 'running' "
            "AND (wh.last_heartbeat IS NULL OR wh.last_heartbeat < ?) "
            "ORDER BY s.created_at DESC",
            [cutoff],
        )
        return [
            {
                "sim_id": r[0],
                "name": r[1],
                "created_at": r[2],
                "last_heartbeat": r[3],
                "age_s": None if r[4] is None else float(r[4]),
            }
            for r in rows
        ]

    def list_running(self) -> list[dict]:
        """Return every ``running`` run with its newest heartbeat age."""
        rows = self._backend.fetch_all(
            "SELECT CAST(s.sim_id AS VARCHAR), s.name, s.created_at, wh.last_heartbeat, "
            "CASE WHEN wh.last_heartbeat IS NULL THEN NULL "
            "ELSE EXTRACT(EPOCH FROM (current_timestamp - wh.last_heartbeat)) END "
            "FROM simulations s JOIN statuses st ON s.status_id = st.id "
            "LEFT JOIN v_workflow_heartbeats wh ON wh.run_id = CAST(s.sim_id AS VARCHAR) "
            "WHERE st.code = 'running' ORDER BY s.created_at DESC",
        )
        return [
            {
                "sim_id": r[0],
                "name": r[1],
                "created_at": r[2],
                "last_heartbeat": r[3],
                "age_s": None if r[4] is None else float(r[4]),
            }
            for r in rows
        ]

    @with_lock_retry()
    def mark_stale_running_failed(self, sim_id: str | UUID) -> None:
        """Flip a stale ``running`` run to ``failed`` (gc reaper path)."""
        sid = str(sim_id)
        with self._backend.transaction():
            self._backend.execute(
                "UPDATE simulations "
                "SET status_id = (SELECT id FROM statuses WHERE code = 'failed'), "
                "ended_at = current_timestamp, updated_at = current_timestamp "
                "WHERE sim_id = ?",
                [sid],
            )

    @with_lock_retry()
    def delete_calibration_session(self, session_id: str | UUID) -> None:
        """Delete a calibration session and its iterations in one transaction."""
        sess = str(session_id)
        with self._backend.transaction():
            self._backend.execute("DELETE FROM calibration_iterations WHERE session_id = ?", [sess])
            self._backend.execute("DELETE FROM calibration_sessions WHERE session_id = ?", [sess])

    def close(self) -> None:
        self._close_open_zarr_handles()
        self._backend.close()
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
