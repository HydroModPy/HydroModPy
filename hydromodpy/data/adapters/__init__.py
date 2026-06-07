"""User-facing format adapters for the custom data scaffold.

The drag-and-drop flow accepts heterogeneous user formats (CSV, SHP,
GeoJSON, GPKG, ASC, GeoTIFF, NetCDF). Adapters normalise them into the
internal pivot formats (Parquet, GeoParquet, COG GeoTIFF) without the
user ever having to see or name them.
"""

from hydromodpy.data.adapters.asc_to_geotiff import convert_asc_to_geotiff
from hydromodpy.data.adapters.csv_to_parquet import (
    TimeSeriesValidationError,
    convert_locations_csv_to_geoparquet,
    convert_timeseries_csv_to_parquet,
    infer_station_id_from_filename,
    read_locations_csv,
)
from hydromodpy.data.adapters.shp_to_geoparquet import convert_vector_to_geoparquet

__all__ = (
    "TimeSeriesValidationError",
    "convert_asc_to_geotiff",
    "convert_locations_csv_to_geoparquet",
    "convert_timeseries_csv_to_parquet",
    "convert_vector_to_geoparquet",
    "infer_station_id_from_filename",
    "read_locations_csv",
)
