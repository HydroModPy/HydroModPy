# -*- coding: utf-8 -*-
"""Shared writer utilities for postprocess NetCDF exports."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
import rasterio as rio
import rasterio.features  # noqa: F401  # keep import to preserve rasterio behavior
import xarray as xr

xr.set_options(keep_attrs=True)

from hydromodpy.core.tools import get_logger

logger = get_logger(__name__)


class NetcdfWriter:
    """Common NetCDF writer used by flow and transport exporters."""

    @staticmethod
    def compute_scale_and_offset(min_value: float, max_value: float, n_bits: int) -> tuple[float, float]:
        """Compute packing parameters for integer-encoded NetCDF outputs."""
        scale_factor = (max_value - min_value) / (2**n_bits - 1)
        add_offset = min_value + 2 ** (n_bits - 1) * scale_factor
        return scale_factor, add_offset

    @staticmethod
    def pack_value(unpacked_value: float, scale_factor: float, add_offset: float) -> float:
        """Pack one float value according to NetCDF scale/offset parameters."""
        logger.debug(
            "Packing value %.6f with scale %.6f and offset %.6f",
            unpacked_value,
            scale_factor,
            add_offset,
        )
        return (unpacked_value - add_offset) / scale_factor

    @staticmethod
    def unpack_value(packed_value: float, scale_factor: float, add_offset: float) -> float:
        """Unpack one integer-encoded value according to NetCDF metadata."""
        return packed_value * scale_factor + add_offset

    @staticmethod
    def _ordered_data_values(data: Any) -> list[np.ndarray]:
        """Return ordered grid values from dict/list-like postprocess outputs."""
        if isinstance(data, Mapping):
            items = list(data.items())
            try:
                items = sorted(items, key=lambda item: item[0])
            except Exception:
                pass
            return [np.asarray(value) for _, value in items]

        if isinstance(data, np.ndarray):
            if data.ndim == 3:
                return [np.asarray(layer) for layer in data]
            if data.ndim == 2:
                return [np.asarray(data)]

        if isinstance(data, Sequence):
            return [np.asarray(value) for value in data]

        return []

    @staticmethod
    def _normalize_time_coordinate(times: Any) -> Any:
        """Normalize optional time coordinate for xarray assignment."""
        if isinstance(times, pd.Series):
            return times.index
        try:
            len(times)  # type: ignore[arg-type]
            return times
        except TypeError:
            return None

    def _apply_common_encoding(
        self,
        dataset: xr.Dataset,
        *,
        variable_name: str,
    ) -> xr.Dataset:
        """Apply shared packing metadata to one exported variable."""

        bound_max = float(dataset[variable_name].max())
        bound_min = float(dataset[variable_name].min())
        if bound_min < 0:
            bound_min *= 1.1
        elif bound_min > 0:
            bound_min /= 1.1
        else:
            bound_min = bound_min - 0.01 * bound_max

        scale_factor, add_offset = self.compute_scale_and_offset(bound_min, bound_max, 16)
        dataset[variable_name].encoding["scale_factor"] = scale_factor
        dataset[variable_name].encoding["add_offset"] = add_offset
        dataset[variable_name].encoding["dtype"] = "int16"
        dataset[variable_name].encoding["_FillValue"] = -32768
        return dataset

    def export_netcdf(
        self,
        data: Any,
        *,
        base_path: str,
        out_path: str,
        base_crs: Any = None,
        times: Any = None,
        y: Any = None,
        x: Any = None,
        append: bool = False,
    ) -> None:
        """Export one time-indexed grid dataset to NetCDF."""
        if isinstance(base_crs, str):
            base_crs = rio.crs.CRS.from_string(base_crs)
        elif isinstance(base_crs, int):
            base_crs = rio.crs.CRS.from_epsg(base_crs)

        values = self._ordered_data_values(data)
        if not values:
            return

        with rio.open(base_path, "r") as base:
            base_profile = base.profile
            if base_crs and not base_profile.get("crs"):
                base_profile["crs"] = base_crs
            val_for_mask = base.read(1)

        reso_x, _, x_min, _, reso_y, y_max, _, _, _ = list(base_profile["transform"])
        if x is None:
            x_vals = list(
                np.arange(
                    x_min + reso_x / 2,
                    x_min + reso_x * base_profile["width"] + reso_x / 2,
                    reso_x,
                )
            )
        else:
            x_vals = x

        if y is None:
            y_vals = list(
                np.arange(
                    y_max + reso_y / 2,
                    y_max + reso_y * base_profile["height"] + reso_y / 2,
                    reso_y,
                )
            )
        else:
            y_vals = y

        times = self._normalize_time_coordinate(times)
        matrix = np.asarray(values)
        if matrix.ndim == 2:
            matrix = np.expand_dims(matrix, axis=0)

        da = xr.DataArray(matrix, dims=("time", "y", "x"))
        if times is not None and len(times) == matrix.shape[0]:
            da = da.assign_coords(
                {
                    "time": ("time", times),
                    "y": ("y", y_vals),
                    "x": ("x", x_vals),
                }
            )
        else:
            da = da.assign_coords({"y": ("y", y_vals), "x": ("x", x_vals)})

        nodata = base_profile.get("nodata")
        if nodata is not None:
            da = da.where(val_for_mask != nodata)

        dataset = xr.Dataset()
        main_var = os.path.splitext(os.path.split(out_path)[-1])[0]
        dataset[main_var] = da

        if append:
            with xr.open_dataset(out_path, decode_coords="all", decode_times=True) as ds_prev:
                dataset = xr.concat([ds_prev, dataset], dim="time")

        dataset.x.attrs = {
            "standard_name": "projection_x_coordinate",
            "long_name": "x coordinate of projection",
            "units": "Meter",
        }
        dataset.y.attrs = {
            "standard_name": "projection_y_coordinate",
            "long_name": "y coordinate of projection",
            "units": "Meter",
        }

        crs_to_write = base_profile.get("crs") or base_crs
        if crs_to_write is not None:
            dataset.rio.write_crs(crs_to_write, inplace=True)

        self._apply_common_encoding(dataset, variable_name=main_var).to_netcdf(out_path)

    def export_cell_netcdf(
        self,
        data: Any,
        *,
        out_path: str,
        cell_x: Any,
        cell_y: Any,
        cell_area: Any,
        base_crs: Any = None,
        times: Any = None,
        append: bool = False,
    ) -> None:
        """Export one time-indexed per-cell dataset to NetCDF."""

        values = self._ordered_data_values(data)
        if not values:
            return

        matrix = np.asarray(values, dtype=float)
        if matrix.ndim == 1:
            matrix = np.expand_dims(matrix, axis=0)

        cell_x = np.asarray(cell_x, dtype=float).reshape(-1)
        cell_y = np.asarray(cell_y, dtype=float).reshape(-1)
        cell_area = np.asarray(cell_area, dtype=float).reshape(-1)
        n_cells = int(matrix.shape[-1])
        if (
            cell_x.size != n_cells
            or cell_y.size != n_cells
            or cell_area.size != n_cells
        ):
            raise ValueError(
                "Cell NetCDF export requires cell_x/cell_y/cell_area sized to the number of cells."
            )

        times = self._normalize_time_coordinate(times)
        coords: dict[str, tuple[str, Any]] = {
            "cell": ("cell", np.arange(n_cells, dtype=int)),
            "cell_x": ("cell", cell_x),
            "cell_y": ("cell", cell_y),
            "cell_area": ("cell", cell_area),
        }
        if times is not None and len(times) == matrix.shape[0]:
            coords["time"] = ("time", times)

        dataset = xr.Dataset()
        main_var = os.path.splitext(os.path.split(out_path)[-1])[0]
        dataset[main_var] = xr.DataArray(matrix, dims=("time", "cell"), coords=coords)

        if append:
            with xr.open_dataset(out_path, decode_coords="all", decode_times=True) as ds_prev:
                dataset = xr.concat([ds_prev, dataset], dim="time")

        dataset.cell.attrs = {
            "long_name": "solver mesh cell identifier",
        }
        dataset.cell_x.attrs = {
            "standard_name": "projection_x_coordinate",
            "long_name": "cell centroid x coordinate of projection",
            "units": "Meter",
        }
        dataset.cell_y.attrs = {
            "standard_name": "projection_y_coordinate",
            "long_name": "cell centroid y coordinate of projection",
            "units": "Meter",
        }
        dataset.cell_area.attrs = {
            "long_name": "planar cell area",
            "units": "m2",
        }

        if base_crs is not None:
            if isinstance(base_crs, str):
                dataset.attrs["crs"] = base_crs
            elif isinstance(base_crs, int):
                dataset.attrs["crs"] = f"EPSG:{base_crs}"
            else:
                dataset.attrs["crs"] = str(base_crs)

        self._apply_common_encoding(dataset, variable_name=main_var).to_netcdf(out_path)


__all__ = [
    "NetcdfWriter",
]

