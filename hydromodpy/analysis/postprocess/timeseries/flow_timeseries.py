# -*- coding: utf-8 -*-
"""Flow-oriented time-series post-processing utilities.

This module converts flow postprocess products (``.npy`` dictionaries keyed by
stress period) into tabular watershed/subbasin time series.

Typical output files
--------------------
- ``_postprocess/_timeseries/_simulated_timeseries.csv`` (catchment scale)
- ``_subbasins/<zone_name>/_simulated_timeseries.csv`` (optional)

Illustration
------------
Given a flow output dictionary like::

    seepage_areas = {
        0: array([[...], [...]]),
        1: array([[...], [...]]),
    }

the exporter writes one row per key (time step), and each grid is reduced to
one scalar with a reducer (mean, sum, percentage, etc.) over the watershed mask.
"""

from __future__ import annotations

import os
import warnings
from typing import Any, Callable

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from hydromodpy.analysis.postprocess.flow.intermittency import apply_intermittency_columns
from hydromodpy.core.tools import get_logger
from hydromodpy.core.tools.filesystem import create_folder

logger = get_logger(__name__)
# Silence pandas masked-to-nan spam when handling masked arrays
warnings.filterwarnings("ignore", message=".*converting a masked element to nan.*")


class FlowTimeseriesPostprocess:
    """Export flow postprocess outputs as watershed/subbasin time-series CSV files.

    Design notes
    ------------
    - Inputs are optional. Missing ``.npy`` payloads are skipped silently.
    - Aggregations are mask-based:
      structured grids reduce rasters over ``dem_clip`` while unstructured
      grids reduce flat per-cell arrays over a cell-domain mask.
    - The class is base-oriented: transport exporters subclass it and append
      extra columns (for example concentration or residence time).
    """

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
        *,
        store: Any = None,
        sim_id: str | None = None,
    ) -> None:
        """Build and immediately export flow time series.

        Parameters
        ----------
        geographic:
            Geographic runtime object containing watershed rasters and folders.
        model_modflow:
            Executed flow model object (MODFLOW-NWT or MODFLOW 6 wrapper).
        runoff:
            Optional runoff forcing. Accepted forms mirror recharge:
            scalar, ``pandas.Series``, or ``dict[time, 2D-array]``.
        suffix_name:
            Optional CSV suffix. Example: ``suffix_name="s1"`` writes
            ``_simulated_timeseries_s1.csv``.
        datetime_format:
            If ``True``, convert ``time`` to ``DatetimeIndex`` when possible.
        subbasin_results:
            If ``True``, repeat extraction for each available subbasin mask.
        store:
            ResultStore instance for reading spatial fields.
        sim_id:
            Simulation UUID in the store.

        Example
        -------
        ``FlowTimeseriesPostprocess(geo, flow_model, runoff=runoff_series)``
        exports one catchment CSV plus optional subbasin CSV files.
        """
        self.suffix_name = suffix_name

        self.geographic = geographic
        self.model_modflow = model_modflow
        self.stable_folder = geographic.stable_folder
        self.simulations = geographic.simulations_folder

        self.model_name = model_modflow.model_name
        self.model_folder = model_modflow.model_folder
        self.resolution = model_modflow.resolution
        self.cell_area = float(
            getattr(model_modflow, "cell_area", float(model_modflow.resolution) ** 2)
        )
        self.base_raster_path = getattr(
            model_modflow,
            "dem_watershed_path",
            geographic.watershed_dem,
        )
        self.solver_mesh = getattr(model_modflow, "solver_mesh", None)
        self.is_unstructured = bool(
            self.solver_mesh is not None
            and not getattr(self.solver_mesh, "is_structured", True)
        )
        self.cell_centroids = None
        self.cell_weights = None
        if self.is_unstructured:
            try:
                self.cell_centroids = np.asarray(
                    self.solver_mesh.cell_centroids(),
                    dtype=float,
                ).reshape(-1, 2)
            except Exception:
                self.cell_centroids = None
            try:
                self.cell_weights = np.asarray(
                    self.solver_mesh.cell_areas(),
                    dtype=float,
                ).reshape(-1)
                if self.cell_weights.size > 0:
                    self.cell_area = float(np.nanmean(self.cell_weights))
            except Exception:
                self.cell_weights = None
        self.recharge = model_modflow.recharge
        self.runoff = runoff
        self._store = store
        self._sim_id = sim_id

        self.intermittency_yearly = intermittency_yearly
        self.intermittency_monthly = intermittency_monthly
        self.intermittency_weekly = intermittency_weekly
        self.intermittency_daily = intermittency_daily
        self.datetime_format = datetime_format

        self.full_path = os.path.join(self.model_folder, self.model_name)
        self.tifs_file = os.path.join(self.full_path, "_postprocess", "_rasters")

        self.save_file = os.path.join(self.full_path, "_postprocess")
        if not os.path.exists(self.save_file):
            create_folder(self.save_file)

        self.timeseries_file = os.path.join(self.save_file, "_timeseries")
        if not os.path.exists(self.timeseries_file):
            create_folder(self.timeseries_file)

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

        if self.is_unstructured:
            self.nodata = float(getattr(self.geographic, "nodata", -9999.0))
            dem_clip = self._build_default_cell_domain()
        else:
            with rasterio.open(self.base_raster_path) as src:
                dem_clip = src.read(1)
                self.nodata = float(
                    src.nodata
                    if src.nodata is not None
                    else getattr(self.geographic, "nodata", -9999.0)
                )
        # ``self.cell`` is used by intermittency postprocess helpers that need
        # normalized indicators (% flowing cells, etc.).
        self.cell = self._count_active_cells(dem_clip)
        self.extract_results(dem_clip, time, recharge, runoff_series, self.timeseries_file)
        logger.info("Exported catchment time series to %s", self.timeseries_file)

        if subbasin_results:
            self._export_subbasins(time, recharge, runoff_series)

    def _normalize_forcing_series(self) -> tuple[Any, Any, Any]:
        """Normalize recharge/runoff to a common time axis.

        Supported recharge/runoff forms
        -------------------------------
        - scalar: one-step synthetic series
        - ``pandas.Series``: explicit timestamped series
        - ``dict``: one 2D grid per stress period, reduced to mean per period

        Illustration
        ------------
        ``{0: grid0, 1: grid1}`` -> ``time=range(2)``, ``values=[mean(grid0), mean(grid1)]``.
        """
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

        try:
            runoff = recharge * np.nan
        except TypeError:
            runoff = np.nan
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

    def _load_field_from_store(self, name: str) -> dict[Any, np.ndarray] | None:
        """Load a spatial field from the ResultStore as a timestep dict."""
        if self._store is None or self._sim_id is None:
            return None
        from hydromodpy.analysis.display.common import load_field_dict_from_store

        return load_field_dict_from_store(self._store, self._sim_id, name)

    def _load_flow_products(self) -> None:
        """Load flow-derived fields from the ResultStore."""
        self.watertable_elevation = self._load_field_from_store("watertable_elevation")
        self.watertable_depth = self._load_field_from_store("watertable_depth")
        self.seepage_areas = self._load_field_from_store("seepage_areas")
        self.outflow_drain = self._load_field_from_store("outflow_drain")
        self.groundwater_flux = self._load_field_from_store("groundwater_flux")
        self.groundwater_storage = self._load_field_from_store("groundwater_storage")
        self.accumulation_flux = self._load_field_from_store("accumulation_flux")

    def _load_additional_products(self) -> None:
        """Hook for subclasses to load non-flow products."""

    def _export_subbasins(self, time: Any, recharge: Any, runoff: Any) -> None:
        """Export one CSV per available subbasin mask."""
        try:
            zones_folder = os.path.join(
                getattr(self.geographic, "out_dir_path", ""), "subbasin",
            )
            for zi, zone_name in enumerate(os.listdir(zones_folder)):
                sub_file = os.path.join(self.full_path, "_subbasins", zone_name)
                if not os.path.exists(sub_file):
                    create_folder(sub_file)
                try:
                    dem_clip = self._load_mask_raster(
                        os.path.join(zones_folder, zone_name, "watershed_dem.tif")
                    )
                    self.cell = self._count_active_cells(dem_clip)
                    self.extract_results(dem_clip, time, recharge, runoff, sub_file)
                    logger.info(
                        "Exported time series for subbasin %s to %s", zi + 1, sub_file
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _active_mask(self, dem_clip: np.ndarray) -> np.ndarray:
        """Return the boolean mask of valid cells for one reporting domain."""

        data = np.asarray(dem_clip, dtype=float)
        mask = np.isfinite(data)
        if np.isfinite(self.nodata):
            mask &= ~np.isclose(data, self.nodata)
        return mask

    def _count_active_cells(self, dem_clip: np.ndarray) -> int:
        """Count valid cells on the current reporting mask."""

        return int(np.count_nonzero(self._active_mask(dem_clip)))

    def _build_default_cell_domain(self) -> np.ndarray:
        """Return the default reporting mask for one cell-based mesh."""

        if self.cell_weights is None or self.cell_weights.size == 0:
            return np.asarray([], dtype=float)

        n_cells = int(self.cell_weights.size)
        mask = np.asarray(
            getattr(self.model_modflow, "dem_mask", np.zeros(n_cells, dtype=bool)),
            dtype=bool,
        ).reshape(-1)
        if mask.size != n_cells:
            mask = np.zeros(n_cells, dtype=bool)

        values = np.asarray(
            getattr(self.model_modflow, "dem", np.ones(n_cells, dtype=float)),
            dtype=float,
        ).reshape(-1)
        if values.size != n_cells:
            values = np.ones(n_cells, dtype=float)

        domain = values.copy()
        domain[mask] = float(self.nodata)
        return domain

    def _sample_cell_mask_from_raster(self, raster_path: str) -> np.ndarray:
        """Sample one raster support at cell centroids for unstructured meshes."""

        if self.cell_centroids is None or self.cell_centroids.size == 0:
            raise ValueError("Cell centroids are required to sample unstructured masks.")

        with rasterio.open(raster_path) as src:
            coords = [tuple(point) for point in self.cell_centroids.tolist()]
            sampled = np.asarray(
                [
                    float(value[0]) if len(value) > 0 else np.nan
                    for value in src.sample(coords)
                ],
                dtype=float,
            )
            src_nodata = float(src.nodata) if src.nodata is not None else float(self.nodata)
            if np.isfinite(src_nodata):
                sampled[np.isclose(sampled, src_nodata)] = float(self.nodata)
        return sampled

    def _load_mask_raster(self, raster_path: str) -> np.ndarray:
        """Load one reporting mask and align it to the solver base raster.

        Subbasin masks are stored in the stable geographic tree and can keep the
        native geographic DEM resolution. They must be reprojected onto the
        solver raster before aggregating solver-grid outputs.
        """
        if self.is_unstructured:
            return self._sample_cell_mask_from_raster(raster_path)

        with rasterio.open(self.base_raster_path) as base_src:
            dst_profile = base_src.profile.copy()
            dst_nodata = float(
                base_src.nodata if base_src.nodata is not None else self.nodata
            )
            destination = np.full(
                (base_src.height, base_src.width),
                dst_nodata,
                dtype=float,
            )

        with rasterio.open(raster_path) as src:
            source = src.read(1).astype(float)
            same_shape = (src.height, src.width) == (
                dst_profile["height"],
                dst_profile["width"],
            )
            same_transform = src.transform == dst_profile["transform"]
            same_crs = src.crs == dst_profile["crs"] or src.crs is None or dst_profile["crs"] is None
            if same_shape and same_transform and same_crs:
                return source

            reproject(
                source=source,
                destination=destination,
                src_transform=src.transform,
                src_crs=src.crs or dst_profile["crs"],
                src_nodata=src.nodata if src.nodata is not None else self.nodata,
                dst_transform=dst_profile["transform"],
                dst_crs=dst_profile["crs"] or src.crs,
                dst_nodata=dst_nodata,
                resampling=Resampling.nearest,
            )
        return destination

    @staticmethod
    def _coerce_grid_to_domain(grid: np.ndarray, dem_clip: np.ndarray) -> np.ndarray:
        """Coerce one input grid to the reporting-domain shape when possible."""

        data = np.asarray(grid, dtype=float)
        target = np.asarray(dem_clip)
        if data.shape == target.shape:
            return data
        if data.size == target.size:
            return data.reshape(target.shape)
        raise ValueError(
            f"Grid shape {data.shape} is incompatible with reporting domain {target.shape}."
        )

    def _mask_grid(self, grid: np.ndarray, dem_clip: np.ndarray) -> np.ma.MaskedArray:
        """Apply DEM-based masking to one input grid."""
        return np.ma.masked_array(
            self._coerce_grid_to_domain(grid, dem_clip),
            mask=~self._active_mask(dem_clip),
        )

    def _domain_cell_weights(self, dem_clip: np.ndarray) -> np.ndarray | None:
        """Return area weights for the active reporting domain when applicable."""

        if not self.is_unstructured or self.cell_weights is None:
            return None
        weights = np.asarray(self.cell_weights, dtype=float)
        target = np.asarray(dem_clip)
        if weights.shape != target.shape:
            if weights.size != target.size:
                return None
            weights = weights.reshape(target.shape)
        return np.where(self._active_mask(dem_clip), weights, np.nan)

    @staticmethod
    def _weighted_nanmean(values: np.ndarray, weights: np.ndarray) -> float:
        """Return the area-weighted mean ignoring NaN values."""

        valid = np.isfinite(values) & np.isfinite(weights)
        if not np.any(valid):
            return float("nan")
        total_weight = float(np.nansum(weights[valid]))
        if total_weight <= 0:
            return float("nan")
        return float(np.nansum(values[valid] * weights[valid]) / total_weight)

    def _reduce_max(self, grid: np.ndarray, dem_clip: np.ndarray) -> float:
        masked = self._mask_grid(grid, dem_clip)
        return float(np.nanmax(masked))

    def _reduce_mean(self, grid: np.ndarray, dem_clip: np.ndarray) -> float:
        masked = self._mask_grid(grid, dem_clip).copy()
        masked[masked < 0] = 0  # Keep legacy behavior
        masked[masked < -1] = np.nan  # Keep legacy behavior
        weights = self._domain_cell_weights(dem_clip)
        if weights is not None:
            return self._weighted_nanmean(
                np.asarray(masked.filled(np.nan), dtype=float),
                weights,
            )
        return float(np.nanmean(masked))

    def _reduce_sum(self, grid: np.ndarray, dem_clip: np.ndarray) -> float:
        masked = self._mask_grid(grid, dem_clip)
        return float(np.nansum(masked))

    def _reduce_qspe(self, grid: np.ndarray, dem_clip: np.ndarray) -> float:
        masked = self._mask_grid(grid, dem_clip)
        weights = self._domain_cell_weights(dem_clip)
        if weights is not None:
            valid = np.isfinite(weights)
            total_area = float(np.nansum(weights[valid]))
            if total_area <= 0:
                return float("nan")
            return float(np.nansum(np.asarray(masked.filled(np.nan), dtype=float)) / total_area)
        cell = masked.count()
        if cell <= 0:
            return float("nan")
        return float(np.nansum(masked) / (cell * self.cell_area))

    def _reduce_percent(self, grid: np.ndarray, dem_clip: np.ndarray) -> float:
        masked = self._mask_grid(grid, dem_clip)
        weights = self._domain_cell_weights(dem_clip)
        if weights is not None:
            values = np.asarray(masked.filled(np.nan), dtype=float)
            total_area = float(np.nansum(weights[np.isfinite(weights)]))
            if total_area <= 0:
                return float("nan")
            active_area = float(
                np.nansum(
                    np.where(
                        (values > 0) & np.isfinite(weights),
                        weights,
                        0.0,
                    )
                )
            )
            return float((active_area / total_area) * 100.0)
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
        """Append one CSV column from a dictionary of time-indexed grids.

        Example
        -------
        For ``column_name="watertable_depth"``, each grid from
        ``dataset[stress_period]`` is reduced and written in
        ``frame.loc[stress_period, "watertable_depth"]``.
        """
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
        """Aggregate loaded grids over one mask and export one CSV file.

        Workflow
        --------
        1. Initialize base frame with ``date`` and forcings.
        2. Append scalar columns reduced from flow grids.
        3. Optionally append intermittency and subclass columns.
        4. Normalize index and write CSV.
        """
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
                cell_weights=self._domain_cell_weights(dem_clip),
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
                # Fallback keeps deterministic integer chronology when incoming
                # time labels are not parseable as datetimes.
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
