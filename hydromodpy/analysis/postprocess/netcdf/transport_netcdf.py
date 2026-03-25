# -*- coding: utf-8 -*-
"""Transport-oriented NetCDF post-processing exports."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio as rio
from rasterio.features import rasterize

from hydromodpy.analysis.postprocess.netcdf.flow_netcdf import FlowNetcdfPostprocess
from hydromodpy.core.tools import get_logger

logger = get_logger(__name__)


class TransportNetcdfPostprocess(FlowNetcdfPostprocess):
    """Convert flow+transport postprocess outputs to NetCDF files."""

    def __init__(
        self,
        geographic: object,
        model_modflow: object,
        *,
        model_modpath: object | None = None,
        model_mt3dms: object | None = None,
        datetime_format: bool = True,
        concentration_seepage: bool = True,
        mass_accumulated: bool = True,
        residence_times: bool = True,
    ) -> None:
        self.model_modpath = model_modpath
        self.model_mt3dms = model_mt3dms
        self.concentration_seepage = concentration_seepage
        self.mass_accumulated = mass_accumulated
        self.residence_times = residence_times
        super().__init__(
            geographic=geographic,
            model_modflow=model_modflow,
            datetime_format=datetime_format,
        )

    def _candidate_particle_shapefiles(self) -> Iterable[str]:
        """Return candidate particle shapefile paths for residence-time export."""
        if self.model_modpath is not None and hasattr(self.model_modpath, "track_dir"):
            type_dir = "ending" if self.model_modpath.track_dir == "forward" else "starting"
            basenames = (f"{type_dir}_weighted.shp", f"{type_dir}.shp")
        else:
            basenames = (
                "ending_weighted.shp",
                "ending.shp",
                "starting_weighted.shp",
                "starting.shp",
            )

        folders = ("_particles", "_particules")
        for folder in folders:
            for name in basenames:
                yield os.path.join(self.save_file, folder, name)

    def _load_residence_raster(self) -> dict[int, np.ndarray] | None:
        """Rasterize particle residence times to a single grid."""
        shapefile_path = next(
            (path for path in self._candidate_particle_shapefiles() if os.path.exists(path)),
            None,
        )
        if shapefile_path is None:
            return None

        try:
            particles = gpd.read_file(shapefile_path)
        except Exception:
            return None

        if particles.empty or "geometry" not in particles:
            return None

        value_column = "time_win" if "time_win" in particles else "time" if "time" in particles else None
        if value_column is None:
            return None

        with rio.open(self.base_raster_path, "r") as base:
            shape = (base.height, base.width)
            transform = base.transform
            nodata = base.nodata

        values = particles[value_column]
        geometries = particles.geometry
        shapes = (
            (geom, float(val))
            for geom, val in zip(geometries, values)
            if geom is not None and val is not None and not (isinstance(val, float) and np.isnan(val))
        )

        fill_value = float("nan") if nodata is None else nodata
        raster = rasterize(
            shapes=shapes,
            out_shape=shape,
            transform=transform,
            fill=fill_value,
            dtype="float32",
            all_touched=True,
        )
        return {0: raster}

    def _export_additional_outputs(self, *, times: Any) -> None:
        """Export transport-only outputs when enabled and available."""
        if self.concentration_seepage and self.model_mt3dms is not None:
            self._export_named_output(name="concentration_seepage", times=times)

        if self.mass_accumulated and self.model_mt3dms is not None:
            self._export_named_output(name="mass_accumulated", times=times)

        if self.residence_times:
            data = self._load_residence_raster()
            if data is None:
                return
            try:
                self.export_netcdf(
                    data,
                    base_path=self.base_raster_path,
                    out_path=os.path.join(self.netcdf_file, "residence_times.nc"),
                    base_crs=self.geographic.crs_proj,
                    times=[0],
                )
            except Exception:
                pass


__all__ = [
    "TransportNetcdfPostprocess",
]
