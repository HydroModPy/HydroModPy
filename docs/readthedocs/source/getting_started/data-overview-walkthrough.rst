Data Overview Walkthrough
=========================

This is the default first HydroModPy workflow if you want to understand how one
basin is assembled before touching meshing or solving.

.. important::

   Start here unless you already know that you need a full solver run on day
   one.

What this workflow teaches
--------------------------

- Extract one watershed from outlet coordinates.
- Build the domain support and depth model.
- Load the main geographic data layers that later workflows reuse.
- Produce readable basin-context figures without running a groundwater solver.

Run it
------

The TOML declares ``workflow = "overview"`` so the same ``hmp run`` entry
point dispatches to the data-only pipeline:

.. code-block:: bash

   hmp run examples/projects/04_data_overview/project.toml

A second variant uses the Nançon catchment with two configs (full
overview and a hydrography-only slice):

.. code-block:: bash

   hmp run examples/projects/05_nancon_data_overview/config_overview.toml
   hmp run examples/projects/05_nancon_data_overview/config_hydrography_only.toml

How the files relate
--------------------

- ``examples/projects/04_data_overview/project.toml`` is the case
  definition. It declares ``workflow = "overview"`` at the top level, so
  ``hmp run`` dispatches to the data-only pipeline (no solver, no mesh).
- The gallery page
  :doc:`../capability_gallery/cases/geographic_watershed_overview`
  republishes stable figures generated from this workflow.
- The focused hydrography page
  :doc:`../capability_gallery/cases/geographic_bdtopage_hydrography_overlay`
  republishes the minimal `BD Topage only` variant when you want to inspect the
  river network overlay in isolation.

Representative results
----------------------

.. figure:: /_static/capability_gallery/geographic/geographic_watershed_dem.png
   :alt: DEM-oriented watershed overview
   :width: 100%

   The DEM-oriented panel is the first figure to check: outlet placement,
   catchment extent, and surrounding terrain context should all look coherent.

.. figure:: /_static/capability_gallery/geographic/geographic_watershed_local.png
   :alt: Local watershed overview
   :width: 100%

   The local overview confirms which basin-scale overlays are actually present
   before any meshing or groundwater solving stage begins.

Read the config in this order
-----------------------------

1. ``[geographic]``:
   This section answers one question first: which basin are we extracting and
   with how much context?
2. ``[domain]``:
   Read this next to see which support zones and depth model later workflows
   would inherit.
3. ``[data]``:
   The ``types`` list tells you which thematic layers should exist in the
   result. Use :doc:`../user_guide/data/index` for the full guide to data
   retrieval, providers, custom files, cache behavior, and lockfiles.
4. Source blocks such as ``[[data.geology.sources]]`` or
   ``[[data.hydrometry.sources]]``:
   These blocks tell you where each layer comes from and which query window is
   used.

Parameters to look at first
---------------------------

- ``catch_def``, ``x_outlet``, and ``y_outlet``:
  these define the watershed anchor.
- ``snap_dist``:
  this controls how aggressively the outlet is snapped to the drainage network.
- ``buff_area``:
  this changes how much surrounding terrain remains visible.
- ``zone_ids`` and ``depth_model``:
  these define the support that a future mesh or solver would inherit.
- ``data.types``:
  this is the fastest switch for simplifying or expanding the workflow.
- Date windows under hydrometry, intermittency, and oceanic data:
  these change the observation horizon without changing the basin geometry.

How to read the outputs
-----------------------

- Read the DEM-oriented figure first:
  it tells you whether the basin sits in the expected regional terrain context.
- Read the local overview second:
  it tells you which basin-scale overlays are actually available.
- If the basin extent looks wrong, fix the outlet and snapping settings before
  editing any downstream modelling section.
- If an expected overlay is missing, check ``data.types`` before assuming a
  source-specific problem.

First modifications to try
--------------------------

- Move ``x_outlet`` and ``y_outlet`` to a nearby catchment.
- Change ``buff_area`` from ``20%`` to a larger or smaller context window.
- Remove one entry from ``data.types`` to see the workflow slim down.
- Tighten or widen the date ranges to understand which data layers are purely
  spatial and which depend on a time window.

Where to go next
----------------

- Open :doc:`../capability_gallery/cases/geographic_watershed_overview` to read
  the stable documentation version of this case.
- Open :doc:`../capability_gallery/cases/geographic_bdtopage_hydrography_overlay`
  if you want the hydrography-only variant with the loaded BD Topage network
  documented panel by panel.
- Continue with :doc:`../user_guide/data/index` when you want to adapt the
  retrieval layer to a new basin, local data archive, or frozen reproducibility
  workflow.
- Continue with :doc:`simulation-walkthrough` once the basin framing and data
  loading logic are clear.
