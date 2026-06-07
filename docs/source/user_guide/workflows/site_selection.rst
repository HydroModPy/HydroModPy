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
   profile = "gauged_downstream_station"
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

Short-term profiles
-------------------

Two profiles are considered operational for the current site-selection work.
They keep the configuration readable while leaving room for later
multi-criteria extensions.

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Profile
     - Use when
     - Required shape
   * - ``area_only``
     - The goal is to find DEM-delineated catchments around a target drainage
       area, without using observations as selection evidence.
     - ``principle = "criteria_crossing"``, ``primary_axes = ["area"]``, and a
       DEM-driven input such as ``site_selection.input.mode = "dem_area_light"``.
   * - ``gauged_downstream_station``
     - The goal is to select gauged catchments whose outlet is represented by a
       downstream flow station.
     - ``principle = "observation_led"``, ``primary_observation_type =
       "flow_station"``, and ``candidate_mode = "station_outlets"``.

Provider status
---------------

The workflow separates provider loading from site-selection criteria. This is
intentional: provider code lives under ``hydromodpy.data``; the
``site_selection`` package consumes normalized layers, stations, outlets, and
basins.

.. list-table::
   :header-rows: 1
   :widths: 22 39 39

   * - Theme
     - Available in ``site_selection`` now
     - Natural next providers
   * - Dams and human influences
     - No direct ROE or BNPE provider is wired into ``site_selection`` yet.
       The current criterion consumes user-declared vector layers through
       ``[[site_selection.criteria.influence.layers]]`` and can mark
       ``major_dam_upstream``, ``major_withdrawal_upstream``, or
       ``major_regulated_reach``. For gauged catchments, Hub'Eau hydrometry
       station metadata can also be used through the ``station_influence``
       observation criterion; this is a station-quality filter, not a spatial
       proof that no upstream dam exists.
     - ROE for obstacles such as dams and weirs; BNPE or Hub'Eau withdrawals
       for water-abstraction pressure; local DREAL, DDT, SAGE, EPTB, or
       operator inventories when they are more complete locally.
   * - Geology
     - ``site_selection`` can intersect configured geology polygon layers and
       report geology evidence. It does not yet automatically transform
       ``[data.geology]`` provider outputs into a site-selection criterion.
     - BRGM ``brgm_1m`` and ``brgm_50k`` already exist in the data package;
       BDLISA is a relevant later source when the question is
       hydrogeological units rather than geological formations.
   * - DEM candidate generation
     - The ``dem_area_light`` mode generates area-driven candidate outlets and
       caps the number of DEM delineations before final selection.
     - A future network-aware generator could favor hydrologically meaningful
       outlets, reduce nested or near-duplicate basins, improve coastal
       behavior, and make large territories faster to review.

For hydrometry-led selections, station influence metadata can be made active
without adding a separate dam layer:

.. code-block:: toml

   [site_selection.criteria.observations.station_influence]
   mode = "warning"
   source = "hubeau_station_metadata"
   unknown_policy = "neutral"

Use ``mode = "hard_reject"`` only when the campaign should exclude stations
whose hydrometric metadata explicitly reports a local or general hydrologic
influence through ``influence_locale_station`` or
``influence_generale_site``. Unknown influence metadata is not rejected by
default. Comment keyword matches are shown as warnings for review; they are not
treated as hard-reject evidence.

Input modes
-----------

``site_selection`` has five explicit input modes. The first three are the
stable day-to-day modes; the generated DEM modes are useful for area-driven or
network-driven candidate discovery.

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
   * - ``dem_area_light``
     - The campaign should discover DEM-derived outlets around a target basin
       area, with a bounded number of delineations for fast review.
     - ``strategy.profile = "area_only"``, ``primary_axes = ["area"]``,
       ``[site_selection.dem_area_light]`` and ``[data.dem]``.
   * - ``generated_candidates``
     - The campaign should sample high-accumulation DEM/network cells before
       normal delineation and selection. This mode is experimental compared
       with the two short-term supported profiles.
     - ``outlets.candidate_mode = "network_sampling"`` plus ``[data.dem]`` or
       a custom DEM.

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

Every executed selection run writes the audit core:

- ``criteria_components.jsonl``;
- ``site_selection_decisions.csv``;
- ``site_selection_decisions.jsonl``;
- ``site_selection_evidence.jsonl`` when normalized evidence exists;
- ``site_selection_manifest.json``.

Additional outputs follow the configured switches:

- ``selected_sites.csv`` when ``write_csv`` and ``write_selected`` are true;
- ``rejected_sites.csv`` when ``write_csv`` and ``write_rejected`` are true;
- ``regional_lab_sites.csv`` when ``write_regional_lab_csv`` is true;
- selected/rejected outlet and basin GeoJSON files when ``write_geojson`` is
  true;
- GeoPackage and GeoParquet layers when their corresponding switches are true.

Generated DEM modes also write ``candidate_generation.jsonl``. When
``write_geojson`` is true, they write ``candidate_outlets.geojson`` and
``generated_dem_network.geojson`` as review artifacts.

When HTML reporting is enabled, the run also writes:

- ``review/index.html`` as the main review entry point, with a
  per-block detail selector;
- ``review/compact/index.html``;
- ``review/standard/index.html``;
- ``review/audit/index.html``;
- ``review/site_selection_map.png``.

The manifest is the hand-off contract. The HTML report is derived from the
manifest and its declared artifacts, so validation should target the manifest
first. ``compact`` is a fast plausibility read, ``standard`` is the default
scientific review, and ``audit`` exposes provenance, detailed criteria tables,
and artifact links. The main ``review/index.html`` page lets each block choose
its own level.

Examples
--------

The example project contains short cases for the two supported short-term
profiles, plus broader regional previews:

.. code-block:: bash

   hmp run examples/projects/17_site_selection_workflow/configs/calvados_dem_area_light_100km2_fast.toml
   hmp run examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small.toml
   hmp run examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small_bdtopage.toml
   hmp run examples/projects/17_site_selection_workflow/configs/auvergne_rhone_alpes_hydrometry_preview.toml
   hmp run examples/projects/17_site_selection_workflow/configs/corse_hydrometry_preview.toml

Use the direct DEM snap example to check the normal map layout. Use the BD
Topage variant only to inspect outlet-location sensitivity; the reference
network remains an internal snapping support.

The two closure examples for the stabilized contract are:

.. list-table::
   :header-rows: 1
   :widths: 28 20 18 34

   * - Config
     - Effective profile
     - Expected result
     - Review HTML
   * - ``calvados_dem_area_light_100km2_fast.toml``
     - ``area_only``
     - 26 candidates, 10 selected, 16 rejected
     - ``outputs/calvados_dem_area_light_100km2_fast_v1/review/index.html``
   * - ``bretagne_hydrometry_50_500_small_bdtopage.toml``
     - ``gauged_downstream_station``
     - 6 candidates, 6 selected, 0 rejected
     - ``outputs/bretagne_hydrometry_50_500_small_bdtopage_v1/review/index.html``

Both paths above are relative to
``examples/projects/17_site_selection_workflow/``. The associated map file is
``review/site_selection_map.png`` in each output directory.

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
