from __future__ import annotations

from pathlib import Path

import numpy as np
import zarr
import zarr.codecs

BLOSC_ZSTD = zarr.codecs.BloscCodec(cname="zstd", clevel=3)

_SUBGROUPS = ("mesh", "derived", "budget", "pathlines", "geographic")


class SimulationZarr:

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
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
    ) -> SimulationZarr:
        path = Path(path)
        store = zarr.storage.LocalStore(str(path))
        root = zarr.open_group(store, mode="w")

        root.attrs["n_cells"] = n_cells
        root.attrs["n_layers"] = n_layers
        if cell_types is not None:
            root.attrs["cell_types"] = cell_types

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
        mesh = self._root["mesh"]

        mesh.create_array(
            "vertices", data=vertices.astype("float64"), overwrite=True,
        )
        mesh.create_array(
            "face_node_connectivity",
            data=face_node_connectivity.astype("int32"),
            overwrite=True,
        )
        mesh.create_array(
            "z_interfaces", data=z_interfaces.astype("float64"), overwrite=True,
        )

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

        arr = target[variable]
        if values.ndim == 1:
            arr[timestep, :] = values
        else:
            arr[timestep, :, :] = values

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
        geo = self._root["geographic"]
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
