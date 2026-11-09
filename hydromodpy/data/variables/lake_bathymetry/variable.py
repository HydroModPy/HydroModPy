"""Lake-bathymetry variable: lake-bed elevation rasters from the user's files."""

from __future__ import annotations

from hydromodpy.data.families.files import RasterFileVariable


class LakeBathymetryVariable(RasterFileVariable):
    VARIABLE_NAME = "lake_bathymetry"
