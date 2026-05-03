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
     - :doc:`provider-matrix`
     - Decide between public APIs, local files, synthetic forcing, and constants.
   * - Use institutionally curated local datasets
     - :doc:`custom-data`
     - Match local rasters, vectors, or station time series to HydroModPy's
       custom-source conventions.
   * - Make the same run reproducible later
     - :doc:`cache-and-lockfiles`
     - Inspect the cache, update the lockfile, verify hashes, and archive data.
   * - Inspect the generated configuration surface
     - :doc:`../../api/hydromodpy-config`
     - Read the configuration API pages for typed data and source blocks.

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

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_dem.png
   :alt: Nancon DEM and watershed support
   :width: 100%

   Data retrieval first has to produce a credible basin support: DEM, watershed
   boundary, outlet context, and common CRS.

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_station_inventory.png
   :alt: Nancon station inventory from data overview
   :width: 100%

   The same retrieval workflow also exposes which observation stations are
   available before any model run is launched.

.. toctree::
   :maxdepth: 2

   retrieval-workflow
   provider-matrix
   custom-data
   cache-and-lockfiles
