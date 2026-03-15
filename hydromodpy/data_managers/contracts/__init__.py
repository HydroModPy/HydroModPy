"""Output contracts for all data sources."""

from hydromodpy.data_managers.contracts.load_result import LoadResult
from hydromodpy.data_managers.contracts.location import StationLocation
from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.data_managers.contracts.spatial_field import FieldRecord

__all__ = ["FieldRecord", "LoadResult", "PointRecord", "StationLocation"]
