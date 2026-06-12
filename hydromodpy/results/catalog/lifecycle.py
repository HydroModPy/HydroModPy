"""Simulation lifecycle helpers (open / finalize / delete / cleanup / close).

Open Zarr handles are tracked on the facade so a ``finalize`` that packs
the live store to ``.zarr.zip`` can release them first, and so ``close``
guarantees no leaked file descriptors at workspace shutdown.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING
from uuid import UUID

from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.results.catalog.audit import audited, emit_audit_event
from hydromodpy.results.catalog.constants import PER_SIM_TABLE_NAMES
from hydromodpy.results.catalog.parquet_views import ensure_parquet_views
from hydromodpy.results.storage_contract import SIMULATIONS_DIRNAME, ZARR_SUFFIX, ZARR_ZIP_SUFFIX
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
    ``self._simulations_dir``, ``self._paths``, and ``self._open_zarr_handles``.
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
        basename = self._paths.basename_for(sim_id)
        zarr_zip = self._simulations_dir / f"{basename}{ZARR_ZIP_SUFFIX}"
        if zarr_zip.exists():
            return self._track_zarr_handle(SimulationZarr(zarr_zip))
        zarr_dir = self._simulations_dir / f"{basename}{ZARR_SUFFIX}"
        if not zarr_dir.exists():
            zarr_dir.parent.mkdir(parents=True, exist_ok=True)
            staged = SimulationZarr.create(zarr_dir, n_cells=0, n_layers=1)
            staged.close()
        return self._track_zarr_handle(SimulationZarr(zarr_dir))

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
        zarr_packed = False
        if status == "completed":
            basename = self._paths.basename_for(sid)
            zarr_dir = self._simulations_dir / f"{basename}{ZARR_SUFFIX}"
            if zarr_dir.is_dir():
                try:
                    self._close_open_zarr_handles()
                    sz = SimulationZarr(zarr_dir)
                    try:
                        sim_row = self._fetch_simulation_row(sid)
                        runs_env = self._fetch_runs_environment_row(sid)
                        sz.write_acdd_root_attrs(
                            sim_row=sim_row,
                            runs_env=runs_env,
                        )
                        sz.consolidate_metadata()
                        zip_path = sz.pack_to_zip()
                        rel_zarr_path = f"{SIMULATIONS_DIRNAME}/{zip_path.name}"
                        zarr_packed = True
                    finally:
                        sz.close()
                except Exception as exc:
                    self._backend.execute(
                        """UPDATE simulations
                              SET status_id = (SELECT id FROM statuses WHERE code = 'partial'),
                                  duration_s = ?,
                                  ended_at = current_timestamp,
                                  updated_at = current_timestamp
                            WHERE sim_id = ?""",
                        [duration_s, sid],
                    )
                    raise RuntimeError(f"Could not pack Zarr store for sim {sid}") from exc

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
                              zarr_packed = ?,
                              ended_at = current_timestamp,
                              updated_at = current_timestamp
                        WHERE sim_id = ?""",
                    [status, duration_s, rel_zarr_path, zarr_packed, sid],
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

    def _write_simulation_snapshot(self, sid: str) -> None:
        """Write a one-row ``simulation.parquet`` so an orphan store stays adoptable.

        Dropped next to the per-sim Parquet views. The view builder only globs
        the named views (``PARQUET_VIEW_NAMES``), so this extra file is inert.
        """
        try:
            parquet_dir = self._paths.parquet_dir_for(sid)
            parquet_dir.mkdir(parents=True, exist_ok=True)
            dest_sql = (parquet_dir / "simulation.parquet").as_posix().replace("'", "''")
            sid_sql = str(sid).replace("'", "''")
            self._backend.execute(
                f"COPY (SELECT * FROM simulations WHERE sim_id = '{sid_sql}') "
                f"TO '{dest_sql}' (FORMAT PARQUET)"
            )
        except Exception as exc:
            logger.debug("Could not write simulation snapshot for %s: %s", sid[:8], exc)

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
        ``simulations/`` unreachable: any interrupted purge leaves a
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

    def _cascade_delete_rows(self, sid: str) -> None:
        """Delete every per-sim row (12 tables + calibration). Caller owns the tx."""
        for table in PER_SIM_TABLE_NAMES:
            self._backend.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])
        self._backend.execute("DELETE FROM calibration_iterations WHERE sim_id = ?", [sid])
        self._backend.execute("DELETE FROM simulations WHERE sim_id = ?", [sid])

    def _remove_sim_storage(self, parquet_dir, zarr_abs) -> None:
        """Idempotently remove the per-sim Parquet dir and Zarr store."""
        if parquet_dir is not None and parquet_dir.is_dir():
            try:
                shutil.rmtree(parquet_dir)
            except OSError as exc:
                raise RuntimeError(f"Could not remove Parquet directory: {parquet_dir}") from exc
            # Refresh views so a workspace whose last per-sim Parquet file
            # was just removed drops back to the empty-typed view form.
            ensure_parquet_views(self._db, self._simulations_dir)
        if zarr_abs is not None:
            if zarr_abs.is_file():
                zarr_abs.unlink(missing_ok=True)
            elif zarr_abs.is_dir():
                try:
                    shutil.rmtree(zarr_abs)
                except OSError as exc:
                    raise RuntimeError(f"Could not remove Zarr directory: {zarr_abs}") from exc

    def _purge_with_journal(
        self, sid: str, audit_event_type: str, audit_payload: dict | None
    ) -> None:
        """Crash-safe two-phase hard purge (journal -> rmtree -> cascade)."""
        row = self._backend.fetch_one(
            "SELECT zarr_path, project FROM simulations WHERE sim_id = ?", [sid]
        )
        if row is None:
            # Row already gone: clear any dangling journal entry and stop.
            with self._backend.transaction():
                self._backend.execute("DELETE FROM purge_journal WHERE sim_id = ?", [sid])
            return

        # Resolve artefact paths while the row still exists so basename lookup
        # works; clearing the cache first would miss the real folder.
        parquet_dir = self._paths.parquet_dir_for(sid)
        zarr_abs = self._workspace / row[0] if row[0] else None
        project_name = row[1]
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
        self._remove_sim_storage(parquet_dir, zarr_abs)
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
                "SELECT zarr_path, project FROM simulations WHERE sim_id = ?", [sid]
            )
            if sim_row is None:
                with self._backend.transaction():
                    self._backend.execute("DELETE FROM purge_journal WHERE sim_id = ?", [sid])
                resolved.append(sid)
                continue
            parquet_dir = self._paths.parquet_dir_for(sid)
            zarr_abs = self._workspace / sim_row[0] if sim_row[0] else None
            if phase != "rmtree_done":
                self._remove_sim_storage(parquet_dir, zarr_abs)
            self._paths.forget(sid)
            with self._backend.transaction():
                self._cascade_delete_rows(sid)
                self._backend.execute("DELETE FROM purge_journal WHERE sim_id = ?", [sid])
                emit_audit_event(
                    self._db,
                    event_type="sim.purge.commit",
                    sim_id=sid,
                    project=sim_row[1],
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
        restore never collides. The status returns to ``completed`` when the run
        had finished, otherwise ``failed``.
        """
        from hydromodpy.results.catalog.registration import _resolve_registration_name

        sid = str(sim_id)
        row = self._backend.fetch_one(
            "SELECT original_name, project, ended_at FROM simulations s "
            "JOIN statuses st ON s.status_id = st.id "
            "WHERE sim_id = ? AND st.code = 'trashed'",
            [sid],
        )
        if row is None:
            raise KeyError(f"No trashed simulation with sim_id={sid[:8]}")
        original_name, project, ended_at = row[0], row[1], row[2]
        restored_status = "completed" if ended_at is not None else "failed"
        with self._backend.transaction():
            final_name, name_stem, version_int, _ = _resolve_registration_name(
                self._backend, project, original_name or sid[:8], "version"
            )
            self._backend.execute(
                "UPDATE simulations SET name = ?, name_stem = ?, version_int = ?, "
                "original_name = NULL, trashed_at = NULL, "
                "status_id = (SELECT id FROM statuses WHERE code = ?), "
                "updated_at = current_timestamp WHERE sim_id = ?",
                [final_name, name_stem, version_int, restored_status, sid],
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

    def close(self) -> None:
        self._close_open_zarr_handles()
        self._backend.close()
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
