Data Sources
============

HydroModPy data loading is configured through ``[data]`` and
``[[data.<family>.sources]]`` TOML sections. Each family accepts one or more
sources. Managers normalize the loaded records into internal field, point, or
timeseries contracts before workflows consume them.

Provider matrix
---------------

.. list-table::
   :header-rows: 1
   :widths: 18 25 22 35

   * - Family
     - Sources
     - Typical payload
     - Notes
   * - ``dem``
     - ``custom``, ``ign_bdalti``
     - Raster elevation
     - Used by geographic preprocessing and catchment extraction.
   * - ``geology``
     - ``custom``, ``brgm_1m``, ``brgm_50k``
     - Vector or raster geology zones
     - Custom vector sources require a geology-code column.
   * - ``hydrography``
     - ``custom``, ``osm``, ``bdtopage``, ``euhydro``
     - Stream-network geometries
     - API sources are clipped by a resolved bounding box and cached.
   * - ``hydrometry``
     - ``custom``, ``hubeau``
     - Streamflow stations and chronicles
     - Used by data overviews, calibration, validation, and reports.
   * - ``piezometry``
     - ``custom``, ``hubeau``
     - Head observation wells and chronicles
     - Can constrain calibration and result diagnostics.
   * - ``intermittency``
     - ``custom``, ``hubeau``
     - Flow-state observations
     - Useful for stream-network calibration and validation.
   * - ``water_quality``
     - ``custom``, ``hubeau``
     - Chemistry samples and chronicles
     - Supports transport and diagnostic workflows.
   * - ``oceanic``
     - ``custom``, ``shom``, ``constant``
     - Sea-level or coastal boundary timeseries
     - ``constant`` is useful for controlled coastal tests.
   * - ``recharge``
     - ``custom``, ``sim2``, ``synthetic``
     - Gridded or point recharge
     - ``synthetic`` creates controlled forcing series for tests.
   * - ``precipitation``
     - ``custom``, ``sim2``
     - Gridded or point climate forcing
     - Components include liquid, solid, or total precipitation.
   * - ``etp``
     - ``custom``, ``sim2``
     - Potential evapotranspiration
     - Shares the standard gridded/time-series source contract.
   * - ``temperature``
     - ``custom``, ``sim2``
     - Air temperature
     - Used by hydrological preprocessing and diagnostics.
   * - ``wind``
     - ``custom``, ``sim2``
     - Wind forcing
     - Uses the common climate manager pattern.
   * - ``humidity``
     - ``custom``, ``sim2``
     - Humidity forcing
     - Uses the common climate manager pattern.
   * - ``radiation``
     - ``custom``, ``sim2``
     - Atmospheric or visible radiation
     - Components are selected in the source block.
   * - ``soil_moisture``
     - ``custom``, ``sim2``
     - Soil-moisture fields or timeseries
     - Used by data overviews and forcing checks.
   * - ``runoff``
     - ``custom``, ``sim2``
     - Runoff fields or chronicles
     - Uses the common hydrometeorological source contract.

Common source fields
--------------------

Most source blocks share the same ideas even when exact fields differ:

- ``source`` selects the provider.
- ``path`` points to user data for ``custom`` sources.
- ``mask_path`` or ``extent`` constrains API downloads.
- ``force_refresh`` bypasses cached API artifacts when available.
- ``source_unit`` documents or overrides units for custom gridded inputs.
- ``stations`` or equivalent id lists restrict point/time-series sources.
- ``date_start`` and ``date_end`` may be inferred from the project period, but
  explicit dates make external downloads easier to audit.

Minimal TOML patterns
---------------------

Most projects start by declaring the active data families, then one or more
source blocks for each family:

.. code-block:: toml

   [data]
   project_crs = "EPSG:2154"
   types = ["dem", "geology", "hydrography", "hydrometry", "piezometry", "recharge"]

   [[data.dem.sources]]
   source = "ign_bdalti"
   extent = "watershed"

   [[data.geology.sources]]
   source = "brgm_1m"
   extent = "watershed"

   [[data.hydrography.sources]]
   source = "bdtopage"
   extent = "watershed"

   [[data.hydrometry.sources]]
   source = "hubeau"
   extent = "watershed"

   [[data.piezometry.sources]]
   source = "hubeau"
   extent = "watershed"

   [[data.recharge.sources]]
   source = "sim2"
   extent = "watershed"

Use ``custom`` when the project should read local files instead of external
services:

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

   [[data.recharge.sources]]
   source = "custom"
   path = "data/recharge/recharge.nc"
   source_unit = "mm/day"

Controlled synthetic or constant sources are useful for tests and teaching:

.. code-block:: toml

   [data]
   types = ["recharge", "oceanic"]

   [[data.recharge.sources]]
   source = "synthetic"
   values = [0.8, 1.2, 0.6]

   [[data.oceanic.sources]]
   source = "constant"
   value = 0.0

Provider choice
---------------

.. list-table::
   :header-rows: 1
   :widths: 26 37 37

   * - Goal
     - Prefer
     - Why
   * - First watershed overview in France
     - ``ign_bdalti``, ``brgm_1m``, ``bdtopage``, Hub'Eau, ``sim2``
     - Minimizes local files and exercises the standard public-data path.
   * - Reproducible teaching case
     - ``custom``, ``synthetic``, ``constant``
     - Avoids external API availability and makes expected values explicit.
   * - Local production project
     - ``custom`` for validated in-house datasets, API sources as fallback
     - Keeps institutionally curated inputs authoritative.
   * - CI or offline validation
     - ``custom`` plus ``hmp run --frozen``
     - Fails early if an input is missing instead of downloading silently.

Cache and reproducibility
-------------------------

API-backed sources persist reusable artifacts in the workspace data cache.
Lockfile commands then record the identity of downloaded or imported data:

.. code-block:: bash

   hmp data
   hmp lock
   hmp run project.toml --frozen

Use ``--frozen`` when a workflow must fail instead of downloading fresh data.
This is the right mode for CI, teaching material, and reproducibility checks.
Use ``force_refresh = true`` only when you intentionally want to bypass cached
API artifacts and refresh provider data.

Where data appears in workflows
-------------------------------

Overview workflows use data managers to build identity cards before any solver
run. Simulation workflows use them during setup and persistence. Calibration,
comparison, and batch workflows reuse the same normalized records through the
workspace catalog and run stores.

For API details, see :doc:`../api/hydromodpy-data`.
