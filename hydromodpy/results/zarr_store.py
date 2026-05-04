from __future__ import annotations

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

from hydromodpy.core.logging import get_logger
from hydromodpy.core.version import __version__ as _HMP_VERSION
from hydromodpy.results import field_registry
from hydromodpy.results.storage_contract import ZARR_ZIP_SUFFIX

logger = get_logger(__name__)

BLOSC_ZSTD = zarr.codecs.BloscCodec(cname="zstd", clevel=3)

_SUBGROUPS = ("mesh", "derived", "budget", "pathlines", "geographic", "forcing")

# CF-1.11 + UGRID-1.0 root conventions string attached to every simulation
# Zarr store (see :mod:`hydromodpy.results.field_registry`).
CF_CONVENTIONS = "CF-1.11 UGRID-1.0"
ZARR_SCHEMA_VERSION = "1"

# Target balanced-chunk size in bytes. Chosen so that compressed chunks sit
# in the typical local-disk / S3 object-store sweet spot (~1 MiB).
_BALANCED_TARGET_BYTES = 1 * 1024 * 1024


def _balanced_chunks_1d(
    n_timesteps: int,
    n_cells: int,
    itemsize: int,
) -> tuple[int, int]:
    """Return a ``(time_chunk, cell_chunk)`` pair close to the target size."""
    target = _BALANCED_TARGET_BYTES // max(itemsize, 1)
    if n_timesteps <= 0 or n_cells <= 0:
        return (1, max(n_cells, 1))
    # Keep ``cell_chunk = n_cells`` whenever it already fits - readers almost
    # always consume a whole timestep at once.
    if n_cells <= target:
        time_chunk = max(1, min(n_timesteps, target // n_cells))
        return (time_chunk, n_cells)
    cell_chunk = min(n_cells, max(1, target))
    return (1, cell_chunk)


def _balanced_chunks_2d(
    n_timesteps: int,
    n_layers: int,
    n_cells: int,
    itemsize: int,
) -> tuple[int, int, int]:
    """Return ``(time_chunk, layer_chunk, cell_chunk)`` near the target size."""
    per_step = n_layers * n_cells * max(itemsize, 1)
    if per_step <= _BALANCED_TARGET_BYTES and n_timesteps > 0:
        time_chunk = max(1, min(n_timesteps, _BALANCED_TARGET_BYTES // per_step))
        return (time_chunk, n_layers, n_cells)
    # Single-timestep chunks, but split cells if the step is too big.
    cell_chunk = max(
        1,
        _BALANCED_TARGET_BYTES // (n_layers * max(itemsize, 1)),
    )
    cell_chunk = min(n_cells, cell_chunk)
    return (1, n_layers, cell_chunk)


def _field_name_from_target(target: zarr.Group, variable: str) -> str:
    """Return the canonical field name for a ``(target_group, variable)`` pair.

    The registry keys data by ``public_name`` (e.g. ``watertable_depth``) and
    maps each entry to a ``zarr_path`` (e.g. ``derived/watertable_depth``).
    Write callers that pass ``subgroup="derived"`` only supply the tail of the
    path, so we recompose the candidate zarr_path and look the descriptor up.
    Returns an empty string when no registered field matches.
    """
    path = target.path or ""
    candidate = f"{path}/{variable}" if path else variable
    for name, desc in field_registry.FIELD_REGISTRY.items():
        if desc.zarr_path == candidate or desc.public_name == variable:
            return name
    return ""


def _update_attrs(node: Any, attrs: dict[str, object]) -> Any:
    """Apply one merged metadata write to a Zarr group/array."""
    if not attrs:
        return node
    return node.update_attributes(attrs)


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
    """Return the path string passed to LocalStore."""
    return str(_windows_long_path(path)) if os.name == "nt" else str(path)


def _ensure_local_zarr_node_dir(store_path: Path, zarr_path: str | None = None) -> None:
    """Create the local directory backing a Zarr node before metadata writes."""
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


class SimulationZarr:
    def __init__(self, path: Path | str, *, balanced: bool = False) -> None:
        self._path = Path(path)
        self._balanced = bool(balanced)
        self._on_close: Callable[[SimulationZarr], None] | None = None
        if _is_zip_store_path(self._path):
            self._store = zarr.storage.ZipStore(str(self._path), mode="r")
            self._root = zarr.open_group(self._store, mode="r")
        else:
            self._store = zarr.storage.LocalStore(_local_store_path_arg(self._path))
            self._root = zarr.open_group(self._store, mode="a")

    @classmethod
    def create(
        cls,
        path: Path | str,
        *,
        n_cells: int,
        n_layers: int,
        cell_types: list[str] | None = None,
        geographic_fingerprint: str | None = None,
        balanced: bool = False,
    ) -> SimulationZarr:
        path = Path(path)
        _ensure_local_zarr_node_dir(path)
        store = zarr.storage.LocalStore(_local_store_path_arg(path))
        root = zarr.open_group(store, mode="w")
        root_attrs: dict[str, object] = {
            "Conventions": CF_CONVENTIONS,
            "hydromodpy_version": _HMP_VERSION,
            "zarr_schema_version": ZARR_SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "n_cells": n_cells,
            "n_layers": n_layers,
        }
        if cell_types is not None:
            root_attrs["cell_types"] = cell_types
        if geographic_fingerprint is not None:
            root_attrs["geographic_fingerprint"] = geographic_fingerprint
        if balanced:
            root_attrs["chunking"] = "balanced"
        root = _update_attrs(root, root_attrs)

        # ``geographic`` is intentionally omitted: rasters now live in the
        # workspace-level content-addressable cache
        # (see :mod:`hydromodpy.results.geographic_cache`). Resolution goes
        # through the fingerprint attribute above.
        for sub in _SUBGROUPS:
            _ensure_local_zarr_node_dir(path, sub)
            root.create_group(sub)

        instance = cls.__new__(cls)
        instance._path = path
        instance._store = store
        instance._root = root
        instance._balanced = bool(balanced)
        instance._on_close = None
        return instance

    def _ensure_child_dir(self, target: zarr.Group, name: str) -> None:
        _ensure_local_zarr_node_dir(self._path, _child_zarr_path(target, name))

    @property
    def root(self) -> zarr.Group:
        return self._root

    @property
    def path(self) -> Path:
        return self._path

    # -- Geographic fingerprint ---------------------------------------------

    @property
    def geographic_fingerprint(self) -> str | None:
        """Fingerprint pointing at the shared workspace ``geographic`` cache.

        Simulations no longer duplicate DEM/geology rasters inside their Zarr
        store - instead they write the SHA-256 fingerprint computed by
        :class:`~hydromodpy.results.geographic_cache.GeographicCache` here.
        """
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
        """Return the cache directory for this simulation's fingerprint, if any.

        The caller owns the mapping from workspace root to cache location.
        Returns ``None`` when the simulation carries no fingerprint.
        """
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
        *,
        start_index: int = 0,
    ) -> None:
        mesh = self._root.require_group("mesh")

        self._ensure_child_dir(mesh, "vertices")
        vertices_arr = mesh.create_array(
            "vertices",
            data=vertices.astype("float64"),
            overwrite=True,
        )
        vertices_arr = _update_attrs(
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
            data=face_node_connectivity.astype("int32"),
            overwrite=True,
        )
        fnc = _update_attrs(
            fnc,
            {
                "cf_role": "face_node_connectivity",
                "long_name": "Mapping from every face to its corner nodes",
                "start_index": start_index,
            },
        )

        self._ensure_child_dir(mesh, "z_interfaces")
        z_arr = mesh.create_array(
            "z_interfaces",
            data=z_interfaces.astype("float64"),
            overwrite=True,
        )
        z_arr = _update_attrs(
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
                data=layer_indices.astype("int32"),
                overwrite=True,
            )
        if source_cell_indices is not None:
            self._ensure_child_dir(mesh, "source_cell_indices")
            mesh.create_array(
                "source_cell_indices",
                data=source_cell_indices.astype("int32"),
                overwrite=True,
            )

        mesh = _update_attrs(
            mesh,
            {
                "start_index": start_index,
                "n_nodes": vertices.shape[0],
                "n_cells": face_node_connectivity.shape[0],
                "n_layers": len(z_interfaces) - 1,
            },
        )

        # UGRID-1.0 topology: create a scalar "mesh" array (value 0) that
        # carries the topology attributes. Downstream xarray readers resolve
        # node_coordinates / face_node_connectivity via these attrs.
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

    # -- Time / CRS metadata --------------------------------------------------

    def write_time(
        self,
        values: np.ndarray,
        *,
        epoch: str = "1970-01-01T00:00:00",
        calendar: str = "proleptic_gregorian",
        units: str = "seconds since 1970-01-01T00:00:00",
    ) -> None:
        """Write the CF time coordinate at the store root.

        ``values`` must be integer seconds since ``epoch``. Creates (or
        overwrites) a ``time`` array with the CF ``units``, ``calendar`` and
        ``standard_name`` attributes required to round-trip through xarray.
        """
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
        """Write a scalar CF ``grid_mapping`` variable named ``crs``.

        The registry attaches ``grid_mapping = "crs"`` to every registered
        field, so this variable makes exported Zarr stores self-describing
        for CF-aware consumers (xarray, IRIS, CDO, ...).
        """
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
        if subgroup:
            if subgroup not in self._root:
                self._ensure_child_dir(self._root, subgroup)
                self._root.create_group(subgroup)
            target = self._root[subgroup]
        else:
            target = self._root

        itemsize = values.dtype.itemsize
        if values.ndim == 1:
            full_shape = (n_timesteps, values.shape[0]) if n_timesteps else None
            if self._balanced and n_timesteps is not None:
                chunk_shape = _balanced_chunks_1d(
                    n_timesteps,
                    values.shape[0],
                    itemsize,
                )
            else:
                chunk_shape = (1, values.shape[0])
        elif values.ndim == 2:
            n_layers, n_cells = values.shape
            full_shape = (n_timesteps, n_layers, n_cells) if n_timesteps else None
            if self._balanced and n_timesteps is not None:
                chunk_shape = _balanced_chunks_2d(
                    n_timesteps,
                    n_layers,
                    n_cells,
                    itemsize,
                )
            else:
                chunk_shape = (1, n_layers, n_cells)
        else:
            raise ValueError(f"Expected 1D or 2D values, got shape {values.shape}")

        if variable not in target:
            if n_timesteps is None:
                raise ValueError(f"n_timesteps required on first write of '{variable}'")
            self._ensure_child_dir(target, variable)
            target.create_array(
                variable,
                shape=full_shape,
                chunks=chunk_shape,
                dtype=values.dtype,
                compressors=BLOSC_ZSTD,
                fill_value=np.nan,
                overwrite=True,
            )
            self._attach_cf_attrs(target, variable)

        arr = target[variable]
        if values.ndim == 1:
            arr[timestep, :] = values
        else:
            arr[timestep, :, :] = values

    def _attach_cf_attrs(self, target: zarr.Group, variable: str) -> None:
        """Attach CF-1.11 attributes to a newly created field array.

        Silently ignores variables that are not in the canonical registry so
        that experimental / user-defined fields do not break writes. When the
        field IS registered, the ``standard_name``, ``long_name``, ``units``,
        ``cell_methods``, ``coordinates`` and ``grid_mapping`` attributes are
        attached in one shot.
        """
        name = _field_name_from_target(target, variable)
        if not name:
            return
        try:
            attrs = field_registry.cf_attrs(name)
        except KeyError:
            return
        arr = target[variable]
        _update_attrs(arr, attrs)

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
            data = target[variable][timestep]
        else:
            for loc_name in (None, "derived", "budget"):
                loc = self._root if loc_name is None else self._root.get(loc_name)
                if loc is not None and variable in loc:
                    data = loc[variable][timestep]
                    break
            else:
                raise KeyError(f"Variable '{variable}' not found")

        if layer is not None and data.ndim == 2:
            return data[layer]
        return data

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
        geo = self._root.require_group("geographic")
        self._ensure_child_dir(geo, name)
        geo.create_array(
            name,
            data=data,
            compressors=BLOSC_ZSTD,
            overwrite=True,
        )
        arr = geo[name]
        _update_attrs(
            arr,
            {
                "transform": list(transform),
                "crs": crs,
                "nodata": nodata,
                "shape": list(data.shape),
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
        """Persist one input forcing timeseries into ``forcing/<variable>/<station_id>``."""
        self._ensure_child_dir(self._root, "forcing")
        forcing = self._root.require_group("forcing")
        self._ensure_child_dir(forcing, variable)
        var_grp = forcing.require_group(variable)
        self._ensure_child_dir(var_grp, station_id)
        sta_grp = var_grp.require_group(station_id)

        ts_bytes = np.asarray(timestamps, dtype="datetime64[ns]").view("int64")
        self._ensure_child_dir(sta_grp, "timestamps")
        sta_grp.create_array("timestamps", data=ts_bytes, overwrite=True)
        self._ensure_child_dir(sta_grp, "values")
        sta_grp.create_array("values", data=np.asarray(values, dtype="float64"), overwrite=True)
        _update_attrs(
            sta_grp,
            {
                "unit": unit,
                "source": source,
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
        """Persist one static forcing field (e.g. geology zones) into ``forcing/<variable>``."""
        self._ensure_child_dir(self._root, "forcing")
        forcing = self._root.require_group("forcing")
        self._ensure_child_dir(forcing, variable)
        forcing.create_array(
            variable,
            data=data,
            compressors=BLOSC_ZSTD,
            overwrite=True,
        )
        _update_attrs(forcing[variable], {"unit": unit, "source": source})

    def read_forcing_timeseries(
        self,
        variable: str,
        station_id: str,
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """Read a forcing timeseries. Returns (timestamps, values, attrs)."""
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

    # -- xarray export --------------------------------------------------------

    def to_xarray(self):
        """Return an ``xarray.Dataset`` view over the simulation fields.

        Collects every registered field that has been written to this Zarr
        store (root, ``derived/`` and ``budget/`` groups are scanned) and
        wraps them in a CF/UGRID-aware :class:`xarray.Dataset`. Non-field
        bookkeeping arrays (mesh topology, time, crs) are included as
        coordinate variables so that downstream consumers can round-trip
        through xarray without losing CF metadata.
        """
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
                # fall back to generic dims when the shape does not match the
                # stored array (e.g. a field was written with an extra axis)
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
        """Consolidate Zarr metadata into a single ``.zmetadata`` entry.

        Must be called once the simulation is fully written, so that readers
        can open the store without scanning every array (zarr v3 metadata
        consolidation). Silently ignores zip-backed stores (already frozen).
        """
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
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("consolidate_metadata failed: %s", exc)

    # -- Packing -------------------------------------------------------------

    def pack_to_zip(self) -> Path:
        """Compact the directory-based Zarr store into a ``.zarr.zip`` file.

        The original directory is removed after successful packing.
        Returns the path to the new zip file.
        """
        if not self._path.is_dir():
            return self._path

        self.close()

        zip_path = self._path.with_suffix(ZARR_ZIP_SUFFIX)
        tmp_path = zip_path.with_name(f"{zip_path.name}.tmp")
        if tmp_path.exists():
            tmp_path.unlink()

        with zipfile.ZipFile(str(tmp_path), "w", compression=zipfile.ZIP_STORED) as zf:
            for fpath in sorted(self._path.rglob("*")):
                if fpath.is_file():
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

        shutil.rmtree(self._path)
        logger.debug("Packed %s -> %s", self._path.name, zip_path.name)

        self._path = zip_path
        self._store = zarr.storage.ZipStore(str(zip_path), mode="r")
        self._root = zarr.open_group(self._store, mode="r")
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

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
