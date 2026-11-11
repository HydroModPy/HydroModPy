"""SimulationZarr: per-simulation Zarr v3 store (CF-1.11 + ACDD-1.3 + UGRID-1.0).

The class holds the store, its root group and its write lock. Each write is
defined once in :mod:`~hydromodpy.results.zarr_store.zarr_writer` and each read
once in :mod:`~hydromodpy.results.zarr_store.zarr_reader`, as a function that
takes the store first. The class binds them as its methods, so a signature is
written in one place. :mod:`~hydromodpy.results.zarr_store.zarr_schema` holds
the layout and the schema version, and
:mod:`~hydromodpy.results.zarr_store.zarr_finalizer` the lock address and the
metadata consolidation.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import zarr
from filelock import FileLock, Timeout
from upath import UPath

from hydromodpy.core.fields.precision import DEFAULT_FIELD_PRECISION, FieldPrecision
from hydromodpy.results.zarr_store import zarr_reader, zarr_writer
from hydromodpy.results.zarr_store.zarr_finalizer import (
    LOCK_TIMEOUT_SECONDS,
    consolidate_metadata,
    lock_path_for_store,
)
from hydromodpy.results.zarr_store.zarr_schema import (
    initialise_root,
    local_store,
    local_store_path_arg,
    open_root_strict,
)


def _file_lock_for_store(path: Path) -> FileLock:
    """Build the store lock using extended-length paths on Windows."""
    return FileLock(local_store_path_arg(lock_path_for_store(path)))


class SimulationZarr:
    """Per-simulation Zarr v3 store. Atomic, locked, CF-1.11 + ACDD-1.3.

    ``field_precision`` is the precision the time-varying fields are written
    in (see :mod:`hydromodpy.core.fields.precision`). It only governs writes:
    a store reads the same whatever precision the handle was opened with.
    """

    def __init__(
        self,
        path: Path | UPath | str,
        *,
        field_precision: FieldPrecision = DEFAULT_FIELD_PRECISION,
    ) -> None:
        self._path = Path(str(path))
        self._field_precision: FieldPrecision = field_precision
        self._on_close: Callable[[SimulationZarr], None] | None = None
        self._store: Any = local_store(self._path)
        self._root: zarr.Group | None = self._open_root_strict(read_only=False)
        self._lock: FileLock = _file_lock_for_store(self._path)

    # -- Construction --------------------------------------------------------

    @classmethod
    def create(
        cls,
        path: Path | UPath | str,
        *,
        n_cells: int,
        n_layers: int,
        cell_types: list[str] | None = None,
        geographic_fingerprint: str | None = None,
        field_precision: FieldPrecision = DEFAULT_FIELD_PRECISION,
    ) -> SimulationZarr:
        path, store, root = initialise_root(
            path,
            n_cells=n_cells,
            n_layers=n_layers,
            cell_types=cell_types,
            geographic_fingerprint=geographic_fingerprint,
        )
        instance = cls.__new__(cls)
        instance._path = path
        instance._store = store
        instance._root = root
        instance._field_precision = field_precision
        instance._on_close = None
        instance._lock = _file_lock_for_store(path)
        return instance

    def _open_root_strict(self, *, read_only: bool) -> zarr.Group:
        """Open the root group and validate the schema version."""
        return open_root_strict(self._store, read_only=read_only)

    # -- Public accessors ----------------------------------------------------

    @property
    def root(self) -> zarr.Group:
        if self._root is None:
            raise RuntimeError("SimulationZarr handle is closed")
        return self._root

    @property
    def path(self) -> Path:
        return self._path

    @property
    def field_precision(self) -> FieldPrecision:
        """Precision the time-varying fields of this handle are written in."""
        return self._field_precision

    # -- Root attributes ----------------------------------------------------

    geographic_fingerprint = property(
        zarr_reader.get_geographic_fingerprint, zarr_reader.set_geographic_fingerprint
    )
    drain_band_depth_m = property(
        zarr_reader.get_drain_band_depth, zarr_reader.set_drain_band_depth
    )

    # -- Writes, each defined once in zarr_writer ----------------------------

    write_mesh = zarr_writer.write_mesh
    write_descent = zarr_writer.write_descent
    write_criterion_cells = zarr_writer.write_criterion_cells
    write_topography = zarr_writer.write_topography
    write_time = zarr_writer.write_time
    write_crs = zarr_writer.write_crs
    write_field = zarr_writer.write_field
    write_field_stack = zarr_writer.write_field_stack
    write_budget_policy = zarr_writer.write_budget_policy
    write_static_field = zarr_writer.write_static_field
    write_forcing_timeseries = zarr_writer.write_forcing_timeseries
    write_forcing_attrs = zarr_writer.write_forcing_attrs
    write_forcing_field = zarr_writer.write_forcing_field
    write_soil_columns = zarr_writer.write_soil_columns
    write_geographic_raster = zarr_writer.write_geographic_raster
    write_lake_abacus = zarr_writer.write_lake_abacus
    write_lake_restart_state = zarr_writer.write_lake_restart_state
    harmonize_axis_references = zarr_writer.harmonize_axis_references
    write_acdd_root_attrs = zarr_writer.write_acdd_root_attrs

    # -- Reads, each defined once in zarr_reader -----------------------------

    read_field = zarr_reader.read_field
    read_field_range = zarr_reader.read_field_range
    read_time = zarr_reader.read_time
    read_forcing_timeseries = zarr_reader.read_forcing_timeseries
    read_geographic_raster = zarr_reader.read_geographic_raster
    read_lake_abacus = zarr_reader.read_lake_abacus
    lake_abacus_lakes = zarr_reader.lake_abacus_lakes
    to_xarray = zarr_reader.to_xarray

    # -- Finalization --------------------------------------------------------

    def _guard_write(self) -> Any:
        """Return a context manager that holds the cross-process filelock."""
        try:
            return self._lock.acquire(timeout=LOCK_TIMEOUT_SECONDS)
        except Timeout as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                f"Could not acquire Zarr write lock for {self._path} after {LOCK_TIMEOUT_SECONDS}s"
            ) from exc

    def consolidate_metadata(self) -> None:
        """Consolidate Zarr metadata into a single ``.zmetadata`` entry."""
        consolidate_metadata(self._store, self._path)

    def close(self) -> None:
        """Close the live store and invoke any on-close callback."""
        if self._store is not None:
            if hasattr(self._store, "close"):
                self._store.close()
            self._store = None
        self._root = None
        if self._on_close is not None:
            callback = self._on_close
            self._on_close = None
            callback(self)

    def __enter__(self) -> SimulationZarr:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = [
    "LOCK_TIMEOUT_SECONDS",
    "SimulationZarr",
]
