Data Loading And Retrieval
==========================

HydroModPy treats data acquisition as a first-class workflow layer. A project
does not only point to files: it can discover public observations, download
gridded forcing, ingest local archives, normalize everything into common
contracts, cache reusable artifacts, and lock the cache for reproducible runs.

This chapter is the operational entry point for that layer. It sits in the user
guide because most choices here are project choices: which families to load,
which providers to trust, which time window to use, and how strict the run must
be about cached inputs.

Reading map
-----------

.. list-table::
   :header-rows: 1
   :widths: 28 38 34

   * - Goal
     - Read
     - Main decision
   * - Retrieve public data for one basin
     - :doc:`retrieval-workflow`
     - Pick ``data.types``, source blocks, extent, dates, and cache policy.
   * - See every supported family and provider
     - `Provider matrix`_ below
     - Decide between public APIs, local files, synthetic forcing, and constants.
   * - Read one page per data family
     - See `Data families`_ below
     - Inspect the operational contract, examples, checks, and source-specific
       sections for each data type.
   * - Connect pages with generated figures
     - :doc:`runs-and-figures`
     - Use the lightest run that explains the data: local file checks,
       provider grids, overview maps, or solver response.
   * - Inspect provider-specific replay cases
     - :doc:`provider-replay-cases`
     - Read SHOM, Hub'Eau, SIM2, and hydrography examples from committed
       provider artifacts before planning live refreshes.
   * - Use institutionally curated local datasets
     - :doc:`custom-data`
     - Match local rasters, vectors, or station time series to HydroModPy's
       custom-source conventions.
   * - Make the same run reproducible later
     - :doc:`cache-and-lockfiles`
     - Inspect the cache, update the lockfile, verify hashes, and archive data.
   * - Inspect the generated configuration surface
     - :doc:`../config_reference/data`
     - Read the typed ``[data]`` section reference with fields, defaults,
       and validators.

Conceptual model
----------------

The data layer has four responsibilities:

1. Declare the active data families in ``[data].types``.
2. Resolve each family to one or more ``[[data.<family>.sources]]`` blocks.
3. Normalize loaded records into field, point, or timeseries contracts.
4. Persist API-backed artifacts in the workspace cache when a workspace exists.

The same records then feed overview figures, geographic preprocessing, mesh and
solver setup, calibration objectives, comparison workflows, and reports. That
is why data retrieval deserves its own user-facing chapter instead of being
hidden in solver examples.

Where this fits
---------------

- First-run tutorials use :doc:`../../getting_started/data-overview-walkthrough`
  to show one complete no-solver data workflow.
- This chapter explains how to adapt that workflow to other basins and data
  policies.
- :doc:`../../architecture/data_loading/index` documents the internal planner
  and runtime handoff for contributors.

Illustrated reference
---------------------

The pages in this chapter use the Nancon data-overview case as the practical
reference. It is a no-solver workflow: the figures below are data and support
diagnostics, not simulation results. For the complete case page, open
:doc:`../../capability_gallery/cases/geographic_nancon_identity_card`.

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_dem.png
   :alt: Nancon DEM and watershed support
   :width: 100%

   Data retrieval first has to produce a credible basin support: DEM, watershed
   boundary, outlet context, and common CRS.

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_station_inventory.png
   :alt: Nancon station inventory from data overview
   :width: 100%

   The same retrieval workflow also exposes which observation stations are
   available before any model run is launched.

Provider matrix
---------------

This section lists the public and local source values accepted by the data
configuration models. The details are derived from the ``*SourceConfig``
classes under ``hydromodpy.data.variables``. For operational details,
examples, and source-specific checks, use the per-family pages below.

Visual source matrix
~~~~~~~~~~~~~~~~~~~~

Read the matrix from left to right: source values are useful only after
the payload shape, first diagnostic, and downstream use are clear.

.. figure:: /_static/user_guide/data/data_family_source_matrix.png
   :alt: Matrix of HydroModPy data families and supported source groups
   :width: 100%

   The colored cells group sources by role: local files, public geographic
   providers, Hub'Eau observations, SIM2 forcing, SHOM coastal data, and
   controlled sources such as synthetic or constant values.

Family inventory
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 18 24 24 34

   * - Family
     - Accepted ``source`` values
     - Payload shape
     - Main selectors
   * - ``dem``
     - ``custom``, ``ign_geoplateforme_dem``
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

Reading the matrix as figures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The matrix is easier to use if each provider group is tied to one expected
visual outcome. On the Nancon reference overview, public geographic layers,
Hub'Eau-style observations, and SIM2-style forcing context appear on the same
basin report.

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_geology.png
   :alt: Geology provider output on the Nancon basin
   :width: 100%

   Geographic providers should first produce inspectable spatial layers:
   terrain, geology, hydrography, and basin masks.

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_climatic_summary.png
   :alt: Climatic forcing summary on the Nancon basin
   :width: 100%

   Forcing providers should be checked through period coverage and aggregate
   forcing summaries before their values are sent to a solver.

Provider replay cases
~~~~~~~~~~~~~~~~~~~~~

The compact matrix tells which providers exist. The replay cases show what
their committed artifacts look like and where provider-specific comparisons
already exist.

.. figure:: /_static/user_guide/data/hubeau_provider_replay_examples.png
   :alt: Hub'Eau provider replay across observation families
   :width: 100%

   Hub'Eau covers several observation families. Treating all of them as one
   generic time series would hide the station metadata, quality fields, and
   different semantics.

.. figure:: /_static/user_guide/data/hydrography_provider_replay_examples.png
   :alt: Hydrography provider replay for custom, BD Topage, OSM, and EU-Hydro data
   :width: 100%

   Hydrography provider examples need source-specific comparisons. The current
   replay is stable for custom, BD Topage, OSM, and EU-Hydro artifacts.

.. figure:: /_static/user_guide/data/hydrography_provider_couesnon_comparison.png
   :alt: Couesnon hydrography comparison between BD Topage, OSM, and EU-Hydro
   :width: 100%

   A source value is a modeling decision, not just a loader switch. On this
   bbox, the public hydrography providers produce visibly different density
   and continuity.

Open :doc:`provider-replay-cases` for the complete provider replay page.

Provider families
~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 30 48

   * - Provider group
     - Source values
     - Typical role
   * - Public geographic layers
     - ``ign_geoplateforme_dem``, ``brgm_1m``, ``brgm_50k``,
       ``bdtopage``, ``euhydro``, ``osm``
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
~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~

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

Data families
-------------

Each family page documents a typed data input. It lists accepted ``source``
values, a minimal TOML example, expected loaded shape, and the first
diagnostic figure to inspect. Each family page also bundles the
source-specific sections (``custom``, public providers, synthetic) that
used to live in dedicated leaf pages.

.. list-table::
   :header-rows: 1
   :widths: 22 28 50

   * - Group
     - Families
     - Main role
   * - Spatial support
     - :doc:`dem`, :doc:`geology`, :doc:`hydrography`
     - Build watershed support, zones, river networks, and mesh constraints.
   * - Observations
     - :doc:`hydrometry`, :doc:`piezometry`, :doc:`intermittency`,
       :doc:`water-quality`
     - Discover or ingest stations and observed chronicles.
   * - Forcing
     - :doc:`recharge`, :doc:`precipitation`, :doc:`etp`, :doc:`temperature`,
       :doc:`wind`, :doc:`humidity`, :doc:`radiation`, :doc:`soil-moisture`,
       :doc:`runoff`
     - Load gridded or point forcing fields over the project period.
   * - Coastal boundary
     - :doc:`oceanic`
     - Load or declare sea-level data for coastal boundary conditions.

.. toctree::
   :maxdepth: 1
   :hidden:

   retrieval-workflow
   runs-and-figures
   provider-replay-cases
   custom-data
   cache-and-lockfiles
   dem
   geology
   hydrography
   hydrometry
   piezometry
   intermittency
   water-quality
   recharge
   precipitation
   etp
   temperature
   wind
   humidity
   radiation
   soil-moisture
   runoff
   oceanic
