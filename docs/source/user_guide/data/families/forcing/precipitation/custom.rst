Precipitation Source: custom
============================

Use ``source = "custom"`` for local precipitation rasters, NetCDF files, or
station-derived series.

.. code-block:: toml

   [[data.precipitation.sources]]
   source = "custom"
   path = "data/precipitation/precipitation.nc"
   components = ["total"]
   source_unit = "mm/day"

Check component naming, units, period coverage, and spatial support before the
data are used in hydrological preprocessing.
