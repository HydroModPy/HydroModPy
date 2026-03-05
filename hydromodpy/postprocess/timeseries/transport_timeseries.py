# -*- coding: utf-8 -*-
"""Transport-oriented time-series post-processing utilities.

This module extends flow time-series export with transport indicators:
- concentration at seepage zones,
- accumulated mass,
- optional residence time estimated from Modpath particles.

Illustration
------------
If ``concentration_seepage=True`` and ``mass_accumulated=True``, the exported
CSV includes both columns in addition to standard flow columns.
"""

from __future__ import annotations

import os
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from hydromodpy.postprocess.timeseries.flow_timeseries import FlowTimeseriesPostprocess


class TransportTimeseriesPostprocess(FlowTimeseriesPostprocess):
    """Export flow+transport postprocess outputs as time-series CSV files.

    The class inherits full flow extraction behavior and appends transport
    columns only when corresponding flags/data are available.
    """

    def __init__(
        self,
        geographic: object,
        model_modflow: object,
        runoff: Any = None,
        model_modpath: object | None = None,
        model_mt3dms: object | None = None,
        suffix_name: str | None = None,
        datetime_format: bool = True,
        subbasin_results: bool = True,
        intermittency_yearly: bool = False,
        intermittency_monthly: bool = False,
        intermittency_weekly: bool = False,
        intermittency_daily: bool = False,
        residence_times: bool = False,
        concentration_seepage: bool = False,
        mass_accumulated: bool = False,
    ) -> None:
        """Build and export transport-enriched time series.

        Parameters
        ----------
        model_modpath:
            Optional Modpath model used to compute residence-time indicators.
        model_mt3dms:
            Optional concentration transport model (MT3DMS or MF6 GWT output
            shape compatible with the same ``.npy`` contract).
        residence_times:
            If ``True``, append one representative residence-time metric.
        concentration_seepage:
            If ``True``, append ``concentration_seepage`` column.
        mass_accumulated:
            If ``True``, append ``mass_accumulated`` column.

        Example
        -------
        ``TransportTimeseriesPostprocess(..., concentration_seepage=True)``
        reads ``concentration_seepage.npy`` and exports one reduced value per
        time step.
        """
        self.model_modpath = model_modpath
        self.model_mt3dms = model_mt3dms
        self.residence_times = residence_times
        self.concentration_seepage_enabled = concentration_seepage
        self.mass_accumulated_enabled = mass_accumulated

        self.shp_particles: gpd.GeoDataFrame | None = None
        self.concentration_seepage_data: dict[Any, np.ndarray] | None = None
        self.mass_accumulated_data: dict[Any, np.ndarray] | None = None

        super().__init__(
            geographic=geographic,
            model_modflow=model_modflow,
            runoff=runoff,
            suffix_name=suffix_name,
            datetime_format=datetime_format,
            subbasin_results=subbasin_results,
            intermittency_yearly=intermittency_yearly,
            intermittency_monthly=intermittency_monthly,
            intermittency_weekly=intermittency_weekly,
            intermittency_daily=intermittency_daily,
        )

    def _load_additional_products(self) -> None:
        """Load transport products and optional particle shapefiles.

        Particle shapefile lookup is backward-compatible:
        1. ``<type_dir>_weighted.shp``
        2. ``<type_dir>.shp``
        where ``type_dir`` is ``ending`` for forward tracking and ``starting``
        for backward tracking.
        """
        if self.model_modpath is not None:
            type_dir = "ending" if self.model_modpath.track_dir == "forward" else "starting"
            try:
                self.shp_particles = gpd.read_file(
                    os.path.join(self.save_file, "_particles", type_dir + "_weighted" + ".shp")
                )
            except Exception:
                try:
                    self.shp_particles = gpd.read_file(
                        os.path.join(self.save_file, "_particles", type_dir + ".shp")
                    )
                except Exception:
                    self.shp_particles = None

        if self.model_mt3dms is not None:
            self.concentration_seepage_data = self._try_load_npy("concentration_seepage")
            self.mass_accumulated_data = self._try_load_npy("mass_accumulated")

    def _append_additional_columns(self, frame: pd.DataFrame, dem_clip: np.ndarray) -> None:
        """Append transport concentration/mass columns and optional residence time.

        Residence-time strategy
        -----------------------
        A single representative value is written at key ``0``:
        - prefer ``time_win`` when available,
        - otherwise fallback to ``time``.
        """
        if self.concentration_seepage_enabled:
            self._append_column(
                frame,
                self.concentration_seepage_data,
                "concentration_seepage",
                dem_clip,
                self._reduce_mean,
            )

        if self.mass_accumulated_enabled:
            self._append_column(
                frame,
                self.mass_accumulated_data,
                "mass_accumulated",
                dem_clip,
                self._reduce_max,
            )

        if self.residence_times:
            try:
                key = 0
                particles = self.shp_particles
                if particles is None:
                    return

                try:
                    # Keep residence-time indicator consistent with watershed
                    # reporting domain even if particle files include extras.
                    shp_frame = gpd.read_file(self.geographic.watershed_shp)
                    particles = particles.clip(shp_frame)
                except Exception:
                    pass

                try:
                    calc = np.nanmean(particles["time_win"])
                except Exception:
                    calc = np.nanmean(particles["time"])
                frame.loc[key, "residence_times"] = calc
            except Exception:
                pass
