"""Output contracts for all data sources."""

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord

__all__ = ["FieldRecord", "LoadResult", "PointRecord", "StationLocation"]
