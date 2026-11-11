"""How a user file is read: pivot formats for the readers, Python objects for a run.

A source ``file`` accepts heterogeneous user formats (CSV, SHP, GeoJSON, GPKG,
ASC, GeoTIFF, NetCDF). ``raster``, ``vector`` and ``tables`` normalize some of
them into the internal pivot formats (Parquet, GeoParquet, COG GeoTIFF) when a
reader needs one; ``custom_points`` and ``custom_grids`` read a folder of them
into records.
"""
