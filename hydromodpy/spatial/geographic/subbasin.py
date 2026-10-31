"""
* Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
*
* This program and the accompanying materials are made available under the
* terms of the Eclipse Public License 2.0 which is available at
* http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
* which is available at https://www.apache.org/licenses/LICENSE-2.0.
*
* SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

# %% LIBRAIRIES

# Python
import glob
import os
import shutil
from pathlib import Path

import pandas as pd

# HydroModPy
from hydromodpy.core.exceptions import TerrainProductError
from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.delineation.registry import resolve_delineation_backend
from hydromodpy.spatial.geographic.core.catchment_from_point import extract_catchment_from_point

logger = get_logger(__name__)

# %% CLASS


class Subbasin:
    """
    Class to extract results in some subbasins inside the model domain (watershed).
    """

    def __init__(
        self,
        geographic: object,
        hydrometry: object,
        intermittency: object,
        sub_snap_dist: int,
        add_path: str = None,
        out_path: str | Path | None = None,
    ):
        """
        Parameters
        ----------
        geographic : object
            Variable object of the model domain (watershed).
        hydrometry : object, optional
            Variable object of the model domain (watershed).
        intermittency : object, optional
            Variable object of the model domain (watershed).
        add_path : str, optional
            Path folder with manual data list. Default is None.
        sub_snap_dist : int
            Maximum distance where the subbasin outlet can be moved.
        out_path : str or Path, optional
            Folder of the outputs, used when *geographic* has no preprocessing
            folder. Default is ``output/`` under the working directory, created
            on demand.
        """
        logger.info("Extracting subbasin definitions for watershed")
        self._backend = resolve_delineation_backend()

        self.sub_snap_dist = sub_snap_dist

        stable = getattr(geographic, "stable_folder", None)
        if stable is None:
            from hydromodpy.core.state.paths import preprocessing_dir

            root = Path(out_path) if out_path is not None else Path.cwd() / "output"
            stable = str(preprocessing_dir(root))
        self.subbasin_path = os.path.join(str(stable), "subbasin")
        if not os.path.exists(self.subbasin_path):
            create_folder(self.subbasin_path)

        self.adddata_path = os.path.join(str(stable), "add_data")
        if not os.path.exists(self.adddata_path):
            create_folder(self.adddata_path)

        try:
            code_bh = hydrometry.code_bh
            x_coord = hydrometry.x_coord
            y_coord = hydrometry.y_coord
            for i in range(len(x_coord)):
                station_name = (
                    f"hydrometry_{code_bh[i]}" if code_bh[i] else f"hydrometry_default_{i + 1}"
                )
                if not code_bh[i]:
                    logger.warning("Hydrometry code missing at index %d; using generated name", i)
                sub_path = os.path.join(self.subbasin_path, station_name)
                self.extract_interest_zones(
                    geographic, x_coord[i], y_coord[i], sub_path, sub_snap_dist
                )
        except Exception as e:
            logger.debug("No hydrometry subbasin or problem: %s", e)
            pass

        try:
            if hasattr(intermittency, "points"):
                # New LoadResult-based intermittency
                for rec in intermittency.points:
                    if rec.location is None:
                        continue
                    onde_name = f"intermittency_{rec.station_id}"
                    sub_path = os.path.join(self.subbasin_path, onde_name)
                    self.extract_interest_zones(
                        geographic, rec.location.x, rec.location.y, sub_path, sub_snap_dist
                    )
        except Exception as e:
            logger.debug("No intermittency subbasin or problem: %s", e)
            pass

        try:
            code_sub, x_coord, y_coord = self.add_coord_manual(add_path)
            for i in range(len(code_sub)):
                sub_path = os.path.join(self.subbasin_path, "subbasin_" + code_sub[i])
                self.extract_interest_zones(
                    geographic, x_coord[i], y_coord[i], sub_path, sub_snap_dist
                )
        except Exception as e:
            logger.debug("No personal subbasins or problem: %s", e)
            pass

    # %% SUB-CATCHMENT FROM STATIONS

    # Extract sub-catchment from existing stations : hydrometry or intermittency

    def extract_interest_zones(self, geographic, X, Y, outpath, sub_snap_dist):
        """
        Delineate the sub-basin of one XY outlet through the terrain port.

        The engine is the one the geographic run routed with
        (``geographic.terrain_engine``), on the regional accumulation of that
        run, so a sub-basin and its parent catchment come from one routing.

        Parameters
        ----------
        X : float
            X coordinate of the outlet.
        Y : float
            Y coordinate of the outlet.
        """
        flow_products = getattr(geographic, "_flow_products", None)
        if flow_products is None:
            raise TerrainProductError(
                f"Sub-basin at ({X}, {Y}) in {outpath}: the geographic runtime carries no "
                "regional flow products (_flow_products) to delineate on. Pass the "
                "CatchmentDelineation of the run, which builds them."
            )
        # Path of subbasin
        if os.path.exists(outpath):
            shutil.rmtree(outpath)
        create_folder(outpath)
        products = extract_catchment_from_point(
            x_outlet=float(X),
            y_outlet=float(Y),
            snap_dist=int(sub_snap_dist),
            accumulation=flow_products.accumulation,
            output_dir=outpath,
            crs_project=geographic.crs_proj,
            backend=self._backend,
            engine_id=getattr(geographic, "terrain_engine", None),
        )
        watershed_shp = products.watershed_shp
        self._backend.raster.polygon_area(watershed_shp)
        # Create shapefile polyline of the watershed
        watershed_contour_shp = os.path.join(outpath, "watershed_contour.shp")
        self._backend.delineation.polygons_to_lines(watershed_shp, watershed_contour_shp)
        # Clip buffer watershed DEM from watershed shapefile polygon
        watershed_dem = os.path.join(outpath, "watershed_dem.tif")
        self._backend.raster.clip_raster_to_polygon(
            geographic.watershed_buff_dem,
            watershed_shp,
            watershed_dem,
            maintain_dimensions=True,
        )

    # %% SUB-CATCHMENT FROM XY POINT

    # From a .csv file with x, y coordinates representing the outlet desired sub-catchments

    def add_coord_manual(self, add_path):
        """
        Check files in folder and extract 'code_sub','x_outlet','y_outlet'
        """
        path_coord = glob.glob(str(Path(add_path) / "*"))[0]
        logger.debug("Loading coordinates from: %s", path_coord)
        sub_list = pd.read_csv(path_coord, sep=";")
        code_sub = sub_list["code_sub"].to_list()
        x_coord = sub_list["x_outlet"].to_list()
        y_coord = sub_list["y_outlet"].to_list()
        return code_sub, x_coord, y_coord


# %% NOTES
