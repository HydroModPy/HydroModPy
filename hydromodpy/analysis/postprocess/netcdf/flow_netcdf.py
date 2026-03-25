# -*- coding: utf-8 -*-
"""Flow-oriented NetCDF post-processing exports."""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.analysis.postprocess.netcdf.netcdf_writer import NetcdfWriter
from hydromodpy.core.tools import get_logger, toolbox

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
    ) -> None:
        logger.info("Exporting flow NetCDF outputs for model %s", model_modflow.model_name)

        self.geographic = geographic
        self.model_name = model_modflow.model_name
        self.model_folder = model_modflow.model_folder
        self.datetime_format = datetime_format
        self.recharge = model_modflow.recharge
        self.base_raster_path = getattr(
            model_modflow,
            "dem_watershed_path",
            geographic.watershed_dem,
        )

        self.full_path = os.path.join(self.model_folder, self.model_name)
        self.save_file = os.path.join(self.full_path, "_postprocess")
        if not os.path.exists(self.save_file):
            toolbox.create_folder(self.save_file)

        self.netcdf_file = os.path.join(self.save_file, "_netcdf")
        if not os.path.exists(self.netcdf_file):
            toolbox.create_folder(self.netcdf_file)

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

    def _try_load_npy(self, name: str) -> Any | None:
        """Attempt to load one postprocess ``.npy`` dict by variable name."""
        try:
            return np.load(
                os.path.join(self.save_file, f"{name}.npy"),
                allow_pickle=True,
            ).item()
        except Exception:
            return None

    def _export_named_output(self, *, name: str, times: Any) -> bool:
        """Export one named flow output when available."""
        data = self._try_load_npy(name)
        if data is None:
            return False

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
