Site Selection Workflow
=======================

``site_selection`` prepares a reviewed catalog of candidate catchments before
regional-lab or simulation work. It selects or rejects basins, writes auditable
criteria, and produces a static HTML review report. It does not expand sites
into model recipes and it does not run groundwater solvers.

Use it when the question is still upstream of modeling:

- which gauged catchments should enter a regional campaign;
- whether candidate outlets delineate plausible basins from the DEM;
- which candidates fail blocking criteria such as station distance, record
  length, known influence, or area rules;
- which selected sites should be exported into ``regional_lab_sites.csv``.

Minimal structure
-----------------

.. code-block:: toml

   [workflow]
   mode = "site_selection"

   [site_selection]
   selection_id = "bretagne_hydrometry_50_500_small_v1"
   output_root = "../outputs/bretagne_hydrometry_50_500_small_v1"

   [site_selection.input]
   mode = "hydrometry"
   region_id = "Bretagne"

   [site_selection.strategy]
   principle = "observation_led"
   primary_observation_type = "flow_station"
   candidate_mode = "station_outlets"

   [site_selection.territory]
   mode = "admin_regions"
   country = "FR"
   regions = ["Bretagne"]

   [site_selection.dem]
   source = "data"
   request_extent = "outlets"
   map_background_extent = "territory"

   [hydrometry]
   date_start = "2015-01-01"
   date_end = "2025-01-01"

   [[hydrometry.sources]]
   source = "hubeau"
   product = "QmnJ"
   extent = "study_area"
   require_observations = true
   max_stations = 7

   [data]
   types = ["dem"]

   [[data.dem.sources]]
   source = "ign_geoplateforme_dem"
   dataset = "bd-alti"
   resolution_m = 25.0
   file_format = "ASC"
   regions = ["Bretagne"]

The DEM is deliberately declared under ``[data.dem]``. In hydrometry mode, the
workflow loads the stations first. With ``site_selection.dem.request_extent =
"outlets"``, it uses those projected station outlets to bound the DEM request
before building flow products, delineating catchments, and handing the spatial
artifacts to the selection/reporting layer.

Input modes
-----------

``site_selection`` has three practical input modes.

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Mode
     - Use when
     - Main inputs
   * - ``plan_only``
     - The team needs to review strategy, territory, data needs, and outputs
       before loading observations or delineating basins.
     - ``[site_selection]`` only.
   * - ``delineated_catchments``
     - Candidate outlets or pre-normalized catchments already exist as a CSV,
       often from a fixture, frozen inventory, or previous provider query.
     - ``catchments_csv`` and optionally ``delineate_from_outlets = true``.
   * - ``hydrometry``
     - Stations should be loaded directly through HydroModPy data managers,
       usually Hub'Eau hydrometry over a territory or explicit station list.
     - ``[hydrometry]`` plus ``[data.dem]``.

DEM and observations
--------------------

The workflow keeps data-provider access outside the spatial selection package:

- DEM loading goes through ``hydromodpy.data.variables.dem`` and should be
  configured in ``[data.dem]``.
- Hub'Eau station loading goes through the hydrometry data manager.
- In hydrometry mode, ``request_extent = "outlets"`` limits the calculation DEM
  to the station envelope plus ``margin_km``; the map background can still use
  a broader territory DEM.
- French administrative regions are resolved to departments by the data layer.
- Hub'Eau station coordinates are requested in WGS84 for provider queries, then
  projected to Lambert-93 for DEM delineation. When Hub'Eau exposes official
  Lambert-93 station coordinates, those are preferred.

For French regional examples, ``source = "ign_geoplateforme_dem"`` with
``dataset = "bd-alti"`` and ``resolution_m = 25`` is the current operational
default.

Outlet snapping
---------------

Two snapping strategies are available:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Strategy
     - Behavior
   * - ``dem_accumulation``
     - Snap the candidate outlet directly to the DEM-derived accumulation
       raster within ``snap_dist_m``.
   * - ``bdtopage_then_dem``
     - First project the outlet to BD Topage or a custom reference network,
       reject it if that reference line is too far, then apply the local DEM
       snap.

BD Topage is a technical reference for constraining outlet locations. It should
not be displayed by default in the site-selection map: on regional DEM
backgrounds it can be mistaken for the validated hydrographic network of the
selected basins. The report should show the DEM, selected/rejected basins,
station points, final outlets, and station-to-outlet displacement links.

Outputs
-------

Every executed run writes:

- ``selection_decisions.jsonl``;
- ``criteria_components.jsonl``;
- ``site_selection_manifest.json``;
- ``selected_sites.csv`` and ``rejected_sites.csv``;
- ``regional_lab_sites.csv``;
- selected/rejected outlet and basin GeoJSON files.

When HTML reporting is enabled, the run also writes:

- ``review/index.html``;
- ``review/site_selection_map.png``.

The manifest is the hand-off contract. The HTML report is derived from the
manifest and its declared artifacts, so validation should target the manifest
first.

Examples
--------

The example project contains short cases for Bretagne, Auvergne-Rhone-Alpes,
and Corse:

.. code-block:: bash

   hmp run examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small.toml
   hmp run examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small_bdtopage.toml
   hmp run examples/projects/17_site_selection_workflow/configs/auvergne_rhone_alpes_hydrometry_preview.toml
   hmp run examples/projects/17_site_selection_workflow/configs/corse_hydrometry_preview.toml

Use the direct DEM snap example to check the normal map layout. Use the BD
Topage variant only to inspect outlet-location sensitivity; the reference
network remains an internal snapping support.

Troubleshooting
---------------

- If selected sites appear on a regular grid, check whether the input is a
  synthetic ``area_only`` fixture rather than real hydrometry stations.
- If the DEM is absent from the map, verify ``[data.dem]`` and
  ``site_selection.dem.map_background_extent``.
- If station points and basins are offset, inspect CRS metadata and prefer
  provider Lambert-93 coordinates when available.
- If ``hmp run`` fails while opening an old ``cache.duckdb``, open the cache
  with a recent HydroModPy build once; old V1 data-cache tables are adopted
  into the current ``schema_migrations`` ledger.
