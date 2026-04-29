"""Simulation lifecycle helpers (open / finalize / delete / cleanup / close).

Open Zarr handles are tracked on the facade so a ``finalize`` that packs
the live store to ``.zarr.zip`` can release them first, and so ``close``
guarantees no leaked file descriptors at workspace shutdown.
"""

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING
from uuid import UUID

from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.results.catalog_schema import PER_SIM_TABLE_NAMES, ensure_parquet_views
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


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
                logger.debug("Could not close SimulationZarr handle", exc_info=True)

    def open_zarr(self, sim_id: str | UUID) -> SimulationZarr:
        basename = self._paths.basename_for(sim_id)
        zarr_zip = self._simulations_dir / f"{basename}.zarr.zip"
        if zarr_zip.exists():
            return self._track_zarr_handle(SimulationZarr(zarr_zip))
        return self._track_zarr_handle(SimulationZarr(self._simulations_dir / f"{basename}.zarr"))

    def _open_zarr_group(self, sim_id: str | UUID, *, mode: str = "r"):
        return self.open_zarr(sim_id).root

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
        self._db.execute(
            "UPDATE simulations SET status = ?, duration_s = ? WHERE sim_id = ?",
            [status, duration_s, sid],
        )

        if status == "completed":
            basename = self._paths.basename_for(sid)
            zarr_dir = self._simulations_dir / f"{basename}.zarr"
            if zarr_dir.is_dir():
                try:
                    self._close_open_zarr_handles()
                    sz = SimulationZarr(zarr_dir)
                    try:
                        sz.consolidate_metadata()
                        zip_path = sz.pack_to_zip()
                        rel = f"simulations/{zip_path.name}"
                        self._db.execute(
                            "UPDATE simulations SET zarr_path = ? WHERE sim_id = ?",
                            [rel, sid],
                        )
                    finally:
                        sz.close()
                except Exception:
                    logger.debug("Could not pack zarr to zip for sim %s", sid)

    @with_lock_retry()
    def delete(self, sim_id: str | UUID) -> None:
        sid = str(sim_id)

        row = self._db.execute(
            "SELECT zarr_path FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        # Resolve artefact paths while the row still exists so basename lookup
        # works; clearing the cache and deleting the row first would push
        # resolution onto the raw-UUID fallback and miss the real folder.
        parquet_dir = self._paths.parquet_dir_for(sid)
        self._paths.forget(sid)

        for table in PER_SIM_TABLE_NAMES:
            self._db.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])
        self._db.execute(
            "DELETE FROM calibration_iterations WHERE sim_id = ?",
            [sid],
        )
        self._db.execute("DELETE FROM simulations WHERE sim_id = ?", [sid])

        if parquet_dir.is_dir():
            shutil.rmtree(parquet_dir, ignore_errors=True)
            # Refresh views so a workspace whose last per-sim Parquet file
            # was just removed drops back to the empty-typed view form.
            ensure_parquet_views(self._db, self._workspace)

        if row and row[0]:
            zarr_abs = self._workspace / row[0]
            if zarr_abs.is_file():
                zarr_abs.unlink(missing_ok=True)
            elif zarr_abs.is_dir():
                shutil.rmtree(zarr_abs, ignore_errors=True)

    def close(self) -> None:
        self._close_open_zarr_handles()
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
