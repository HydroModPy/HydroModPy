"""Lake-bathymetry manager: lake-bed elevation rasters from the user's files."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_file import RasterFileManager


class LakeBathymetryManager(RasterFileManager):
    VARIABLE_NAME = "lake_bathymetry"
