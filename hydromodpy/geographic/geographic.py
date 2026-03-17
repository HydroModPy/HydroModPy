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

from geopy.geocoders import Nominatim

from hydromodpy.backends import WhiteboxBackend, get_whitebox_backend
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.legacy.geographic.dem_metadata import read_legacy_dem_metadata
from hydromodpy.legacy.geographic.pipeline import build_legacy_geographic_context
from hydromodpy.geographic.core.domain_geographic_pipeline import DomainGeographicContext
from hydromodpy.geographic.core.flow_products import build_regional_flow_products
from hydromodpy.geographic.core.surface_from_dem import build_surface_topo_from_dem
from hydromodpy.support.tools import get_logger

logger = get_logger(__name__)


def DEM_correcflow_analysis(
    dem_init_path: str,
    dem_out_dir_path: str,
    dem_correc_type: str,
    backend: WhiteboxBackend | None = None,
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
    tool = get_whitebox_backend() if backend is None else backend
    products = build_regional_flow_products(
        dem_init_path=dem_init_path,
        dem_out_dir_path=dem_out_dir_path,
        dem_correc_type=dem_correc_type,
        backend=tool,
    )
    return {
        "correc": products.correc,
        "direc": products.direc,
        "acc": products.acc,
    }


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

        self._config = config
        self.out_dir_path = initializing.catch_folder
        self.catch_def = config.catch_def
        self.dem_init_path = str(config.dem_init_path)
        self.x_outlet = config.x_outlet
        self.y_outlet = config.y_outlet
        self.snap_dist = config.snap_dist
        self.buff_area = config.buff_area
        self.polyg_shp_path = str(config.polyg_shp_path) if config.polyg_shp_path is not None else None
        self.dem_correc_type = config.dem_correc_type

        self.processing()

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
        if not hasattr(self, "_dem_metadata"):
            self.info_dem()
        return self._dem_metadata.as_georeferencing()

    def get_domain_surface_topo(self):
        """
        Return the domain topographic surface as one fully prepared `Surface`.

        This helper keeps the extraction of topography-driven domain objects
        close to the `Geographic` object that produces the underlying data,
        while still passing only explicit objects to `Domain`.
        """
        return build_surface_topo_from_dem(self.watershed_box_buff_dem)

    def get_domain_geographic_context(self) -> DomainGeographicContext:
        """
        Return the narrow geographic payload consumed by `Domain`.

        This keeps the compatibility facade available for legacy runtime users
        while allowing newer orchestration code to depend on an explicit,
        smaller contract.
        """
        box_buff_shp = getattr(self, "box_buff_shp", None)
        if box_buff_shp is None:
            box_buff_shp = getattr(self, "box_buff", None)
        if box_buff_shp is None:
            raise ValueError("Missing box-buffer shapefile path on Geographic runtime object.")

        return DomainGeographicContext(
            surface_topo=self.get_domain_surface_topo(),
            watershed_shp=str(self.watershed_shp),
            catchment_area_km2=float(self.catch_area),
            catch_def=str(self.catch_def),
            x_outlet=float(self.x_outlet) if self.x_outlet is not None else None,
            y_outlet=float(self.y_outlet) if self.y_outlet is not None else None,
            watershed_box_buff_dem=str(self.watershed_box_buff_dem),
            watershed_box_shp=str(getattr(self, "watershed_box_shp", "")) or None,
            box_buff_shp=str(box_buff_shp),
            zone_kind=(
                "uniform"
                if str(self.catch_def).strip().lower() == "dem"
                else "catchment"
            ),
        )

    def processing(self):
        """Build and hydrate the full legacy geographic runtime payload."""
        tool = get_whitebox_backend()
        context = build_legacy_geographic_context(
            config=self._config,
            out_dir_path=self.out_dir_path,
            backend=tool,
            locator_factory=Nominatim,
        )
        for attr_name, value in context.legacy_attributes().items():
            setattr(self, attr_name, value)

    # ------------------------------------------------------------------
    # DEM features (public behavior unchanged)
    # ------------------------------------------------------------------
    def info_dem(self):
        """
        Extract metadata and spatial characteristics from generated DEM rasters.
        """
        if hasattr(self, "_dem_metadata"):
            for attr_name, value in self._dem_metadata.legacy_attributes().items():
                setattr(self, attr_name, value)
            return

        self._dem_metadata = read_legacy_dem_metadata(
            watershed_box_buff_dem_path=self.watershed_box_buff_dem,
            watershed_buff_dem_path=self.watershed_buff_dem,
            watershed_dem_path=self.watershed_dem,
            crs_project=self.crs_proj,
            locator_factory=Nominatim,
        )
        for attr_name, value in self._dem_metadata.legacy_attributes().items():
            setattr(self, attr_name, value)

