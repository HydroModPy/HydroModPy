# -*- coding: utf-8 -*-
"""Flow-oriented NetCDF post-processing exports."""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.analysis.postprocess.netcdf.netcdf_writer import NetcdfWriter
from hydromodpy.core.tools import get_logger
from hydromodpy.core.tools.filesystem import create_folder

logger = get_logger(__name__)


class FlowNetcdfPostprocess(NetcdfWriter):
    """Convert flow postprocess ``.npy`` outputs to NetCDF files."""

    FLOW_OUTPUTS: tuple[str, ...] = (
        "watertable_elevation",
        "watertable_depth",
        "seepage_areas",
        "outflow_drain",
        "groundwater_flux",
        "saturated_storage",
        "groundwater_storage",
        "accumulation_flux",
    )

    def __init__(
        self,
        geographic: object,
        model_modflow: object,
        datetime_format: bool = True,
        *,
        store: Any = None,
        sim_id: str | None = None,
    ) -> None:
        logger.info("Exporting flow NetCDF outputs for model %s", model_modflow.model_name)

        self.geographic = geographic
        self.model_name = model_modflow.model_name
        self.model_folder = model_modflow.model_folder
        self.datetime_format = datetime_format
        self.recharge = model_modflow.recharge
        self._store = store
        self._sim_id = sim_id
        self.base_raster_path = getattr(
            model_modflow,
            "dem_watershed_path",
            geographic.watershed_dem,
        )

        self.full_path = os.path.join(self.model_folder, self.model_name)
        self.save_file = os.path.join(self.full_path, "_postprocess")
        if not os.path.exists(self.save_file):
            create_folder(self.save_file)

        self.netcdf_file = os.path.join(self.save_file, "_netcdf")
        if not os.path.exists(self.netcdf_file):
            create_folder(self.netcdf_file)

        times = self._resolve_time_axis(self.recharge, self.datetime_format)
        self._export_flow_outputs(times=times)
        self._export_additional_outputs(times=times)

    @staticmethod
    def _resolve_time_axis(recharge: Any, datetime_format: bool) -> Any:
        """Resolve time axis from model recharge according to legacy rules."""
        if datetime_format:
            if isinstance(recharge, (int, float)):
                return [0]
            if isinstance(recharge, pd.Series):
                return recharge.index
            if isinstance(recharge, dict):
                return range(len(recharge))
            if hasattr(recharge, "index"):
                return recharge.index
            return np.array(range(len(recharge)))

        if isinstance(recharge, (int, float)):
            return [0]

        if isinstance(recharge, dict):
            return pd.Series(range(len(recharge)), index=range(len(recharge)))

        return np.array(range(len(recharge)))

    def _load_field_from_store(self, name: str) -> dict | None:
        """Load a spatial field from the ResultStore as a timestep dict."""
        if self._store is None or self._sim_id is None:
            return None
        from hydromodpy.analysis.display.common import load_field_dict_from_store

        return load_field_dict_from_store(self._store, self._sim_id, name)

    def _export_named_output(self, *, name: str, times: Any) -> bool:
        """Export one named flow output when available."""
        data = self._load_field_from_store(name)
        if data is None:
            return False

        # Store fields are flat 1D — reshape to 2D grid for NetCDF export.
        import rasterio
        with rasterio.open(self.base_raster_path) as src:
            grid_shape = (src.height, src.width)
        data = {
            k: v.reshape(grid_shape) if v.size == grid_shape[0] * grid_shape[1] else v
            for k, v in data.items()
        }

        try:
            self.export_netcdf(
                data,
                base_path=self.base_raster_path,
                out_path=os.path.join(self.netcdf_file, f"{name}.nc"),
                base_crs=self.geographic.crs_proj,
                times=times,
            )
            return True
        except Exception:
            return False

    def _export_flow_outputs(self, *, times: Any) -> None:
        """Export all configured flow outputs."""
        for output_name in self.FLOW_OUTPUTS:
            self._export_named_output(name=output_name, times=times)

    def _export_additional_outputs(self, *, times: Any) -> None:
        """Subclass hook for transport-specific NetCDF outputs."""


__all__ = [
    "FlowNetcdfPostprocess",
]
