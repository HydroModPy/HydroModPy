# -*- coding: utf-8 -*-
"""Flow-oriented time-series post-processing utilities."""

from __future__ import annotations

import os
import warnings
from typing import Any, Callable

import numpy as np
import pandas as pd
import rasterio

from hydromodpy.postprocess.flow.intermittency import apply_intermittency_columns
from hydromodpy.tools import get_logger, toolbox

logger = get_logger(__name__)
# Silence pandas masked-to-nan spam when handling masked arrays
warnings.filterwarnings("ignore", message=".*converting a masked element to nan.*")


class FlowTimeseriesPostprocess:
    """Export flow postprocess outputs as watershed/subbasin time-series CSV files."""

    def __init__(
        self,
        geographic: object,
        model_modflow: object,
        runoff: Any = None,
        suffix_name: str | None = None,
        datetime_format: bool = True,
        subbasin_results: bool = True,
        intermittency_yearly: bool = False,
        intermittency_monthly: bool = False,
        intermittency_weekly: bool = False,
        intermittency_daily: bool = False,
    ) -> None:
        self.suffix_name = suffix_name

        self.geographic = geographic
        self.stable_folder = geographic.stable_folder
        self.simulations = geographic.simulations_folder

        self.model_name = model_modflow.model_name
        self.model_folder = model_modflow.model_folder
        self.resolution = model_modflow.resolution
        self.recharge = model_modflow.recharge
        self.runoff = runoff

        self.intermittency_yearly = intermittency_yearly
        self.intermittency_monthly = intermittency_monthly
        self.intermittency_weekly = intermittency_weekly
        self.intermittency_daily = intermittency_daily
        self.datetime_format = datetime_format

        self.full_path = os.path.join(self.model_folder, self.model_name)
        self.tifs_file = os.path.join(self.full_path, "_postprocess", "_rasters")

        self.save_file = os.path.join(self.full_path, "_postprocess")
        if not os.path.exists(self.save_file):
            toolbox.create_folder(self.save_file)

        self.timeseries_file = os.path.join(self.save_file, "_timeseries")
        if not os.path.exists(self.timeseries_file):
            toolbox.create_folder(self.timeseries_file)

        self.watertable_elevation: dict[Any, np.ndarray] | None = None
        self.watertable_depth: dict[Any, np.ndarray] | None = None
        self.seepage_areas: dict[Any, np.ndarray] | None = None
        self.outflow_drain: dict[Any, np.ndarray] | None = None
        self.groundwater_flux: dict[Any, np.ndarray] | None = None
        self.groundwater_storage: dict[Any, np.ndarray] | None = None
        self.accumulation_flux: dict[Any, np.ndarray] | None = None

        time, recharge, runoff_series = self._normalize_forcing_series()
        self._load_flow_products()
        self._load_additional_products()

        with rasterio.open(self.geographic.watershed_dem) as src:
            dem_clip = src.read(1)
        self.cell = np.ma.masked_array(dem_clip, mask=(dem_clip < 0)).count()
        self.extract_results(dem_clip, time, recharge, runoff_series, self.timeseries_file)
        logger.info("Exported catchment time series to %s", self.timeseries_file)

        if subbasin_results:
            self._export_subbasins(time, recharge, runoff_series)

    def _normalize_forcing_series(self) -> tuple[Any, Any, Any]:
        """Normalize recharge/runoff to a common time axis."""
        time = [0]
        recharge: Any = self.recharge
        runoff: Any = np.nan

        if isinstance(self.recharge, (int, float)):
            time = [0]
            recharge = self.recharge
        if isinstance(self.recharge, pd.Series):
            time = self.recharge.index
            recharge = self.recharge.values
        if isinstance(self.recharge, dict):
            time = range(len(self.recharge))
            recharge = pd.Series(
                np.array(
                    list(({k: np.nanmean(v) for k, v in self.recharge.items()}).values())
                ),
                index=range(len(self.recharge)),
            )

        runoff = recharge * np.nan
        if self.runoff is not None and (
            not isinstance(self.runoff, pd.DataFrame) or not self.runoff.empty
        ):
            if isinstance(self.runoff, (int, float)):
                time = [0]
                runoff = self.runoff
            elif isinstance(self.runoff, pd.Series):
                time = self.runoff.index
                runoff = self.runoff.values
            elif isinstance(self.runoff, dict):
                time = range(len(self.runoff))
                runoff = pd.Series(
                    np.array([np.nanmean(v) for v in self.runoff.values()]),
                    index=range(len(self.runoff)),
                )

        return time, recharge, runoff

    def _try_load_npy(self, name: str) -> dict[Any, np.ndarray] | None:
        """Try loading one ``.npy`` dictionary from the ``_postprocess`` folder."""
        try:
            return np.load(
                os.path.join(self.save_file, f"{name}.npy"), allow_pickle=True
            ).item()
        except Exception:
            return None

    def _load_flow_products(self) -> None:
        """Load flow-derived postprocess arrays when available."""
        self.watertable_elevation = self._try_load_npy("watertable_elevation")
        self.watertable_depth = self._try_load_npy("watertable_depth")
        self.seepage_areas = self._try_load_npy("seepage_areas")
        self.outflow_drain = self._try_load_npy("outflow_drain")
        self.groundwater_flux = self._try_load_npy("groundwater_flux")
        self.groundwater_storage = self._try_load_npy("groundwater_storage")
        self.accumulation_flux = self._try_load_npy("accumulation_flux")

    def _load_additional_products(self) -> None:
        """Hook for subclasses to load non-flow products."""

    def _export_subbasins(self, time: Any, recharge: Any, runoff: Any) -> None:
        """Export one CSV per available subbasin mask."""
        try:
            zones_folder = os.path.join(self.stable_folder, "subbasin")
            for zi, zone_name in enumerate(os.listdir(zones_folder)):
                sub_file = os.path.join(self.full_path, "_subbasins", zone_name)
                if not os.path.exists(sub_file):
                    toolbox.create_folder(sub_file)
                try:
                    with rasterio.open(
                        os.path.join(zones_folder, zone_name, "watershed_dem.tif")
                    ) as src:
                        dem_clip = src.read(1)
                    self.cell = np.ma.masked_array(dem_clip, mask=(dem_clip < 0)).count()
                    self.extract_results(dem_clip, time, recharge, runoff, sub_file)
                    logger.info(
                        "Exported time series for subbasin %s to %s", zi + 1, sub_file
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _mask_grid(self, grid: np.ndarray, dem_clip: np.ndarray) -> np.ma.MaskedArray:
        """Apply DEM-based masking to one input grid."""
        return toolbox.mask_by_dem(grid, dem_clip, "==", self.geographic.nodata)

    def _reduce_max(self, grid: np.ndarray, dem_clip: np.ndarray) -> float:
        masked = self._mask_grid(grid, dem_clip)
        return float(np.nanmax(masked))

    def _reduce_mean(self, grid: np.ndarray, dem_clip: np.ndarray) -> float:
        masked = self._mask_grid(grid, dem_clip)
        masked[masked < 0] = 0  # Keep legacy behavior
        masked[masked < -1] = np.nan  # Keep legacy behavior
        return float(np.nanmean(masked))

    def _reduce_sum(self, grid: np.ndarray, dem_clip: np.ndarray) -> float:
        masked = self._mask_grid(grid, dem_clip)
        return float(np.nansum(masked))

    def _reduce_qspe(self, grid: np.ndarray, dem_clip: np.ndarray) -> float:
        masked = self._mask_grid(grid, dem_clip)
        cell = masked.count()
        if cell <= 0:
            return float("nan")
        return float(np.nansum(masked) / (cell * self.resolution**2))

    def _reduce_percent(self, grid: np.ndarray, dem_clip: np.ndarray) -> float:
        masked = self._mask_grid(grid, dem_clip)
        cell = masked.count()
        if cell <= 0:
            return float("nan")
        count = (masked > 0).sum()
        return float((count / cell) * 100)

    def _append_column(
        self,
        frame: pd.DataFrame,
        dataset: dict[Any, np.ndarray] | None,
        column_name: str,
        dem_clip: np.ndarray,
        reducer: Callable[[np.ndarray, np.ndarray], float],
    ) -> None:
        """Append one CSV column from a dictionary of time-indexed grids."""
        if dataset is None:
            return
        try:
            for key, grid in dataset.items():
                frame.loc[key, column_name] = reducer(grid, dem_clip)
        except Exception:
            pass

    def _append_additional_columns(self, frame: pd.DataFrame, dem_clip: np.ndarray) -> None:
        """Hook for subclasses to append non-flow columns."""

    def extract_results(
        self,
        dem_clip: np.ndarray,
        time: Any,
        recharge: Any,
        runoff: Any,
        timeseries_file: str,
    ) -> pd.DataFrame | None:
        """Aggregate loaded grids over one mask and export one CSV file."""
        self.mfdata = pd.DataFrame({"date": time, "recharge": recharge}, index=range(len(time)))
        try:
            self.mfdata["runoff"] = runoff
        except Exception:
            pass

        self._append_column(
            self.mfdata,
            self.watertable_elevation,
            "watertable_elevation",
            dem_clip,
            self._reduce_mean,
        )
        self._append_column(
            self.mfdata,
            self.watertable_depth,
            "watertable_depth",
            dem_clip,
            self._reduce_mean,
        )
        self._append_column(
            self.mfdata,
            self.seepage_areas,
            "seepage_areas",
            dem_clip,
            self._reduce_percent,
        )
        self._append_column(
            self.mfdata,
            self.outflow_drain,
            "outflow_drain",
            dem_clip,
            self._reduce_qspe,
        )
        self._append_column(
            self.mfdata,
            self.groundwater_flux,
            "groundwater_flux",
            dem_clip,
            self._reduce_mean,
        )
        self._append_column(
            self.mfdata,
            self.groundwater_storage,
            "groundwater_storage",
            dem_clip,
            self._reduce_sum,
        )
        self._append_column(
            self.mfdata,
            self.accumulation_flux,
            "accumulation_flux",
            dem_clip,
            self._reduce_max,
        )

        try:
            apply_intermittency_columns(
                self.mfdata,
                accumulation_flux=self.accumulation_flux,
                dem_clip=dem_clip,
                cell_count=self.cell,
                yearly=self.intermittency_yearly,
                monthly=self.intermittency_monthly,
                weekly=self.intermittency_weekly,
                daily=self.intermittency_daily,
            )
        except Exception:
            pass

        self._append_additional_columns(self.mfdata, dem_clip)

        if self.datetime_format:
            try:
                self.mfdata["date"] = pd.to_datetime(time, format="%Y-%m-%d")
            except Exception:
                self.mfdata["date"] = np.arange(0, len(self.mfdata), 1)
        self.mfdata = self.mfdata.set_index(["date"])

        if self.suffix_name is None:
            self.mfdata.to_csv(timeseries_file + "/_simulated_timeseries.csv", sep=";")
        else:
            self.mfdata.to_csv(
                timeseries_file + "/_simulated_timeseries" + "_" + self.suffix_name + ".csv",
                sep=";",
            )

        if timeseries_file == self.timeseries_file:
            return self.mfdata
        return None
