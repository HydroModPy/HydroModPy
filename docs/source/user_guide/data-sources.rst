Data Sources
============

This page is a compact compatibility entry point for older links. The complete
data documentation now lives in :doc:`data/index`.

HydroModPy data loading is configured through ``[data]`` and
``[[data.<family>.sources]]`` TOML sections. Managers can load public API
providers, local custom files, synthetic forcing, and constants, then normalize
the result into internal field, point, or timeseries contracts.

Quick provider matrix
---------------------

.. list-table::
   :header-rows: 1
   :widths: 18 28 26 28

   * - Family
     - Sources
     - Typical payload
     - Deep reference
   * - ``dem``
     - ``custom``, ``ign_bdalti``
     - Raster elevation
     - :doc:`data/provider-matrix`
   * - ``geology``
     - ``custom``, ``brgm_1m``, ``brgm_50k``
     - Geology zones
     - :doc:`data/provider-matrix`
   * - ``hydrography``
     - ``custom``, ``osm``, ``bdtopage``, ``euhydro``
     - Stream-network geometries
     - :doc:`data/provider-matrix`
   * - ``hydrometry``, ``piezometry``, ``intermittency``, ``water_quality``
     - ``custom`` and Hub'Eau-backed sources
     - Observation stations and chronicles
     - :doc:`data/provider-matrix`
   * - ``recharge``, ``runoff``, ``precipitation``, ``etp``, ``temperature``,
       ``wind``, ``humidity``, ``radiation``, ``soil_moisture``
     - ``custom`` and SIM2-backed sources, plus ``synthetic`` recharge
     - Gridded or point forcing
     - :doc:`data/provider-matrix`
   * - ``oceanic``
     - ``custom``, ``shom``, ``constant``
     - Coastal boundary time series or fixed sea level
     - :doc:`data/provider-matrix`

Minimal public-data pattern
---------------------------

.. code-block:: toml

   [data]
   project_crs = "EPSG:2154"
   inference_mode = "strict"
   types = ["dem", "geology", "hydrography", "hydrometry", "recharge"]

   [[data.dem.sources]]
   source = "ign_bdalti"
   extent = "watershed"

   [[data.geology.sources]]
   source = "brgm_1m"
   extent = "watershed"

   [[data.hydrography.sources]]
   source = "bdtopage"

   [data.hydrometry]
   date_start = "2020-01-01"
   date_end = "2020-12-31"

   [[data.hydrometry.sources]]
   source = "hubeau"
   product = "QmnJ"
   extent = "watershed"

   [data.recharge]
   date_start = "2020-01-01"
   date_end = "2020-12-31"

   [[data.recharge.sources]]
   source = "sim2"
   extent = "watershed"

``hydrography`` is intentionally shown without ``extent`` here: its source
config does not expose that field. The runtime passes the project geographic
context to the hydrography manager.

Minimal custom pattern
----------------------

.. code-block:: toml

   [data]
   project_crs = "EPSG:2154"
   types = ["dem", "geology", "hydrography", "recharge"]

   [[data.dem.sources]]
   source = "custom"
   path = "data/dem/catchment_dem.tif"

   [[data.geology.sources]]
   source = "custom"
   path = "data/geology/geology.gpkg"
   code_field = "CODE_LEG"

   [[data.hydrography.sources]]
   source = "custom"
   path = "data/hydrography/rivers.gpkg"

   [data.recharge]
   date_start = "2000-01-01"
   date_end = "2002-12-31"

   [[data.recharge.sources]]
   source = "custom"
   path = "data/recharge/recharge.nc"
   source_unit = "mm/day"

Where to continue
-----------------

- :doc:`data/retrieval-workflow` explains the end-to-end retrieval lifecycle.
- :doc:`data/provider-matrix` lists supported families, providers, and fields.
- :doc:`data/custom-data` documents local files and CSV conventions.
- :doc:`data/cache-and-lockfiles` explains cache inspection, locking, frozen
  runs, and data archives.
- :doc:`../api/index` exposes the generated Python API reference.
