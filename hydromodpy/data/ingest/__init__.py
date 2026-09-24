"""How a user file enters: storage formats for ``hmp data add``, Python objects for a run.

The drag-and-drop flow accepts heterogeneous user formats (CSV, SHP,
GeoJSON, GPKG, ASC, GeoTIFF, NetCDF). ``raster``, ``vector`` and ``tables``
normalise them into the internal pivot formats (Parquet, GeoParquet, COG
GeoTIFF) without the user ever having to see or name them;
``custom_points`` and ``custom_grids`` read a folder of them into records.
"""

from hydromodpy.data.ingest.raster import convert_asc_to_geotiff
from hydromodpy.data.ingest.tables import (
    TimeSeriesValidationError,
    convert_abacus_to_parquet,
    convert_locations_csv_to_geoparquet,
    convert_timeseries_csv_to_parquet,
    infer_station_id_from_filename,
    read_locations_csv,
)
from hydromodpy.data.ingest.vector import convert_vector_to_geoparquet

__all__ = (
    "TimeSeriesValidationError",
    "convert_abacus_to_parquet",
    "convert_asc_to_geotiff",
    "convert_locations_csv_to_geoparquet",
    "convert_timeseries_csv_to_parquet",
    "convert_vector_to_geoparquet",
    "infer_station_id_from_filename",
    "read_locations_csv",
)
