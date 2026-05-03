Overview Workflow
=================

``workflow = "overview"`` builds a watershed identity card. It runs the
geographic and data-loading parts of HydroModPy without running a groundwater
solver.

Use it when the first question is:
"What basin am I modelling, what data are available, and does the spatial
support look coherent?"

Functional Role
---------------

The overview workflow is a pre-solver inspection workflow. It is designed to:

- delineate or load the watershed geometry;
- build the domain and support context;
- load declared observation and input-data families;
- render maps, station inventories, and time-series panels;
- populate the workspace cache so later workflows can reuse data.

It is not designed to:

- execute MODFLOW or Boussinesq;
- calibrate parameters;
- compare solver outputs;
- make numerical-method claims.

Typical Command
---------------

.. code-block:: bash

   hmp run examples/projects/04_data_overview/project.toml

Reference examples:

- ``examples/projects/04_data_overview/project.toml``
- ``examples/projects/05_nancon_data_overview/config_overview.toml``
- ``examples/projects/02_nancon_watershed/run_overview_all_apis.toml``

Representative Results
----------------------

.. figure:: /_static/capability_gallery/geographic/geographic_watershed_dem.png
   :alt: DEM-oriented overview result for the overview workflow
   :width: 100%

   A correct overview run should first produce a convincing DEM-oriented
   watershed framing.

.. figure:: /_static/capability_gallery/geographic/geographic_watershed_local.png
   :alt: Local watershed overview result for the overview workflow
   :width: 100%

   The local figure then confirms which basin overlays and loaded data layers
   are actually available before moving on to meshing or solving.

Minimal Shape
-------------

.. code-block:: toml

   workflow = "overview"

   [workspace]
   project_root = "."

   [geographic]
   catch_def = "from_outlet_coord"
   dem_init_path = "../../data/dem/DEM_armorican_massif.tif"
   x_outlet = 127348.427
   y_outlet = 6835802.564
   snap_dist = "150 m"
   buff_area = "20%"
   crs_project = "EPSG:2154"

   [domain]
   zone_ids = ["geology"]

   [data]
   types = ["geology", "hydrography", "hydrometry"]
   inference_mode = "strict"

   [overview]
   name = "Watershed Data Overview"
   date_start = "2019-01-01"
   date_end = "2025-12-31"

Important Parameters
--------------------

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Section / field
     - Role
     - Practical guidance
   * - ``workflow``
     - Selects the overview launcher.
     - Must be exactly ``"overview"`` for ``hmp run`` dispatch.
   * - ``[workspace]``
     - Resolves where cache and outputs live.
     - Keep one stable workspace while iterating on data choices.
   * - ``[geographic]``
     - Defines catchment extraction or loading.
     - ``catch_def``, outlet coordinates, DEM path, CRS, snap distance, and
       buffer are the first parameters to inspect.
   * - ``[domain]``
     - Defines the model support and depth model.
     - Use it to decide whether geology or zones are part of the spatial
       support even before solving.
   * - ``[data].types``
     - Declares data families to load.
     - Start small, then add hydrometry, intermittency, oceanic, piezometry,
       or climate sources as needed.
   * - ``[overview]``
     - Names and dates the report.
     - Match the date range to the observation families you request.
   * - ``[overview.panels]``
     - Enables or disables report panels.
     - Turn off panels for missing or irrelevant data instead of forcing every
       source to exist.

Panel Controls
--------------

``[overview.panels]`` controls the generated identity-card sections:

.. code-block:: toml

   [overview.panels]
   map_dem = true
   map_geology = true
   map_hydrography = true
   stats_card = true
   timeseries_discharge = true
   timeseries_piezometry = false
   climatic_summary = false
   timeseries_intermittency = true
   timeseries_water_quality = false
   station_inventory = true

Use panel toggles as documentation intent. For example, disabling
``timeseries_piezometry`` says that this overview does not evaluate
piezometric observations, while keeping the rest of the watershed report
valid.

Outputs To Inspect
------------------

Start with the map panels:

1. DEM and watershed boundary.
2. Hydrography overlay.
3. Geology or support map.
4. Station inventory.
5. Observed time series.

If these panels look wrong, do not continue to ``simulation`` yet. Fix the
catchment, source, CRS, or date-range issue first.

Next Pages
----------

- :doc:`../../getting_started/data-overview-walkthrough`
- :doc:`../../capability_gallery/geographic`
- :doc:`../../getting_started/workspace-layout`
- :doc:`../../architecture/spatial_support/index`
