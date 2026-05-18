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


class LifecycleMixin:
    """Open/finalize/delete/cleanup/close for :class:`SimulationCatalog`.

    Relies on the facade attributes ``self._backend`` (CatalogBackend port),
    ``self._db`` (DuckDB connection kept for explicit BEGIN/COMMIT/ROLLBACK
    blocks and the ``close`` of the owned connection), ``self._workspace``,
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
            "mf6_binary_sha256",
            "mf6_version_text",
            "solver",
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

        # Explicit BEGIN/COMMIT/ROLLBACK on self._db: the surrounding logic
        # is straightforward enough that the port's transaction() context
        # would also work, but keeping the raw commands avoids any subtle
        # behaviour change in the failure path. Inner SQL routes through
        # the backend on the same shared connection.
        self._db.execute("BEGIN TRANSACTION")
        try:
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
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

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

        Cascades the delete across every per-sim DuckDB table and removes
        the per-sim Parquet directory and Zarr store when
        ``remove_storage`` is true. Emits one ``audit_log`` row in the same
        transaction; callers (notably ``hmp privacy purge``) override
        ``audit_event_type`` to ``"sim.purge"`` to distinguish a hard purge
        from a routine delete.
        """
        sid = str(sim_id)

        row = self._backend.fetch_one(
            "SELECT zarr_path, project FROM simulations WHERE sim_id = ?",
            [sid],
        )
        # Resolve artefact paths while the row still exists so basename lookup
        # works; clearing the cache and deleting the row first would push
        # resolution onto the raw-UUID fallback and miss the real folder.
        parquet_dir = self._paths.parquet_dir_for(sid) if remove_storage else None
        zarr_abs = self._workspace / row[0] if remove_storage and row and row[0] else None
        project_name = row[1] if row else None
        self._paths.forget(sid)

        payload: dict = {"remove_storage": bool(remove_storage)}
        if audit_payload:
            payload.update(audit_payload)

        # Explicit BEGIN/COMMIT/ROLLBACK on self._db: emit_audit_event takes
        # a raw connection by design (audit.py escapes the port), so the
        # transaction is kept on the same connection. Inner data-table
        # deletes route through the backend.
        self._db.execute("BEGIN TRANSACTION")
        try:
            for table in PER_SIM_TABLE_NAMES:
                self._backend.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])
            self._backend.execute(
                "DELETE FROM calibration_iterations WHERE sim_id = ?",
                [sid],
            )
            self._backend.execute("DELETE FROM simulations WHERE sim_id = ?", [sid])
            emit_audit_event(
                self._db,
                event_type=audit_event_type,  # type: ignore[arg-type]
                sim_id=sid,
                project=project_name,
                payload=payload,
            )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

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

    def close(self) -> None:
        self._close_open_zarr_handles()
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
