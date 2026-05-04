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
from hydromodpy.results.catalog_schema import PER_SIM_TABLE_NAMES, ensure_parquet_views
from hydromodpy.results.storage_contract import SIMULATIONS_DIRNAME, ZARR_SUFFIX, ZARR_ZIP_SUFFIX
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class LifecycleMixin:
    """Open/finalize/delete/cleanup/close for :class:`SimulationCatalog`.

    Relies on the facade attributes ``self._db``, ``self._workspace``,
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
        return self._track_zarr_handle(
            SimulationZarr(self._simulations_dir / f"{basename}{ZARR_SUFFIX}")
        )

    def cleanup(
        self,
        *,
        status: str | None = None,
        older_than: str | None = None,
    ) -> int:
        query = "SELECT sim_id FROM simulations WHERE 1=1"
        params: list = []
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        if older_than is not None:
            query += " AND created_at < ?"
            params.append(older_than)

        rows = self._db.execute(query, params).fetchall()
        for (sid,) in rows:
            self.delete(str(sid))
        return len(rows)

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
                        sz.consolidate_metadata()
                        zip_path = sz.pack_to_zip()
                        rel_zarr_path = f"{SIMULATIONS_DIRNAME}/{zip_path.name}"
                        zarr_packed = True
                    finally:
                        sz.close()
                except Exception as exc:
                    self._db.execute(
                        """UPDATE simulations
                              SET status = 'partial',
                                  duration_s = ?,
                                  ended_at = current_timestamp,
                                  updated_at = current_timestamp
                            WHERE sim_id = ?""",
                        [duration_s, sid],
                    )
                    raise RuntimeError(f"Could not pack Zarr store for sim {sid}") from exc

        self._db.execute("BEGIN TRANSACTION")
        try:
            if status == "completed":
                existing = self._db.execute(
                    "SELECT scientific_objective FROM simulations WHERE sim_id = ?",
                    [sid],
                ).fetchone()
                if existing is not None and not existing[0]:
                    logger.debug(
                        "Simulation %s completed without a scientific_objective; "
                        "defaulting to 'unspecified'. Set one with "
                        "Catalog.write_scientific_objective() to enable ML stratification.",
                        sid[:8],
                    )
                    self._db.execute(
                        "UPDATE simulations SET scientific_objective = 'unspecified' WHERE sim_id = ?",
                        [sid],
                    )

            if rel_zarr_path is not None:
                self._db.execute(
                    """UPDATE simulations
                          SET status = ?,
                              duration_s = ?,
                              zarr_path = ?,
                              zarr_packed = ?,
                              ended_at = current_timestamp,
                              updated_at = current_timestamp
                        WHERE sim_id = ?""",
                    [status, duration_s, rel_zarr_path, zarr_packed, sid],
                )
            else:
                self._db.execute(
                    """UPDATE simulations
                          SET status = ?,
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
    ) -> None:
        """Delete a simulation row and (optionally) its on-disk artefacts.

        Cascades the delete across every per-sim DuckDB table and removes
        the per-sim Parquet directory and Zarr store when
        ``remove_storage`` is true.
        """
        sid = str(sim_id)

        row = self._db.execute(
            "SELECT zarr_path FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        # Resolve artefact paths while the row still exists so basename lookup
        # works; clearing the cache and deleting the row first would push
        # resolution onto the raw-UUID fallback and miss the real folder.
        parquet_dir = self._paths.parquet_dir_for(sid) if remove_storage else None
        zarr_abs = self._workspace / row[0] if remove_storage and row and row[0] else None
        self._paths.forget(sid)

        self._db.execute("BEGIN TRANSACTION")
        try:
            for table in PER_SIM_TABLE_NAMES:
                self._db.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])
            self._db.execute(
                "DELETE FROM calibration_iterations WHERE sim_id = ?",
                [sid],
            )
            self._db.execute("DELETE FROM simulations WHERE sim_id = ?", [sid])
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
