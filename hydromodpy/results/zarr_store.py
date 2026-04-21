from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path

import numpy as np
import zarr
import zarr.codecs

from hydromodpy.results import field_registry

logger = logging.getLogger(__name__)

BLOSC_ZSTD = zarr.codecs.BloscCodec(cname="zstd", clevel=3)

_SUBGROUPS = ("mesh", "derived", "budget", "pathlines", "geographic", "forcing")

# CF-1.11 + UGRID-1.0 root conventions string attached to every simulation
# Zarr store (see :mod:`hydromodpy.results.field_registry`).
CF_CONVENTIONS = "CF-1.11 UGRID-1.0"


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


class SimulationZarr:

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        if self._path.suffix == ".zip" or str(self._path).endswith(".zarr.zip"):
            self._store = zarr.storage.ZipStore(str(self._path), mode="r")
            self._root = zarr.open_group(self._store, mode="r")
        else:
            self._store = zarr.storage.LocalStore(str(self._path))
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
    ) -> SimulationZarr:
        path = Path(path)
        store = zarr.storage.LocalStore(str(path))
        root = zarr.open_group(store, mode="w")

        root.attrs["Conventions"] = CF_CONVENTIONS
        root.attrs["n_cells"] = n_cells
        root.attrs["n_layers"] = n_layers
        if cell_types is not None:
            root.attrs["cell_types"] = cell_types
        if geographic_fingerprint is not None:
            root.attrs["geographic_fingerprint"] = geographic_fingerprint

        # ``geographic`` is intentionally omitted: rasters now live in the
        # workspace-level content-addressable cache
        # (see :mod:`hydromodpy.results.geographic_cache`). Resolution goes
        # through the fingerprint attribute above.
        for sub in _SUBGROUPS:
            root.create_group(sub)

        instance = cls.__new__(cls)
        instance._path = path
        instance._store = store
        instance._root = root
        return instance

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
        store — instead they write the SHA-256 fingerprint computed by
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

        vertices_arr = mesh.create_array(
            "vertices", data=vertices.astype("float64"), overwrite=True,
        )
        vertices_arr.attrs["long_name"] = "Mesh node coordinates (x, y, z)"
        vertices_arr.attrs["units"] = "m"
        vertices_arr.attrs["cf_role"] = "mesh_node_coordinates"

        fnc = mesh.create_array(
            "face_node_connectivity",
            data=face_node_connectivity.astype("int32"),
            overwrite=True,
        )
        fnc.attrs["cf_role"] = "face_node_connectivity"
        fnc.attrs["long_name"] = "Mapping from every face to its corner nodes"
        fnc.attrs["start_index"] = start_index

        z_arr = mesh.create_array(
            "z_interfaces", data=z_interfaces.astype("float64"), overwrite=True,
        )
        z_arr.attrs["long_name"] = "Altitude of layer interfaces"
        z_arr.attrs["units"] = "m"
        z_arr.attrs["standard_name"] = "altitude"
        z_arr.attrs["positive"] = "up"

        if layer_indices is not None:
            mesh.create_array(
                "layer_indices",
                data=layer_indices.astype("int32"),
                overwrite=True,
            )
        if source_cell_indices is not None:
            mesh.create_array(
                "source_cell_indices",
                data=source_cell_indices.astype("int32"),
                overwrite=True,
            )

        mesh.attrs["start_index"] = start_index
        mesh.attrs["n_nodes"] = vertices.shape[0]
        mesh.attrs["n_cells"] = face_node_connectivity.shape[0]
        mesh.attrs["n_layers"] = len(z_interfaces) - 1

        # UGRID-1.0 topology: create a scalar "mesh" array (value 0) that
        # carries the topology attributes. Downstream xarray readers resolve
        # node_coordinates / face_node_connectivity via these attrs.
        topo = mesh.create_array(
            "topology", data=np.zeros((), dtype="int32"), overwrite=True,
        )
        topo.attrs["cf_role"] = "mesh_topology"
        topo.attrs["long_name"] = "UGRID 2D topology of the simulation mesh"
        topo.attrs["topology_dimension"] = 2
        topo.attrs["node_coordinates"] = "vertices"
        topo.attrs["face_node_connectivity"] = "face_node_connectivity"

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
        time_arr = self._root.create_array(
            "time", data=np.asarray(values, dtype="int64"), overwrite=True,
        )
        time_arr.attrs["units"] = units
        time_arr.attrs["calendar"] = calendar
        time_arr.attrs["standard_name"] = "time"
        time_arr.attrs["long_name"] = "Simulation time"
        time_arr.attrs["axis"] = "T"
        self._root.attrs["time_epoch"] = epoch

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
        crs_arr = self._root.create_array(
            "crs", data=np.zeros((), dtype="int32"), overwrite=True,
        )
        crs_arr.attrs["grid_mapping_name"] = grid_mapping_name
        if crs_wkt:
            crs_arr.attrs["crs_wkt"] = crs_wkt
        if epsg_code is not None:
            crs_arr.attrs["epsg_code"] = int(epsg_code)
        if semi_major_axis is not None:
            crs_arr.attrs["semi_major_axis"] = float(semi_major_axis)
        if inverse_flattening is not None:
            crs_arr.attrs["inverse_flattening"] = float(inverse_flattening)

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
                self._root.create_group(subgroup)
            target = self._root[subgroup]
        else:
            target = self._root

        if values.ndim == 1:
            full_shape = (n_timesteps, values.shape[0]) if n_timesteps else None
            chunk_shape = (1, values.shape[0])
        elif values.ndim == 2:
            n_layers, n_cells = values.shape
            full_shape = (n_timesteps, n_layers, n_cells) if n_timesteps else None
            chunk_shape = (1, n_layers, n_cells)
        else:
            raise ValueError(f"Expected 1D or 2D values, got shape {values.shape}")

        if variable not in target:
            if n_timesteps is None:
                raise ValueError(
                    f"n_timesteps required on first write of '{variable}'"
                )
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
        for key, value in attrs.items():
            arr.attrs[key] = value

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
                raise KeyError(
                    f"Variable '{variable}' not found in subgroup '{subgroup}'"
                )
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
        geo.create_array(
            name, data=data, compressors=BLOSC_ZSTD, overwrite=True,
        )
        arr = geo[name]
        arr.attrs["transform"] = list(transform)
        arr.attrs["crs"] = crs
        arr.attrs["nodata"] = nodata
        arr.attrs["shape"] = list(data.shape)

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
        forcing = self._root.require_group("forcing")
        var_grp = forcing.require_group(variable)
        sta_grp = var_grp.require_group(station_id)

        ts_bytes = np.asarray(timestamps, dtype="datetime64[ns]").view("int64")
        sta_grp.create_array("timestamps", data=ts_bytes, overwrite=True)
        sta_grp.create_array("values", data=np.asarray(values, dtype="float64"), overwrite=True)
        sta_grp.attrs["unit"] = unit
        sta_grp.attrs["source"] = source
        sta_grp.attrs["n_records"] = int(len(values))

    def write_forcing_field(
        self,
        variable: str,
        data: np.ndarray,
        *,
        unit: str = "",
        source: str = "",
    ) -> None:
        """Persist one static forcing field (e.g. geology zones) into ``forcing/<variable>``."""
        forcing = self._root.require_group("forcing")
        forcing.create_array(
            variable, data=data, compressors=BLOSC_ZSTD, overwrite=True,
        )
        forcing[variable].attrs["unit"] = unit
        forcing[variable].attrs["source"] = source

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

    # -- Packing -------------------------------------------------------------

    def pack_to_zip(self) -> Path:
        """Compact the directory-based Zarr store into a ``.zarr.zip`` file.

        The original directory is removed after successful packing.
        Returns the path to the new zip file.
        """
        if not self._path.is_dir():
            return self._path

        self.close()

        zip_path = self._path.with_suffix(".zarr.zip")
        with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_STORED) as zf:
            for fpath in sorted(self._path.rglob("*")):
                if fpath.is_file():
                    arcname = str(fpath.relative_to(self._path))
                    zf.write(str(fpath), arcname)

        shutil.rmtree(self._path, ignore_errors=True)
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

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
