Provider Matrix
===============

This page lists the public and local source values accepted by the data
configuration models. The details are derived from the ``*SourceConfig`` classes
under ``hydromodpy.data.variables``.

Family inventory
----------------

.. list-table::
   :header-rows: 1
   :widths: 18 24 24 34

   * - Family
     - Accepted ``source`` values
     - Payload shape
     - Main selectors
   * - ``dem``
     - ``custom``, ``ign_bdalti``
     - Elevation raster
     - ``path``, ``mask_path``, ``extent``
   * - ``geology``
     - ``custom``, ``brgm_1m``, ``brgm_50k``
     - Geology zones as vector or raster data
     - ``path``, ``code_field``, ``values_table_path``, ``mask_path``, ``extent``
   * - ``hydrography``
     - ``custom``, ``osm``, ``bdtopage``, ``euhydro``
     - River-network geometries
     - ``path``, provider paging fields, ``waterway_types``
   * - ``hydrometry``
     - ``custom``, ``hubeau``
     - Discharge stations and chronicles
     - ``station_ids``, ``mask_path``, ``extent``, ``product``
   * - ``piezometry``
     - ``custom``, ``hubeau``
     - Groundwater-level wells and chronicles
     - ``station_ids``, ``mask_path``, ``extent``, ``product``, ``nearest``
   * - ``intermittency``
     - ``custom``, ``hubeau``
     - ONDE flow-state observations
     - ``station_ids``, ``code_departement``, ``mask_path``, ``extent``
   * - ``water_quality``
     - ``custom``, ``hubeau``
     - River or piezometer chemistry observations
     - ``site_type``, ``parameters``, ``station_ids``, ``mask_path``, ``extent``
   * - ``oceanic``
     - ``custom``, ``shom``, ``constant``
     - Sea-level or coastal boundary time series
     - ``path``, ``value``, ``station_ids``, ``mask_path``, ``extent``, ``nearest``
   * - ``recharge``
     - ``custom``, ``sim2``, ``synthetic``
     - Gridded or point recharge forcing
     - ``path``, ``values``, ``mask_path``, ``extent``, synthetic waveform fields
   * - ``precipitation``
     - ``custom``, ``sim2``
     - Gridded or point precipitation forcing
     - ``components``, ``path``, ``mask_path``, ``extent``
   * - ``etp``
     - ``custom``, ``sim2``
     - Potential evapotranspiration forcing
     - ``path``, ``mask_path``, ``extent``
   * - ``temperature``
     - ``custom``, ``sim2``
     - Air-temperature forcing
     - ``path``, ``mask_path``, ``extent``
   * - ``wind``
     - ``custom``, ``sim2``
     - Wind forcing
     - ``path``, ``mask_path``, ``extent``
   * - ``humidity``
     - ``custom``, ``sim2``
     - Relative-humidity forcing
     - ``path``, ``mask_path``, ``extent``
   * - ``radiation``
     - ``custom``, ``sim2``
     - Atmospheric and visible radiation
     - ``components``, ``path``, ``mask_path``, ``extent``
   * - ``soil_moisture``
     - ``custom``, ``sim2``
     - Soil-moisture fields or time series
     - ``path``, ``mask_path``, ``extent``
   * - ``runoff``
     - ``custom``, ``sim2``
     - Surface-runoff forcing
     - ``path``, ``mask_path``, ``extent``

Provider families
-----------------

.. list-table::
   :header-rows: 1
   :widths: 22 30 48

   * - Provider group
     - Source values
     - Typical role
   * - Public geographic layers
     - ``ign_bdalti``, ``brgm_1m``, ``brgm_50k``, ``bdtopage``, ``euhydro``,
       ``osm``
     - Build watershed context: DEM, geology, and stream-network support.
   * - Hub'Eau observations
     - ``hubeau``
     - Discover and download streamflow, piezometry, ONDE intermittency, and
       water-quality observations.
   * - SIM2 forcing
     - ``sim2``
     - Retrieve gridded meteorological and hydrological forcing over a project
       period and spatial window.
   * - Coastal boundary data
     - ``shom``, ``constant``
     - Retrieve observed sea-level data or declare a controlled fixed sea level.
   * - Local and controlled data
     - ``custom``, ``synthetic``
     - Use project-owned files or deterministic forcing for reproducible tests
       and teaching cases.

Common fields
-------------

.. list-table::
   :header-rows: 1
   :widths: 25 25 50

   * - Field
     - Applies to
     - Meaning
   * - ``source``
     - Every source block
     - Selects the provider implementation.
   * - ``path``
     - ``custom`` sources
     - Points to a local directory or file. Relative paths are resolved from the
       TOML file, with workspace data fallbacks for bare filenames.
   * - ``mask_path``
     - Most spatial and observation families
     - Uses a local mask to clip grids or filter stations.
   * - ``extent``
     - DEM, geology, Hub'Eau families, SIM2 families, oceanic
     - Uses project ``watershed`` or ``study_area`` extent when available.
   * - ``station_ids``
     - Point/time-series families
     - Restricts loading to known station identifiers.
   * - ``source_unit``
     - Custom grids and point series that expose units
     - Overrides or documents the input unit before conversion to HydroModPy's
       internal unit.
   * - ``force_refresh``
     - API-backed and cached sources
     - Bypasses compatible cache hits for that source.
   * - ``fallback_search_radius_km``
     - Hub'Eau and SHOM-style discovery
     - Expands a station search if the initial spatial filter finds no usable
       observations.
   * - ``require_observations``
     - Observation discovery
     - Keeps only stations with observations over the requested period when
       ``true``.

Specialized fields
------------------

- ``geology.code_field`` is required for custom vector geology sources.
- ``geology.values_table_path`` can attach tabular property values to geology
  codes.
- ``hydrometry.product`` is required for Hub'Eau hydrometry sources; ``QmnJ``
  is the usual daily-discharge code.
- ``precipitation.components`` accepts ``liquid``, ``solid``, and ``total``.
- ``radiation.components`` accepts ``atmospheric`` and ``visible``.
- ``piezometry.product`` accepts ``level`` or ``depth``.
- ``water_quality.site_type`` accepts ``river`` or ``piezometer``.
- ``water_quality.parameters`` restricts downloaded chemistry parameters.
- ``oceanic.value`` is used by ``source = "constant"``.
- ``recharge.values``, ``start_date``, ``freq``, ``periods``, ``amplitude``,
  ``period_days``, ``offset``, and ``runoff_ratio`` belong to synthetic
  recharge forcing.

API reference
-------------

For the complete generated configuration list, use
:doc:`../../api/hydromodpy-config`. The generated pages are useful when you
need every default value, while this page is the user-facing selection guide.
