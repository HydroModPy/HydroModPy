"""SimulationZarr: per-simulation Zarr v2 store (CF-1.11 + ACDD-1.3 + UGRID-1.0).

Thin facade over four single-concern modules:

* :mod:`hydromodpy.results.zarr_store.zarr_schema` — layout contract and
  schema-version enforcement.
* :mod:`hydromodpy.results.zarr_store.zarr_writer` — every ``write_*`` and
  the CF-attribute composition.
* :mod:`hydromodpy.results.zarr_store.zarr_reader` — every ``read_*`` and
  the root-attribute readers.
* :mod:`hydromodpy.results.zarr_store.zarr_finalizer` — write lock,
  ``consolidate_metadata``, ``pack_to_zip``, ``close``.

Refer to ``reports_db/03_zarr_stores.md`` and
``reports_db/99_target_architecture.md`` §5 for the layout contract.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import zarr
from filelock import FileLock
from upath import UPath

from hydromodpy.results.zarr_store import zarr_finalizer, zarr_reader, zarr_writer
from hydromodpy.results.zarr_store.zarr_finalizer import (
    LOCK_FILE_NAME,
    LOCK_TIMEOUT_SECONDS,
)
from hydromodpy.results.zarr_store.zarr_finalizer import DummyLock as _DummyLock
from hydromodpy.results.zarr_store.zarr_schema import (
    ensure_local_zarr_node_dir as _ensure_local_zarr_node_dir,
)
from hydromodpy.results.zarr_store.zarr_schema import (
    initialise_root,
    is_zip_store_path,
    local_store,
    open_root_strict,
)
from hydromodpy.results.zarr_store.zarr_schema import (
    is_zip_store_path as _is_zip_store_path,
)
from hydromodpy.results.zarr_store.zarr_schema import (
    local_store_path_arg as _local_store_path_arg,
)
from hydromodpy.results.zarr_store.zarr_schema import (
    windows_long_path as _windows_long_path,
)


def _file_lock_for_store(path: Path) -> FileLock:
    """Build the store lock using extended-length paths on Windows."""
    return FileLock(str(_windows_long_path(path / LOCK_FILE_NAME)))


class SimulationZarr:
    """Per-simulation Zarr v2 store. Atomic, locked, CF-1.11 + ACDD-1.3."""

    def __init__(self, path: Path | UPath | str, *, balanced: bool = True) -> None:
        self._path = Path(str(path))
        self._balanced = bool(balanced)
        self._on_close: Callable[[SimulationZarr], None] | None = None
        if is_zip_store_path(self._path):
            self._store: Any = zarr.storage.ZipStore(str(self._path), mode="r")
            self._root: zarr.Group | None = self._open_root_strict(read_only=True)
            self._lock: FileLock | _DummyLock = _DummyLock()
        else:
            self._store = local_store(self._path)
            self._root = self._open_root_strict(read_only=False)
            self._lock = _file_lock_for_store(self._path)

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
        balanced: bool = True,
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
        instance._balanced = bool(balanced)
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
    def balanced(self) -> bool:
        return self._balanced

    # -- Geographic fingerprint ---------------------------------------------

    @property
    def geographic_fingerprint(self) -> str | None:
        return zarr_reader.get_geographic_fingerprint(self)

    @geographic_fingerprint.setter
    def geographic_fingerprint(self, value: str | None) -> None:
        zarr_reader.set_geographic_fingerprint(self, value)

    def resolve_geographic_dir(self, workspace_path: Path | str) -> Path | None:
        return zarr_reader.resolve_geographic_dir(self, workspace_path)

    # -- Mesh ----------------------------------------------------------------

    def write_mesh(
        self,
        vertices: np.ndarray,
        face_node_connectivity: np.ndarray,
        z_interfaces: np.ndarray,
        layer_indices: np.ndarray | None = None,
        source_cell_indices: np.ndarray | None = None,
        topography: np.ndarray | None = None,
        *,
        topography_reference: np.ndarray | None = None,
        start_index: int = 0,
        grid_type: str | None = None,
        structured_shape: tuple[int, int] | None = None,
    ) -> None:
        """Write the UGRID-1.0 mesh group, including the optional topography array."""
        zarr_writer.write_mesh(
            self,
            vertices,
            face_node_connectivity,
            z_interfaces,
            layer_indices,
            source_cell_indices,
            topography,
            topography_reference=topography_reference,
            start_index=start_index,
            grid_type=grid_type,
            structured_shape=structured_shape,
        )

    def write_topography(
        self,
        topography: np.ndarray,
        *,
        z_interfaces: np.ndarray | None = None,
        n_cells: int | None = None,
        n_layers: int | None = None,
    ) -> None:
        """Write the mesh topography (and optional z_interfaces) only."""
        zarr_writer.write_topography(
            self,
            topography,
            z_interfaces=z_interfaces,
            n_cells=n_cells,
            n_layers=n_layers,
        )

    # -- Time / CRS ----------------------------------------------------------

    def write_time(
        self,
        values: np.ndarray,
        *,
        epoch: str = "1970-01-01T00:00:00",
        calendar: str = "proleptic_gregorian",
        units: str = "seconds since 1970-01-01T00:00:00",
    ) -> None:
        zarr_writer.write_time(self, values, epoch=epoch, calendar=calendar, units=units)

    def write_crs(
        self,
        *,
        crs_wkt: str,
        grid_mapping_name: str = "latitude_longitude",
        epsg_code: int | None = None,
        semi_major_axis: float | None = None,
        inverse_flattening: float | None = None,
    ) -> None:
        zarr_writer.write_crs(
            self,
            crs_wkt=crs_wkt,
            grid_mapping_name=grid_mapping_name,
            epsg_code=epsg_code,
            semi_major_axis=semi_major_axis,
            inverse_flattening=inverse_flattening,
        )

    # -- Fields --------------------------------------------------------------

    def write_field(
        self,
        variable: str,
        timestep: int,
        values: np.ndarray,
        *,
        n_timesteps: int | None = None,
        subgroup: str | None = None,
    ) -> None:
        """Append one timestep slice to ``variable`` under ``subgroup`` or root."""
        zarr_writer.write_field(
            self,
            variable,
            timestep,
            values,
            n_timesteps=n_timesteps,
            subgroup=subgroup,
        )

    def write_field_stack(
        self,
        variable: str,
        values: np.ndarray,
        *,
        n_timesteps: int | None = None,
        timestep_offset: int = 0,
        subgroup: str | None = None,
    ) -> None:
        """Write a full ``(time, ...)`` stack of ``variable`` in one batched call."""
        zarr_writer.write_field_stack(
            self,
            variable,
            values,
            n_timesteps=n_timesteps,
            timestep_offset=timestep_offset,
            subgroup=subgroup,
        )

    def read_field(
        self,
        variable: str,
        timestep: int,
        *,
        subgroup: str | None = None,
        layer: int | None = None,
    ) -> np.ndarray:
        return zarr_reader.read_field(self, variable, timestep, subgroup=subgroup, layer=layer)

    def read_time(self) -> np.ndarray | None:
        """Return the CF ``/time`` axis as ``datetime64[ns]``, or ``None``.

        This axis is the single source of truth for the simulation clock: the
        exact stress-period timestamps the solver wrote, shared by every field
        array. Stored as integer offsets since the CF epoch (1970-01-01), so a
        plain numpy cast decodes it without a calendar library.
        """
        root = self._root
        if root is None or "time" not in root:
            return None
        arr = root["time"]
        values = np.asarray(arr[:])
        if values.size == 0:
            return None
        units = str(dict(arr.attrs).get("units", "seconds since 1970-01-01"))
        if "since 1970-01-01" not in units:
            # The decode below assumes the 1970 epoch; a different epoch would
            # silently shift the whole clock (~30 years for a 2000 anchor).
            raise ValueError(
                f"SimulationZarr.read_time: time units {units!r} are not anchored to "
                "'since 1970-01-01'; the clock cannot be decoded without an epoch offset."
            )
        unit_code = "s"
        if units.startswith("days"):
            unit_code = "D"
        elif units.startswith("hours"):
            unit_code = "h"
        elif units.startswith("minutes"):
            unit_code = "m"
        return values.astype(f"datetime64[{unit_code}]").astype("datetime64[ns]")

    # -- Forcing -------------------------------------------------------------

    def write_forcing_timeseries(
        self,
        variable: str,
        station_id: str,
        timestamps: np.ndarray,
        values: np.ndarray,
        *,
        unit: str = "",
        source: str = "",
    ) -> None:
        zarr_writer.write_forcing_timeseries(
            self,
            variable,
            station_id,
            timestamps,
            values,
            unit=unit,
            source=source,
        )

    def write_forcing_field(
        self,
        variable: str,
        data: np.ndarray,
        *,
        unit: str = "",
        source: str = "",
    ) -> None:
        zarr_writer.write_forcing_field(self, variable, data, unit=unit, source=source)

    def read_forcing_timeseries(
        self,
        variable: str,
        station_id: str,
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        return zarr_reader.read_forcing_timeseries(self, variable, station_id)

    # -- Geographic rasters --------------------------------------------------

    def write_geographic_raster(
        self,
        name: str,
        data: np.ndarray,
        *,
        transform: tuple[float, ...],
        crs: str,
        nodata: float = -99999.0,
    ) -> None:
        """Persist a per-run raster under ``geographic/<name>``."""
        zarr_writer.write_geographic_raster(
            self, name, data, transform=transform, crs=crs, nodata=nodata
        )

    def read_geographic_raster(self, name: str) -> tuple[np.ndarray, dict]:
        return zarr_reader.read_geographic_raster(self, name)

    # -- Lake abacus comparison ----------------------------------------------

    def write_lake_abacus(self, lake_id: str, **arrays: Any) -> None:
        """Persist a lake's reference vs simulated abacus under ``lake_abacus/<id>``."""
        zarr_writer.write_lake_abacus(self, lake_id, **arrays)

    def read_lake_abacus(self, lake_id: str) -> dict:
        return zarr_reader.read_lake_abacus(self, lake_id)

    def lake_abacus_lakes(self) -> list[str]:
        return zarr_reader.lake_abacus_lakes(self)

    # -- ACDD ----------------------------------------------------------------

    def write_acdd_root_attrs(
        self,
        *,
        sim_row: dict[str, Any] | None,
        runs_env: dict[str, Any] | None,
        project_table: dict[str, Any] | None = None,
        geographic_bounds: dict[str, float] | None = None,
        history_lines: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compose and persist ACDD root attrs. Returns the attrs written."""
        return zarr_writer.write_acdd_root_attrs(
            self,
            sim_row=sim_row,
            runs_env=runs_env,
            project_table=project_table,
            geographic_bounds=geographic_bounds,
            history_lines=history_lines,
        )

    # -- xarray export -------------------------------------------------------

    def to_xarray(self):
        """Return an ``xarray.Dataset`` view over the simulation fields."""
        return zarr_reader.to_xarray(self)

    # -- Finalization --------------------------------------------------------

    def _guard_write(self) -> Any:
        """Return a context manager that holds the cross-process filelock."""
        return zarr_finalizer.guard_write(self._lock, self._path)

    def consolidate_metadata(self) -> None:
        """Consolidate Zarr metadata into a single ``.zmetadata`` entry."""
        zarr_finalizer.consolidate_metadata(self._store, self._path)

    def pack_to_zip(self) -> Path:
        """Compact the directory-based Zarr store into a ``.zarr.zip`` file."""
        return zarr_finalizer.pack_to_zip(self)

    def close(self) -> None:
        zarr_finalizer.close(self)

    def __enter__(self) -> SimulationZarr:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- Debug helpers -------------------------------------------------------

    def root_attrs_json(self) -> str:
        return zarr_reader.root_attrs_json(self)


__all__ = [
    "LOCK_FILE_NAME",
    "LOCK_TIMEOUT_SECONDS",
    "SimulationZarr",
    "_ensure_local_zarr_node_dir",
    "_is_zip_store_path",
    "_local_store_path_arg",
    "_windows_long_path",
]
