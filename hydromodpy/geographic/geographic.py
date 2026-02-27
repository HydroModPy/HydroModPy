# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

from __future__ import annotations

import os
import ssl
import sys
from os.path import abspath, dirname

import certifi
import geopandas as gpd
import geopy.geocoders
import numpy as np
import pandas as pd
import rasterio
import whitebox
from geopy.geocoders import Nominatim
from pyproj import Transformer

from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.geographic.geographic_io import (
    ensure_crs as _ensure_crs_impl,
    write_shapefile_without_duplicate_columns,
)
from hydromodpy.geographic.geographic_paths import GeographicPaths, build_geographic_paths
from hydromodpy.tools import get_logger, toolbox

wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Keep backward-compatible path bootstrap behavior.
root_dir = dirname(dirname(abspath(__file__)))
sys.path.append(root_dir)

fontprop = toolbox.plot_params(8, 15, 18, 20)  # small, medium, interm, large
logger = get_logger(__name__)


def DEM_correcflow_analysis(
    dem_init_path: str,
    dem_out_dir_path: str,
    dem_correc_type: str,
) -> dict:
    """
    Build the 3 core regional rasters needed by watershed delineation.

    Workflow (in order)
    -------------------
    1. Hydrologically correct the input DEM:
       - ``fill``   : fill topographic depressions,
       - ``breach`` : carve channels through depressions.
    2. Compute D8 flow-direction on the corrected DEM.
    3. Compute D8 flow-accumulation on the corrected DEM.

    Parameters
    ----------
    dem_init_path : str
        Path to the regional DEM used as hydrologic input.
    dem_out_dir_path : str
        Folder where regional rasters are written.
    dem_correc_type : str
        Type of DEM correction to apply:
        - ``"fill"``
        - ``"breach"``
        Any other value raises a ``ValueError``.

    Returns
    -------
    dict
        Dictionary with output raster paths:
        ``{"correc": ..., "direc": ..., "acc": ...}``.
    """
    # Normalize to plain strings because WhiteboxTools expects str paths.
    dem_init_path = str(dem_init_path)
    dem_out_dir_path = str(dem_out_dir_path)

    # Step 1 - DEM hydrologic correction.
    # The corrected DEM is the common support for all downstream rasters.
    if dem_correc_type == "fill":
        correc = os.path.join(dem_out_dir_path, "dem_fill.tif")
        wbt.fill_depressions(dem_init_path, correc)
    elif dem_correc_type == "breach":
        correc = os.path.join(dem_out_dir_path, "dem_breach.tif")
        wbt.breach_depressions(dem_init_path, correc)
    else:
        raise ValueError(f"Unknown dem_correc_type={dem_correc_type!r}. Expected 'fill' or 'breach'.")

    # Step 2 - D8 flow-direction raster from the corrected DEM.
    # ``esri_pntr=False`` keeps Whitebox default pointer convention.
    direc = os.path.join(dem_out_dir_path, "dem_direc.tif")
    wbt.d8_pointer(correc, direc, esri_pntr=False)

    # Step 3 - D8 flow-accumulation raster from the corrected DEM.
    # ``log=True`` reduces dynamic range and is consistent with legacy behavior.
    acc = os.path.join(dem_out_dir_path, "dem_acc.tif")
    wbt.d8_flow_accumulation(correc, acc, log=True)

    return {
        "correc": correc,
        "direc": direc,
        "acc": acc,
    }


def _ensure_crs(path, crs):
    """
    Ensures that a spatial file (raster or shapefile) has the specified CRS.

    Parameters
    ----------
    path : str
        Path to the raster (.tif) or shapefile (.shp) to update.
    crs : str or None
        The target Coordinate Reference System (e.g., 'EPSG:2154'). If None,
        no operation is performed.
    """
    _ensure_crs_impl(path, crs)


class Geographic:
    """
    Initializes the model domain (watershed) by performing geospatial operations.

    Public contract is intentionally unchanged:
    - constructor signature remains ``Geographic(config, initializing)``,
    - main outputs are stored in the same public attributes,
    - generated filenames remain identical.
    """

    def __init__(self, config: GeographicConfig, initializing):
        logger.info("Extracting geographic data for model area")

        self.out_dir_path = initializing.catch_folder
        self.catch_def = config.catch_def
        self.dem_init_path = str(config.dem_init_path)
        self.x_outlet = config.x_outlet
        self.y_outlet = config.y_outlet
        self.snap_dist = config.snap_dist
        self.buff_area = config.buff_area
        self.polyg_shp_path = str(config.polyg_shp_path) if config.polyg_shp_path is not None else None
        self.dem_correc_type = config.dem_correc_type
        self._crs_project = config.crs_project

        self.processing()
        self.info_dem()

    def build_georeferencing(self) -> dict[str, object]:
        """
        Return the georeferencing metadata needed by `Domain`.

        The returned mapping is intentionally narrow: only the attributes that
        describe the spatial support are exposed, so callers can pass a small,
        explicit payload instead of the whole `Geographic` object.

        Returned keys
        -------------
        - `crs`
        - `dx`
        - `dy`
        - `xmin`
        - `xmax`
        - `ymin`
        - `ymax`

        `dx` and `dy` are exported separately so the raster support can
        represent non-square cells without silently assuming one single
        resolution value.
        """
        mapping = {
            "crs": "crs_proj",
            "dx": "dx",
            "dy": "dy",
            "xmin": "xmin",
            "xmax": "xmax",
            "ymin": "ymin",
            "ymax": "ymax",
        }
        out: dict[str, object] = {}
        for key, attr_name in mapping.items():
            if hasattr(self, attr_name):
                out[key] = getattr(self, attr_name)
        return out

    def get_domain_surface_topo(self):
        """
        Return the domain topographic surface as one fully prepared `Surface`.

        This helper keeps the extraction of topography-driven domain objects
        close to the `Geographic` object that produces the underlying data,
        while still passing only explicit objects to `Domain`.
        """
        from hydromodpy.domain.raster_support import RasterSupport
        from hydromodpy.domain.surface import Surface

        top_values = np.asarray(self.dem_box_buff_data, dtype=float)
        support = RasterSupport.from_georeferencing(
            self.build_georeferencing(),
            shape=top_values.shape,
            nodata=getattr(self, "nodata", None),
        )
        surface_topo = Surface.from_geographic_dem(
            top_values,
            support=support,
        )
        return surface_topo

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------
    def processing(self):
        """
        Prepare and generate physical files defining the model domain.

        This method keeps the historical behavior and output names, but now
        orchestrates the workflow via explicit internal steps.
        """
        self._initialize_output_paths()
        self._prepare_output_folders()
        self._resolve_crs_from_input_dem()

        flow_products = self._prepare_regional_flow_products()
        self._build_watershed_geometry(
            direc_path=flow_products["direc"],
            acc_path=flow_products["acc"],
        )
        self._build_watershed_derivatives()
        buffer_path = self._build_buffer_and_box_products()
        self._clip_domain_products(
            correc_path=flow_products["correc"],
            direc_path=flow_products["direc"],
            buffer_path=buffer_path,
        )
        self._align_raster_shapes_if_needed()

    # ------------------------------------------------------------------
    # Step 1: paths + folders + CRS
    # ------------------------------------------------------------------
    def _initialize_output_paths(self) -> None:
        self._paths: GeographicPaths = build_geographic_paths(self.out_dir_path)

        # Expose historical public attributes.
        self.stable_folder = self._paths.stable_folder
        self.simulations_folder = self._paths.simulations_folder
        self.geographic_path = self._paths.geographic_path
        self.correcflow_path = self._paths.correcflow_path
        self.watershed = self._paths.watershed
        self.watershed_shp = self._paths.watershed_shp
        self.watershed_contour_shp = self._paths.watershed_contour_shp
        self.watershed_box_shp = self._paths.watershed_box_shp
        self.box_buff = self._paths.box_buff
        self.watershed_box_buff_dem = self._paths.watershed_box_buff_dem
        self.watershed_box_buff_fill = self._paths.watershed_box_buff_fill
        self.watershed_box_buff_direc = self._paths.watershed_box_buff_direc
        self.watershed_buff_dem = self._paths.watershed_buff_dem
        self.watershed_buff_fill = self._paths.watershed_buff_fill
        self.watershed_buff_direc = self._paths.watershed_buff_direc
        self.watershed_dem = self._paths.watershed_dem
        self.watershed_fill = self._paths.watershed_fill
        self.watershed_direc = self._paths.watershed_direc
        self.watershed_contour_tif = self._paths.watershed_contour_tif

    def _prepare_output_folders(self) -> None:
        toolbox.create_folder(self.geographic_path)
        toolbox.create_folder(self.correcflow_path)

    def _resolve_crs_from_input_dem(self) -> None:
        with rasterio.open(self.dem_init_path) as dem_src:
            epsg = dem_src.crs.to_epsg() if dem_src.crs is not None else None
        self.epsg = epsg
        self.crs_proj = f"EPSG:{epsg}" if epsg is not None else None
        if self._crs_project is not None:
            self.crs_proj = self._crs_project

    # ------------------------------------------------------------------
    # Step 2: core products
    # ------------------------------------------------------------------
    def _prepare_regional_flow_products(self) -> dict:
        products = DEM_correcflow_analysis(
            dem_init_path=self.dem_init_path,
            dem_out_dir_path=self.correcflow_path,
            dem_correc_type=self.dem_correc_type,
        )
        _ensure_crs(products["correc"], self.crs_proj)
        _ensure_crs(products["direc"], self.crs_proj)
        _ensure_crs(products["acc"], self.crs_proj)
        return products

    def _build_watershed_geometry(self, *, direc_path: str, acc_path: str) -> None:
        if self.catch_def == "from_outlet_coord":
            self._build_watershed_from_outlet(direc_path=direc_path, acc_path=acc_path)
            return
        if self.catch_def == "from_polyg_shp":
            if self.polyg_shp_path is None:
                raise ValueError("catch_def='from_polyg_shp' requires polyg_shp_path")
            write_shapefile_without_duplicate_columns(self.polyg_shp_path, self.watershed_shp)
            _ensure_crs(self.watershed_shp, self.crs_proj)

    def _build_watershed_from_outlet(self, *, direc_path: str, acc_path: str) -> None:
        outlet_shp = os.path.join(self.geographic_path, "outlet.shp")
        outlet_snap_shp = os.path.join(self.geographic_path, "outlet_snap.shp")

        df = pd.DataFrame({"x": [self.x_outlet], "y": [self.y_outlet]})
        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["x"], df["y"]), crs=self.crs_proj)
        gdf.to_file(outlet_shp)
        _ensure_crs(outlet_shp, self.crs_proj)

        wbt.snap_pour_points(outlet_shp, acc_path, outlet_snap_shp, self.snap_dist)
        _ensure_crs(outlet_snap_shp, self.crs_proj)

        wbt.watershed(direc_path, outlet_snap_shp, self.watershed, esri_pntr=False)
        _ensure_crs(self.watershed, self.crs_proj)

        wbt.raster_to_vector_polygons(self.watershed, self.watershed_shp)
        _ensure_crs(self.watershed_shp, self.crs_proj)

    def _build_watershed_derivatives(self) -> None:
        wbt.polygons_to_lines(self.watershed_shp, self.watershed_contour_shp)

        try:
            area = gpd.read_file(self.watershed_shp).AREA.iloc[0] / 1_000_000
            self.catch_area = float(np.abs(area))
        except Exception:
            area = gpd.read_file(self.watershed_shp).area.iloc[0] / 1_000_000
            self.catch_area = float(np.abs(area))

    # ------------------------------------------------------------------
    # Step 3: buffering + clipping
    # ------------------------------------------------------------------
    def _compute_buffer_distance(self) -> float:
        with rasterio.open(self.dem_init_path) as dem_src:
            self.dem_res = abs(dem_src.transform.a)

        if isinstance(self.buff_area, str) is not True:
            buff_raw = (np.sqrt(float(self.catch_area))) * (float(self.buff_area) / 100) * 1000
            buff_raw = int(round(buff_raw))
            dist = np.linspace(0, buff_raw, buff_raw + 1) * self.dem_res
            return float(dist[np.abs(dist - buff_raw).argmin()])
        return float(self.buff_area)

    def _build_buffer_and_box_products(self) -> str:
        buff_dist = self._compute_buffer_distance()

        # Buffer around watershed polygon.
        write_shapefile_without_duplicate_columns(self.watershed_shp, self.watershed_shp)
        site_polyg = gpd.read_file(self.watershed_shp)
        site_polyg["geometry"] = site_polyg.geometry.buffer(buff_dist)
        buffer_path = os.path.join(self.geographic_path, "watershed_buff.shp")
        site_polyg.to_file(buffer_path)
        _ensure_crs(buffer_path, self.crs_proj)

        # Bounding envelope + buffered box.
        wbt.minimum_bounding_envelope(self.watershed_shp, self.watershed_box_shp, features=False)
        write_shapefile_without_duplicate_columns(self.watershed_box_shp, self.watershed_box_shp)
        _ensure_crs(self.watershed_box_shp, self.crs_proj)

        site_bound = gpd.read_file(self.watershed_box_shp)
        site_bound["geometry"] = site_bound.geometry.buffer(buff_dist)
        site_bound.to_file(self.box_buff)
        wbt.minimum_bounding_envelope(self.box_buff, self.box_buff, features=False)
        write_shapefile_without_duplicate_columns(self.box_buff, self.box_buff)
        _ensure_crs(self.box_buff, self.crs_proj)
        return buffer_path

    def _ensure(self, path: str) -> None:
        """Apply current project CRS on one output file."""
        _ensure_crs(path, self.crs_proj)

    def _set_nodata(self, path: str, value: float) -> None:
        """Set nodata value on one raster output."""
        wbt.modify_no_data_value(path, new_value=value)

    def _clip_raster(
        self,
        src: str,
        polygon: str,
        dst: str,
        maintain_dimensions: bool,
        nodata: float | None = None,
    ) -> None:
        """Clip one raster to polygon, then enforce CRS and optional nodata."""
        wbt.clip_raster_to_polygon(
            src,
            polygon,
            dst,
            maintain_dimensions=maintain_dimensions,
        )
        self._ensure(dst)
        if nodata is not None:
            self._set_nodata(dst, nodata)

    def _clip_domain_products(self, *, correc_path: str, direc_path: str, buffer_path: str) -> None:
        # Table-driven clipping pipeline:
        # each tuple = (src_raster, clip_polygon, dst_raster, keep_input_grid, nodata_override).
        # This centralizes the repetitive "clip + ensure_crs + optional nodata" pattern.
        jobs = [
            # 1) Box-buffer extent: model support window used for all downstream products.
            (self.dem_init_path, self.box_buff, self.watershed_box_buff_dem, False, -9999.0),
            (correc_path, self.box_buff, self.watershed_box_buff_fill, False, None),
            (direc_path, self.box_buff, self.watershed_box_buff_direc, False, None),
            # 2) Buffered watershed extent: same support but clipped with maintain_dimensions for DEM.
            (self.watershed_box_buff_dem, buffer_path, self.watershed_buff_dem, True, -9999),
            (correc_path, buffer_path, self.watershed_buff_fill, False, None),
            (direc_path, buffer_path, self.watershed_buff_direc, False, None),
            # 3) Exact watershed footprint: solver-ready catchment rasters.
            (self.watershed_box_buff_dem, self.watershed_shp, self.watershed_dem, True, None),
            (correc_path, self.watershed_shp, self.watershed_fill, False, None),
            (direc_path, self.watershed_shp, self.watershed_direc, False, None),
        ]
        for src, poly, dst, maintain, nodata in jobs:
            self._clip_raster(
                src,
                poly,
                dst,
                maintain_dimensions=maintain,
                nodata=nodata,
            )

        # Catchment contour raster.
        wbt.vector_lines_to_raster(
            self.watershed_shp,
            self.watershed_contour_tif,
            base=self.watershed_dem,
        )
        self._ensure(self.watershed_contour_tif)

    def _align_raster_shapes_if_needed(self) -> None:
        with (
            rasterio.open(self.watershed_box_buff_dem) as src1,
            rasterio.open(self.watershed_buff_dem) as src2,
            rasterio.open(self.watershed_dem) as src3,
        ):
            # Keep historical condition as-is for strict behavioral compatibility.
            if src1.read(1).shape != src2.read(1).shape != src3.read(1).shape:
                logger.debug("Reshaping rasters to match box buff watershed dimensions")
                self._export_reshaped_rasters()

    def _export_reshaped_rasters(self) -> None:
        """Export all rasters on the box-buff grid using a compact table-driven loop."""
        # tuple = (source_raster, destination_raster, nodata_value)
        jobs = [
            # solver footprint rasters
            (self.watershed_box_buff_dem, self.watershed_dem, -9999),
            (self.watershed_box_buff_fill, self.watershed_fill, -9999),
            (self.watershed_box_buff_direc, self.watershed_direc, -32768),
            # buffered footprint rasters
            (self.watershed_box_buff_dem, self.watershed_buff_dem, -9999),
            (self.watershed_box_buff_fill, self.watershed_buff_fill, -9999),
            (self.watershed_box_buff_direc, self.watershed_buff_direc, -32768),
            # canonical box-buff rasters
            (self.watershed_box_buff_dem, self.watershed_box_buff_dem, -9999),
            (self.watershed_box_buff_fill, self.watershed_box_buff_fill, -9999),
            (self.watershed_box_buff_direc, self.watershed_box_buff_direc, -32768),
        ]
        for src_path, dst_path, nodata in jobs:
            with rasterio.open(src_path) as src:
                data = src.read(1)
            toolbox.export_tif(self.watershed_box_buff_dem, data, dst_path, nodata)

    # ------------------------------------------------------------------
    # DEM features (public behavior unchanged)
    # ------------------------------------------------------------------
    def info_dem(self):
        """
        Extract metadata and spatial characteristics from generated DEM rasters.
        """
        with rasterio.open(self.watershed_box_buff_dem) as box_buff_dem_src:
            self.dem_box_buff_data = box_buff_dem_src.read(1)
        with rasterio.open(self.watershed_buff_dem) as buff_dem_src:
            self.dem_buff_data = buff_dem_src.read(1)
        with rasterio.open(self.watershed_dem) as dem_src:
            self.dem_data = dem_src.read(1)
            self.nodata = dem_src.nodata
            self.geodata = dem_src.transform.to_gdal()

        self.x_pixel = self.dem_box_buff_data.shape[1]  # columns
        self.y_pixel = self.dem_box_buff_data.shape[0]  # rows

        self.resolution_x = self.geodata[1]  # pixelWidth: positive
        self.resolution_y = self.geodata[5]  # pixelHeight: negative
        self.dx = abs(self.resolution_x)
        self.dy = abs(self.resolution_y)
        self.resolution = self.resolution_x

        self.xmin = self.geodata[0]  # originX
        self.ymax = self.geodata[3]  # originY
        self.xmax = self.xmin + self.x_pixel * self.resolution_x
        self.ymin = self.ymax + self.y_pixel * self.resolution_y

        self.x_coord = (
            np.linspace(1, self.x_pixel, self.x_pixel) * self.resolution_x + self.xmin
        )
        self.y_coord = self.ymax - (
            np.linspace(1, self.y_pixel, self.y_pixel) * self.resolution_x
        )

        self.centroid = [
            self.xmin + ((self.xmax - self.xmin) / 2),
            self.ymin + ((self.ymax - self.ymin) / 2),
        ]

        try:
            transformer = Transformer.from_crs(self.crs_proj, "epsg:4326")
            self.centroid_long_lat = transformer.transform(self.centroid[0], self.centroid[1])
            self.ur_long_lat = transformer.transform(self.xmax, self.ymax)
            self.ul_long_lat = transformer.transform(self.xmin, self.ymax)
            self.lr_long_lat = transformer.transform(self.xmax, self.ymin)
            self.ll_long_lat = transformer.transform(self.xmin, self.ymin)
            self.centroid_long_lat_Greenwich = [
                self.centroid_long_lat[0],
                self.centroid_long_lat[1],
            ]
            if self.centroid_long_lat_Greenwich[1] < 0:
                self.centroid_long_lat_Greenwich[1] += 360
        except Exception:
            pass

        try:
            locator = Nominatim(user_agent="google")
            location = locator.reverse(
                f"{self.centroid_long_lat_Greenwich[0]},{self.centroid_long_lat_Greenwich[1]}",
                timeout=120,
            )
            try:
                self.dep_code = int(location.address.split(",")[-2][0:3])
            except Exception:
                pass
        except OSError:
            ctx = ssl.create_default_context(cafile=certifi.where())
            geopy.geocoders.options.default_ssl_context = ctx
            locator = Nominatim(user_agent="google")
            location = locator.reverse(
                f"{self.centroid_long_lat_Greenwich[0]},{self.centroid_long_lat_Greenwich[1]}",
                timeout=120,
            )
            self.dep_code = int(location.address.split(",")[-2][0:3])
        else:
            pass
