Retrieval Workflow
==================

The retrieval workflow starts from a TOML project and ends with normalized data
records available to the rest of the run. The same pattern works for
``workflow = "overview"`` and for solver workflows that need data-backed
geometry, forcing, observations, or boundary conditions.

Minimal public-data stack
-------------------------

This example uses public providers for a French basin. It is intentionally
small enough to read in one pass:

.. code-block:: toml

   [data]
   project_crs = "EPSG:2154"
   inference_mode = "strict"
   types = ["dem", "geology", "hydrography", "hydrometry", "piezometry", "recharge"]

   [[data.dem.sources]]
   source = "ign_bdalti"
   extent = "watershed"

   [[data.geology.sources]]
   source = "brgm_1m"
   extent = "watershed"

   [[data.hydrography.sources]]
   source = "bdtopage"

   [data.hydrometry]
   date_start = "2018-01-01"
   date_end = "2020-12-31"

   [[data.hydrometry.sources]]
   source = "hubeau"
   product = "QmnJ"
   extent = "watershed"
   require_observations = true
   fallback_search_radius_km = 10

   [data.piezometry]
   date_start = "2018-01-01"
   date_end = "2020-12-31"

   [[data.piezometry.sources]]
   source = "hubeau"
   extent = "watershed"
   product = "level"

   [data.recharge]
   date_start = "2018-01-01"
   date_end = "2020-12-31"

   [[data.recharge.sources]]
   source = "sim2"
   extent = "watershed"

Read it from top to bottom:

- ``types`` is the explicit family list.
- ``project_crs`` is the target CRS for normalized project data.
- ``extent = "watershed"`` asks compatible providers to use the project
  watershed or study-area extent.
- Date windows live on the family section, such as ``[data.hydrometry]``.
- ``hydrography`` providers do not expose an ``extent`` field in their source
  config; the runtime uses the geographic context passed to the hydrography
  manager.

What the stack produces
-----------------------

On the Nancon reference basin, the same kind of declaration produces visible
data diagnostics before any solver is executed.

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_dem.png
   :alt: Nancon DEM and watershed support produced by data overview
   :width: 100%

   DEM retrieval and watershed setup define the spatial support that later
   data families use for clipping, station discovery, and reporting.

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_hydrography.png
   :alt: Nancon hydrography overlay produced by data overview
   :width: 100%

   Hydrography is loaded as a spatial data family. In a data-overview run it is
   rendered directly so that network coverage can be checked before meshing or
   simulation.

.. figure:: /_static/user_guide/data/hydrography_provider_couesnon_comparison.png
   :alt: Provider-specific hydrography comparison on a small bbox
   :width: 100%

   The provider choice itself can change the loaded network. The Couesnon
   replay compares BD Topage, OSM, and EU-Hydro after clipping them to the same
   bbox, which is the kind of check to do before selecting a hydrography source.

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_station_inventory.png
   :alt: Nancon station inventory produced by data overview
   :width: 100%

   Observation-source discovery is not only an internal step. The station
   inventory makes the discovered records auditable by a user.

Active families and inference
-----------------------------

``data.types`` is the user's explicit contract. The planner can also infer
families from other model sections:

.. list-table::
   :header-rows: 1
   :widths: 32 25 43

   * - Runtime clue
     - Inferred family
     - Why
   * - ``domain.zone_ids`` contains ``geology``
     - ``geology``
     - The domain asks for geology-backed zones.
   * - ``flow.active_bc`` contains ``stream``
     - ``hydrography``
     - Stream boundary conditions need a river network.
   * - ``flow.active_bc`` contains ``ocean``
     - ``oceanic``
     - Coastal boundary conditions need sea-level data.

Use ``inference_mode = "warn"`` while exploring. Use
``inference_mode = "strict"`` when the TOML should fail if an inferred family
does not have an explicit section. ``geology`` is the exception: it can be
defaulted when inferred.

Spatial filters
---------------

Most API-backed spatial sources need one of these selectors:

.. list-table::
   :header-rows: 1
   :widths: 26 30 44

   * - Selector
     - Typical families
     - Use it when
   * - ``extent = "watershed"``
     - DEM, geology, Hub'Eau families, SIM2 forcing
     - The project has a resolved watershed and you want the basin window.
   * - ``extent = "study_area"``
     - DEM, geology, Hub'Eau families, SIM2 forcing
     - You want the larger project context when available.
   * - ``mask_path = "..."``
     - DEM, geology, point/time-series families, gridded forcing
     - A local polygon or raster mask is the authoritative spatial filter.
   * - ``station_ids = [...]``
     - Hydrometry, piezometry, water quality, climate-style point sources
     - The stations are known and should not be discovered by bbox.
   * - ``code_departement = [...]``
     - Intermittency
     - ONDE discovery should use French department codes.

Temporal filters
----------------

Time windows are set on the family block:

.. code-block:: toml

   [data.hydrometry]
   date_start = "2020-01-01"
   date_end = "2020-12-31"

   [[data.hydrometry.sources]]
   source = "hubeau"
   extent = "watershed"

The family-level window is reused by all sources in that family. SIM2 sources
also require a project period, so explicit dates are the clearest option for
reproducible forcing downloads.

Running and inspecting
----------------------

Use an overview workflow when you want to audit data without a solver:

.. code-block:: bash

   hmp run examples/projects/05_nancon_data_overview/config_overview.toml

After a run, inspect the workspace data catalog:

.. code-block:: bash

   hmp data list --workspace ~/hydromodpy
   hmp data list --workspace ~/hydromodpy --variable hydrometry
   hmp data check --workspace ~/hydromodpy

Use ``force_refresh = true`` only on the source that should bypass the cache:

.. code-block:: toml

   [[data.recharge.sources]]
   source = "sim2"
   extent = "watershed"
   force_refresh = true

Use ``hmp run --frozen`` when the run must not download or ingest anything that
is not already present and locked.

Observation panels
------------------

Once the data is loaded, the overview workflow can also render the observation
chronicles that later serve comparison or calibration work.

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_timeseries_discharge.png
   :alt: Nancon observed discharge time series
   :width: 100%

   Hydrometry retrieval should be judged through both station discovery and
   the actual chronicle coverage over the requested period.

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_timeseries_piezometry.png
   :alt: Nancon observed piezometry time series
   :width: 100%

   Piezometry follows the same pattern: discover candidate wells, normalize the
   records, then inspect the time-series panel before using it downstream.

Failure triage
--------------

- If a provider says a bbox is missing, add ``extent`` or ``mask_path`` on a
  source that supports it.
- If a time-series provider returns no stations, try explicit ``station_ids``
  or a small ``fallback_search_radius_km``.
- If a custom vector geology file fails, check that ``code_field`` names an
  existing attribute column.
- If a gridded custom forcing has wrong magnitudes, set ``source_unit`` instead
  of editing solver parameters to compensate.
