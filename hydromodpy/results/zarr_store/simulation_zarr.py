"""SimulationZarr: per-simulation Zarr v2 store (CF-1.11 + ACDD-1.3 + UGRID-1.0).

Single source of truth for HydroModPy field arrays on disk. Handles mesh,
state, derived, budget, particles, forcing groups plus the CF time/crs
coordinates and ACDD root metadata. All writes are atomic and protected by
a filelock-based ``.lock`` file so concurrent writers cannot corrupt the
store.

Refer to ``reports_db/03_zarr_stores.md`` and
``reports_db/99_target_architecture.md`` §5 for the layout contract.
"""

from __future__ import annotations

import json
import os
import shutil
import warnings
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from os import replace
from pathlib import Path
from typing import Any

import numpy as np
import zarr
import zarr.codecs
from filelock import FileLock, Timeout
from upath import UPath

from hydromodpy.core.logging import get_logger
from hydromodpy.core.version import __version__ as _HMP_VERSION
from hydromodpy.results import field_registry
from hydromodpy.results.storage_contract import ZARR_ZIP_SUFFIX
from hydromodpy.results.zarr_store.acdd import compose_acdd_root_attrs
from hydromodpy.results.zarr_store.chunks import (
    compute_balanced_chunks_1d,
    compute_balanced_chunks_2d,
    compute_shard_shape_1d,
    compute_shard_shape_2d,
    should_use_sharding,
)
from hydromodpy.results.zarr_store.constants import (
    _SUBGROUPS,
    BLOSC_ZSTD,
    CF_CONVENTIONS,
    ZARR_SCHEMA_VERSION,
)
from hydromodpy.results.zarr_store.exceptions import ZarrSchemaVersionError

logger = get_logger(__name__)

LOCK_TIMEOUT_SECONDS = 60.0
LOCK_FILE_NAME = ".lock"


def _is_zip_store_path(path: Path) -> bool:
    return path.suffix == ".zip" or str(path).endswith(ZARR_ZIP_SUFFIX)


def _windows_long_path(path: Path) -> Path:
    """Return a Windows extended-length path when needed by local stores."""
    if os.name != "nt":
        return path
    text = str(path.resolve())
    if text.startswith("\\\\?\\"):
        return Path(text)
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text.lstrip("\\"))
    return Path("\\\\?\\" + text)


def _local_store_path_arg(path: Path) -> str:
    return str(_windows_long_path(path)) if os.name == "nt" else str(path)


def _ensure_local_zarr_node_dir(store_path: Path, zarr_path: str | None = None) -> None:
    if _is_zip_store_path(store_path):
        return
    if zarr_path:
        target = store_path.joinpath(*zarr_path.split("/"))
    else:
        target = store_path
    _windows_long_path(target).mkdir(parents=True, exist_ok=True)


def _child_zarr_path(target: zarr.Group, name: str) -> str:
    base = target.path or ""
    return f"{base}/{name}" if base else name


def _update_attrs(node: Any, attrs: dict[str, object]) -> Any:
    """Apply one merged metadata write to a Zarr group/array."""
    if not attrs:
        return node
    return node.update_attributes(attrs)


def _field_name_from_target(target: zarr.Group, variable: str) -> str:
    """Return the canonical registry field name for ``(group, variable)``."""
    path = target.path or ""
    candidate = f"{path}/{variable}" if path else variable
    for name, desc in field_registry.FIELD_REGISTRY.items():
        if desc.zarr_path == candidate or desc.public_name == variable:
            return name
    return ""


def _attrs_for_field(name: str, dtype: np.dtype) -> dict[str, object]:
    """Compose CF attrs for a field straight from the registry + _FillValue."""
    if not field_registry.has(name):
        attrs: dict[str, object] = {}
    else:
        attrs = dict(field_registry.cf_attrs(name))
    if np.issubdtype(dtype, np.floating):
        attrs["_FillValue"] = float(np.nan)
    elif np.issubdtype(dtype, np.integer):
        attrs["_FillValue"] = int(np.iinfo(dtype).min)
    return attrs


class _DummyLock:
    """No-op lock used for zip stores (read-only by construction)."""

    def acquire(self, *_: Any, **__: Any) -> None:
        return None

    def release(self) -> None:
        return None

    def __enter__(self) -> _DummyLock:
        return self

    def __exit__(self, *_: Any) -> None:
        return None


class SimulationZarr:
    """Per-simulation Zarr v2 store. Atomic, locked, CF-1.11 + ACDD-1.3."""

    def __init__(self, path: Path | UPath | str, *, balanced: bool = True) -> None:
        self._path = Path(str(path))
        self._balanced = bool(balanced)
        self._on_close: Callable[[SimulationZarr], None] | None = None
        if _is_zip_store_path(self._path):
            self._store: Any = zarr.storage.ZipStore(str(self._path), mode="r")
            self._root: zarr.Group = self._open_root_strict(read_only=True)
            self._lock: FileLock | _DummyLock = _DummyLock()
        else:
            self._store = zarr.storage.LocalStore(_local_store_path_arg(self._path))
            self._root = self._open_root_strict(read_only=False)
            self._lock = FileLock(str(self._path / LOCK_FILE_NAME))

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
        path = Path(str(path))
        _ensure_local_zarr_node_dir(path)
        store = zarr.storage.LocalStore(_local_store_path_arg(path))
        root = zarr.open_group(store, mode="w")
        root_attrs: dict[str, object] = {
            "Conventions": CF_CONVENTIONS,
            "hydromodpy_version": _HMP_VERSION,
            "zarr_schema_version": ZARR_SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "n_cells": int(n_cells),
            "n_layers": int(n_layers),
            "chunking": "balanced",
        }
        if cell_types is not None:
            root_attrs["cell_types"] = list(cell_types)
        if geographic_fingerprint is not None:
            root_attrs["geographic_fingerprint"] = str(geographic_fingerprint)
        root = _update_attrs(root, root_attrs)

        for sub in _SUBGROUPS:
            _ensure_local_zarr_node_dir(path, sub)
            root.create_group(sub)

        meta = root["meta"]
        _update_attrs(meta, {"zarr_schema_version": ZARR_SCHEMA_VERSION})

        instance = cls.__new__(cls)
        instance._path = path
        instance._store = store
        instance._root = root
        instance._balanced = bool(balanced)
        instance._on_close = None
        instance._lock = FileLock(str(path / LOCK_FILE_NAME))
        return instance

    def _open_root_strict(self, *, read_only: bool) -> zarr.Group:
        """Open the root group and validate the schema version.

        The v2 contract requires every persisted store to carry a non-null
        ``zarr_schema_version`` attribute matching ``ZARR_SCHEMA_VERSION`` at
        the root. Mismatch, absence and null all raise
        :class:`ZarrSchemaVersionError`. A freshly created empty directory is
        the only exempted case (``__init__`` racing with ``create``).
        """
        mode = "r" if read_only else "a"
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=(
                    "Consolidated metadata is currently not part .* Zarr format 3 specification.*"
                ),
                category=UserWarning,
            )
            try:
                root = zarr.open_group(
                    self._store,
                    mode=mode,
                    use_consolidated=True,
                )
            except (KeyError, ValueError):
                root = zarr.open_group(self._store, mode=mode)
        is_empty = not dict(root.attrs) and not list(root.keys())
        if is_empty and not read_only:
            return root
        actual = root.attrs.get("zarr_schema_version")
        if actual is None or str(actual) != ZARR_SCHEMA_VERSION:
            raise ZarrSchemaVersionError(
                ZARR_SCHEMA_VERSION,
                None if actual is None else str(actual),
            )
        return root

    # -- Public accessors ----------------------------------------------------

    @property
    def root(self) -> zarr.Group:
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
        value = self._root.attrs.get("geographic_fingerprint")
        return str(value) if value else None

    @geographic_fingerprint.setter
    def geographic_fingerprint(self, value: str | None) -> None:
        if value is None:
            if "geographic_fingerprint" in self._root.attrs:
                del self._root.attrs["geographic_fingerprint"]
        else:
            self._root.attrs["geographic_fingerprint"] = str(value)

    def resolve_geographic_dir(self, workspace_path: Path | str) -> Path | None:
        fp = self.geographic_fingerprint
        if fp is None:
            return None
        from hydromodpy.results.geographic_cache import GeographicCache

        return GeographicCache(workspace_path).path_for(fp)

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
        start_index: int = 0,
        grid_type: str | None = None,
        structured_shape: tuple[int, int] | None = None,
    ) -> None:
        """Write the UGRID-1.0 mesh group, including the optional topography array.

        All solver extractors must call this entry point instead of
        ``mesh.create_array(...)`` so CF/UGRID attributes stay consistent.
        """
        with self._guard_write():
            mesh = self._root.require_group("mesh")
            self._ensure_child_dir(mesh, "vertices")
            vertices_arr = mesh.create_array(
                "vertices",
                data=np.asarray(vertices, dtype="float64"),
                overwrite=True,
            )
            _update_attrs(
                vertices_arr,
                {
                    "long_name": "Mesh node coordinates (x, y, z)",
                    "units": "m",
                    "cf_role": "mesh_node_coordinates",
                },
            )

            self._ensure_child_dir(mesh, "face_node_connectivity")
            fnc = mesh.create_array(
                "face_node_connectivity",
                data=np.asarray(face_node_connectivity, dtype="int32"),
                overwrite=True,
            )
            _update_attrs(
                fnc,
                {
                    "cf_role": "face_node_connectivity",
                    "long_name": "Mapping from every face to its corner nodes",
                    "start_index": int(start_index),
                },
            )

            self._ensure_child_dir(mesh, "z_interfaces")
            z_arr = mesh.create_array(
                "z_interfaces",
                data=np.asarray(z_interfaces, dtype="float64"),
                overwrite=True,
            )
            _update_attrs(
                z_arr,
                {
                    "long_name": "Altitude of layer interfaces",
                    "units": "m",
                    "standard_name": "altitude",
                    "positive": "up",
                },
            )

            if layer_indices is not None:
                self._ensure_child_dir(mesh, "layer_indices")
                mesh.create_array(
                    "layer_indices",
                    data=np.asarray(layer_indices, dtype="int32"),
                    overwrite=True,
                )
            if source_cell_indices is not None:
                self._ensure_child_dir(mesh, "source_cell_indices")
                mesh.create_array(
                    "source_cell_indices",
                    data=np.asarray(source_cell_indices, dtype="int32"),
                    overwrite=True,
                )

            if topography is not None:
                self._ensure_child_dir(mesh, "topography")
                topo_arr = mesh.create_array(
                    "topography",
                    data=np.asarray(topography, dtype="float64"),
                    overwrite=True,
                )
                _update_attrs(topo_arr, _attrs_for_field("topography", topo_arr.dtype))

            mesh_attrs: dict[str, object] = {
                "start_index": int(start_index),
                "n_nodes": int(np.asarray(vertices).shape[0]),
                "n_cells": int(np.asarray(face_node_connectivity).shape[0]),
                "n_layers": int(len(z_interfaces) - 1),
            }
            if grid_type:
                mesh_attrs["grid_type"] = str(grid_type)
            if structured_shape is not None:
                mesh_attrs["structured_shape"] = [
                    int(structured_shape[0]),
                    int(structured_shape[1]),
                ]
            _update_attrs(mesh, mesh_attrs)

            # UGRID-1.0 topology scalar variable carrying the topology attrs.
            self._ensure_child_dir(mesh, "topology")
            topo = mesh.create_array(
                "topology",
                data=np.zeros((), dtype="int32"),
                overwrite=True,
            )
            _update_attrs(
                topo,
                {
                    "cf_role": "mesh_topology",
                    "long_name": "UGRID 2D topology of the simulation mesh",
                    "topology_dimension": 2,
                    "node_coordinates": "vertices",
                    "face_node_connectivity": "face_node_connectivity",
                },
            )

    def write_topography(
        self,
        topography: np.ndarray,
        *,
        z_interfaces: np.ndarray | None = None,
        n_cells: int | None = None,
        n_layers: int | None = None,
    ) -> None:
        """Write the mesh topography (and optional z_interfaces) only.

        Useful for solvers like Boussinesq that do not expose a full UGRID
        mesh but still need the surface elevation under ``mesh/topography``.
        """
        with self._guard_write():
            mesh = self._root.require_group("mesh")
            self._ensure_child_dir(mesh, "topography")
            topo_arr = mesh.create_array(
                "topography",
                data=np.asarray(topography, dtype="float64"),
                overwrite=True,
            )
            _update_attrs(topo_arr, _attrs_for_field("topography", topo_arr.dtype))
            if z_interfaces is not None:
                self._ensure_child_dir(mesh, "z_interfaces")
                z_arr = mesh.create_array(
                    "z_interfaces",
                    data=np.asarray(z_interfaces, dtype="float64"),
                    overwrite=True,
                )
                _update_attrs(
                    z_arr,
                    {
                        "long_name": "Altitude of layer interfaces",
                        "units": "m",
                        "standard_name": "altitude",
                        "positive": "up",
                    },
                )
            mesh_attrs: dict[str, object] = {}
            if n_cells is not None:
                mesh_attrs["n_cells"] = int(n_cells)
            if n_layers is not None:
                mesh_attrs["n_layers"] = int(n_layers)
            if mesh_attrs:
                _update_attrs(mesh, mesh_attrs)

    # -- Time / CRS metadata --------------------------------------------------

    def write_time(
        self,
        values: np.ndarray,
        *,
        epoch: str = "1970-01-01T00:00:00",
        calendar: str = "proleptic_gregorian",
        units: str = "seconds since 1970-01-01T00:00:00",
    ) -> None:
        with self._guard_write():
            self._ensure_child_dir(self._root, "time")
            time_arr = self._root.create_array(
                "time",
                data=np.asarray(values, dtype="int64"),
                overwrite=True,
            )
            _update_attrs(
                time_arr,
                {
                    "units": units,
                    "calendar": calendar,
                    "standard_name": "time",
                    "long_name": "Simulation time",
                    "axis": "T",
                },
            )
            self._root = _update_attrs(self._root, {"time_epoch": epoch})

    def write_crs(
        self,
        *,
        crs_wkt: str,
        grid_mapping_name: str = "latitude_longitude",
        epsg_code: int | None = None,
        semi_major_axis: float | None = None,
        inverse_flattening: float | None = None,
    ) -> None:
        with self._guard_write():
            self._ensure_child_dir(self._root, "crs")
            crs_arr = self._root.create_array(
                "crs",
                data=np.zeros((), dtype="int32"),
                overwrite=True,
            )
            attrs: dict[str, object] = {"grid_mapping_name": grid_mapping_name}
            if crs_wkt:
                attrs["crs_wkt"] = crs_wkt
            if epsg_code is not None:
                attrs["epsg_code"] = int(epsg_code)
            if semi_major_axis is not None:
                attrs["semi_major_axis"] = float(semi_major_axis)
            if inverse_flattening is not None:
                attrs["inverse_flattening"] = float(inverse_flattening)
            _update_attrs(crs_arr, attrs)

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
        """Append one timestep slice to ``variable`` under ``subgroup`` or root.

        Allocation on the first call uses balanced chunks (~1 MiB) and
        promotes to ``ShardingCodec`` whenever the total array size exceeds
        the 100 MiB trigger.
        """
        with self._guard_write():
            if subgroup:
                if subgroup not in self._root:
                    self._ensure_child_dir(self._root, subgroup)
                    self._root.create_group(subgroup)
                target = self._root[subgroup]
            else:
                target = self._root

            values = np.asarray(values)
            itemsize = int(values.dtype.itemsize)
            if values.ndim == 1:
                n_cells = int(values.shape[0])
                full_shape = (int(n_timesteps), n_cells) if n_timesteps is not None else None
                if self._balanced and n_timesteps is not None:
                    chunk_shape: tuple[int, ...] = compute_balanced_chunks_1d(
                        int(n_timesteps), n_cells, itemsize
                    )
                else:
                    chunk_shape = (1, n_cells)
            elif values.ndim == 2:
                n_layers, n_cells = int(values.shape[0]), int(values.shape[1])
                full_shape = (
                    (int(n_timesteps), n_layers, n_cells) if n_timesteps is not None else None
                )
                if self._balanced and n_timesteps is not None:
                    chunk_shape = compute_balanced_chunks_2d(
                        int(n_timesteps), n_layers, n_cells, itemsize
                    )
                else:
                    chunk_shape = (1, n_layers, n_cells)
            else:
                raise ValueError(f"Expected 1D or 2D values, got shape {values.shape}")

            if variable not in target:
                if n_timesteps is None:
                    raise ValueError(f"n_timesteps required on first write of '{variable}'")
                self._ensure_child_dir(target, variable)
                shards = self._maybe_shards(
                    values.ndim,
                    int(n_timesteps),
                    chunk_shape,
                    itemsize,
                    n_layers=n_layers if values.ndim == 2 else 1,
                    n_cells=n_cells,
                )
                create_kwargs: dict[str, Any] = dict(
                    shape=full_shape,
                    chunks=chunk_shape,
                    dtype=values.dtype,
                    compressors=BLOSC_ZSTD,
                    fill_value=float("nan"),
                    overwrite=True,
                )
                if shards is not None:
                    try:
                        target.create_array(
                            variable,
                            shards=shards,
                            **create_kwargs,
                        )
                    except (TypeError, ValueError) as exc:
                        logger.warning(
                            "ShardingCodec unavailable for %s (shape=%s, "
                            "shard=%s): %s. Falling back to plain chunks.",
                            variable,
                            full_shape,
                            shards,
                            exc,
                        )
                        target.create_array(variable, **create_kwargs)
                else:
                    target.create_array(variable, **create_kwargs)
                self._attach_field_attrs(target, variable)

            arr = target[variable]
            if values.ndim == 1:
                arr[int(timestep), :] = values
            else:
                arr[int(timestep), :, :] = values

    def _maybe_shards(
        self,
        ndim: int,
        n_timesteps: int,
        chunk_shape: tuple[int, ...],
        itemsize: int,
        *,
        n_layers: int,
        n_cells: int,
    ) -> tuple[int, ...] | None:
        layer_bytes_per_step = n_layers * n_cells * max(itemsize, 1)
        if not should_use_sharding(n_timesteps, layer_bytes_per_step):
            return None
        if ndim == 1:
            shard = compute_shard_shape_1d(
                n_timesteps,
                (chunk_shape[0], chunk_shape[1]),
                itemsize=itemsize,
            )
            return tuple(shard) if shard is not None else None
        if ndim == 2:
            shard = compute_shard_shape_2d(
                n_timesteps,
                (chunk_shape[0], chunk_shape[1], chunk_shape[2]),
                itemsize=itemsize,
            )
            return tuple(shard) if shard is not None else None
        return None

    def _attach_field_attrs(self, target: zarr.Group, variable: str) -> None:
        name = _field_name_from_target(target, variable)
        if not name:
            return
        arr = target[variable]
        _update_attrs(arr, _attrs_for_field(name, np.dtype(arr.dtype)))

    def _ensure_child_dir(self, target: zarr.Group, name: str) -> None:
        _ensure_local_zarr_node_dir(self._path, _child_zarr_path(target, name))

    def _guard_write(self) -> Any:
        """Return a context manager that holds the cross-process filelock."""
        if isinstance(self._lock, _DummyLock):
            return self._lock
        try:
            return self._lock.acquire(timeout=LOCK_TIMEOUT_SECONDS)
        except Timeout as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                f"Could not acquire Zarr write lock for {self._path} after {LOCK_TIMEOUT_SECONDS}s"
            ) from exc

    def read_field(
        self,
        variable: str,
        timestep: int,
        *,
        subgroup: str | None = None,
        layer: int | None = None,
    ) -> np.ndarray:
        if subgroup:
            target = self._root[subgroup]
            if variable not in target:
                raise KeyError(f"Variable '{variable}' not found in subgroup '{subgroup}'")
            data = target[variable][int(timestep)]
        else:
            for loc_name in (None, "state", "derived", "budget"):
                loc = self._root if loc_name is None else self._root.get(loc_name)
                if loc is not None and variable in loc:
                    data = loc[variable][int(timestep)]
                    break
            else:
                raise KeyError(f"Variable '{variable}' not found")
        if layer is not None and data.ndim == 2:
            return data[layer]
        return data

    # -- Forcing persistence --------------------------------------------------

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
        with self._guard_write():
            self._ensure_child_dir(self._root, "forcing")
            forcing = self._root.require_group("forcing")
            self._ensure_child_dir(forcing, variable)
            var_grp = forcing.require_group(variable)
            self._ensure_child_dir(var_grp, station_id)
            sta_grp = var_grp.require_group(station_id)

            ts_bytes = np.asarray(timestamps, dtype="datetime64[ns]").view("int64")
            self._ensure_child_dir(sta_grp, "timestamps")
            ts_arr = sta_grp.create_array("timestamps", data=ts_bytes, overwrite=True)
            _update_attrs(
                ts_arr,
                {
                    "units": "nanoseconds since 1970-01-01T00:00:00",
                    "calendar": "proleptic_gregorian",
                    "standard_name": "time",
                    "long_name": f"Timestamps for {variable}",
                    "axis": "T",
                },
            )
            self._ensure_child_dir(sta_grp, "values")
            values_arr = sta_grp.create_array(
                "values", data=np.asarray(values, dtype="float64"), overwrite=True
            )
            _update_attrs(
                values_arr,
                {
                    "units": str(unit),
                    "long_name": f"Forcing values for {variable}",
                    "source": str(source),
                },
            )
            _update_attrs(
                sta_grp,
                {
                    "unit": str(unit),
                    "source": str(source),
                    "n_records": int(len(values)),
                },
            )

    def write_forcing_field(
        self,
        variable: str,
        data: np.ndarray,
        *,
        unit: str = "",
        source: str = "",
    ) -> None:
        with self._guard_write():
            self._ensure_child_dir(self._root, "forcing")
            forcing = self._root.require_group("forcing")
            self._ensure_child_dir(forcing, variable)
            forcing.create_array(
                variable,
                data=np.asarray(data),
                compressors=BLOSC_ZSTD,
                overwrite=True,
            )
            _update_attrs(forcing[variable], {"unit": str(unit), "source": str(source)})

    def read_forcing_timeseries(
        self,
        variable: str,
        station_id: str,
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        forcing = self._root.get("forcing")
        if forcing is None:
            raise KeyError("No forcing group")
        var_grp = forcing.get(variable)
        if var_grp is None:
            raise KeyError(f"No forcing variable '{variable}'")
        sta_grp = var_grp.get(station_id)
        if sta_grp is None:
            raise KeyError(f"No forcing station '{station_id}' for '{variable}'")
        ts_int = np.asarray(sta_grp["timestamps"][:], dtype="int64")
        timestamps = ts_int.view("datetime64[ns]")
        values = np.asarray(sta_grp["values"][:], dtype="float64")
        attrs = dict(sta_grp.attrs)
        return timestamps, values, attrs

    # -- Geographic rasters (legacy, per-run) --------------------------------

    def write_geographic_raster(
        self,
        name: str,
        data: np.ndarray,
        *,
        transform: tuple[float, ...],
        crs: str,
        nodata: float = -99999.0,
    ) -> None:
        """Persist a per-run raster under ``geographic/<name>``.

        Shared DEM / geology rasters belong to the workspace-level cache
        (``GeographicCache``); this entry point exists only for per-run
        artefacts (out_top, masks, ...).
        """
        with self._guard_write():
            self._ensure_child_dir(self._root, "geographic")
            geo = self._root.require_group("geographic")
            self._ensure_child_dir(geo, name)
            geo.create_array(
                name,
                data=np.asarray(data),
                compressors=BLOSC_ZSTD,
                overwrite=True,
            )
            arr = geo[name]
            _update_attrs(
                arr,
                {
                    "transform": list(transform),
                    "crs": str(crs),
                    "nodata": float(nodata),
                    "shape": list(np.asarray(data).shape),
                },
            )

    def read_geographic_raster(self, name: str) -> tuple[np.ndarray, dict]:
        geo = self._root.get("geographic")
        if geo is None or name not in geo:
            raise KeyError(f"Geographic raster '{name}' not found")
        arr = geo[name]
        data = np.asarray(arr[:])
        meta = {
            "transform": tuple(arr.attrs.get("transform", ())),
            "crs": arr.attrs.get("crs", ""),
            "nodata": arr.attrs.get("nodata", -99999.0),
            "shape": tuple(arr.attrs.get("shape", ())),
        }
        return data, meta

    # -- ACDD ---------------------------------------------------------------

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
        attrs = compose_acdd_root_attrs(
            sim_row=sim_row,
            runs_env=runs_env,
            project_table=project_table,
            geographic_bounds=geographic_bounds,
            history_lines=history_lines,
        )
        with self._guard_write():
            self._root = _update_attrs(self._root, attrs)
            meta = self._root.require_group("meta")
            # ``meta`` stores the same ACDD payload so a downstream tool can
            # discover the metadata even with .zmetadata stripped.
            _update_attrs(meta, attrs)
        return attrs

    # -- xarray export --------------------------------------------------------

    def to_xarray(self):
        """Return an ``xarray.Dataset`` view over the simulation fields."""
        import dask.array as da
        import xarray as xr

        data_vars: dict[str, xr.Variable] = {}
        coords: dict[str, xr.Variable] = {}

        def _shape_dims(shape: str) -> tuple[str, ...]:
            return {
                field_registry.SHAPE_TIME_LAYER_FACE: ("time", "layer", "face"),
                field_registry.SHAPE_TIME_FACE: ("time", "face"),
                field_registry.SHAPE_LAYER_FACE: ("layer", "face"),
                field_registry.SHAPE_FACE: ("face",),
                field_registry.SHAPE_PARTICLES: ("time", "particle"),
            }.get(shape, ())

        for name, desc in field_registry.FIELD_REGISTRY.items():
            path = desc.zarr_path
            if "/" in path:
                group_name, var_name = path.split("/", 1)
                group = self._root.get(group_name)
                if group is None or var_name not in group:
                    continue
                arr = group[var_name]
            else:
                if path not in self._root:
                    continue
                arr = self._root[path]
            dims = _shape_dims(desc.shape)
            if len(dims) != arr.ndim:
                dims = tuple(f"dim_{i}" for i in range(arr.ndim))
            chunks = arr.chunks if arr.chunks else "auto"
            data_vars[name] = xr.Variable(
                dims,
                da.from_array(arr, chunks=chunks),
                attrs=dict(arr.attrs),
            )

        if "time" in self._root:
            time_arr = self._root["time"]
            coords["time"] = xr.Variable(
                ("time",),
                np.asarray(time_arr[:]),
                attrs=dict(time_arr.attrs),
            )
        if "crs" in self._root:
            crs_arr = self._root["crs"]
            coords["crs"] = xr.Variable(
                (),
                np.asarray(crs_arr[()]),
                attrs=dict(crs_arr.attrs),
            )

        root_attrs = {k: v for k, v in self._root.attrs.items()}
        return xr.Dataset(data_vars=data_vars, coords=coords, attrs=root_attrs)

    # -- Finalization --------------------------------------------------------

    def consolidate_metadata(self) -> None:
        """Consolidate Zarr metadata into a single ``.zmetadata`` entry."""
        if not isinstance(self._store, zarr.storage.LocalStore):
            return
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=(
                        "Consolidated metadata is currently not part .* "
                        "Zarr format 3 specification.*"
                    ),
                    category=UserWarning,
                )
                zarr.consolidate_metadata(self._store)
        except Exception as exc:
            logger.warning("consolidate_metadata failed for %s: %s", self._path, exc)

    # -- Packing -------------------------------------------------------------

    def pack_to_zip(self) -> Path:
        """Compact the directory-based Zarr store into a ``.zarr.zip`` file."""
        if not self._path.is_dir():
            return self._path

        self.close()

        zip_path = self._path.with_suffix(ZARR_ZIP_SUFFIX)
        tmp_path = zip_path.with_name(f"{zip_path.name}.tmp")
        if tmp_path.exists():
            tmp_path.unlink()

        # Skip the lock file (transient, not part of the artifact).
        with zipfile.ZipFile(str(tmp_path), "w", compression=zipfile.ZIP_STORED) as zf:
            for fpath in sorted(self._path.rglob("*")):
                if not fpath.is_file():
                    continue
                if fpath.name == LOCK_FILE_NAME:
                    continue
                arcname = str(fpath.relative_to(self._path))
                zf.write(str(fpath), arcname)

        with zipfile.ZipFile(str(tmp_path), "r") as zf:
            corrupt = zf.testzip()
            if corrupt is not None:
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(f"Corrupt Zarr zip member: {corrupt}")

        replace(tmp_path, zip_path)
        check = SimulationZarr(zip_path)
        check.close()

        try:
            shutil.rmtree(self._path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning(
                "Packed %s -> %s, but could not remove the source Zarr directory.",
                self._path.name,
                zip_path.name,
                exc_info=True,
            )
        logger.debug("Packed %s -> %s", self._path.name, zip_path.name)

        self._path = zip_path
        self._store = zarr.storage.ZipStore(str(zip_path), mode="r")
        self._root = self._open_root_strict(read_only=True)
        self._lock = _DummyLock()
        return zip_path

    # -- Lifecycle -----------------------------------------------------------

    def close(self) -> None:
        if self._store is not None:
            if hasattr(self._store, "close"):
                self._store.close()
            self._store = None
        if self._on_close is not None:
            callback = self._on_close
            self._on_close = None
            callback(self)

    def __enter__(self) -> SimulationZarr:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- Debug helpers -------------------------------------------------------

    def root_attrs_json(self) -> str:
        return json.dumps({k: v for k, v in self._root.attrs.items()}, default=str)


__all__ = [
    "SimulationZarr",
    "_windows_long_path",
    "_local_store_path_arg",
    "_is_zip_store_path",
    "_ensure_local_zarr_node_dir",
]
