Results and Exports
===================

HydroModPy writes durable results at the workspace level. The DuckDB catalog
stores run metadata, metrics, parameters, budgets, provenance, and lookup
tables. Per-run stores hold fields, meshes, rasters, timeseries, and derived
arrays.

Result Store Map
----------------

.. figure:: /_static/concepts/results/workspace_results_exports.svg
   :alt: Map of the HydroModPy workspace result model and export paths
   :width: 100%

   Read the result system in three layers: the workspace catalog records
   metadata and tabular diagnostics, each run store carries arrays and spatial
   objects, and the reading/export APIs convert those objects into tables,
   scientific files, figures, or portable packages.

Core objects
------------

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Object
     - Role
   * - ``SimulationCatalog``
     - Workspace-level registry opened by ``hydromodpy.open(path)``.
   * - ``Run``
     - One persisted simulation resolved from the catalog.
   * - ``SimulationGroup``
     - A set of runs used for comparison, calibration, or batch analysis.
   * - ``ResultsConfig``
     - Configuration block controlling result persistence and export options.

CLI reading path
----------------

.. code-block:: bash

   hmp list
   hmp list --project my_basin
   hmp show <sim_id>
   hmp inspect <sim_id>
   hmp best my_basin --metric nse
   hmp worst my_basin --metric nse
   hmp compare <sim_a> <sim_b>
   hmp display <sim_id>

``sim_id`` accepts a unique prefix. Use ``hmp inspect`` when you need file and
store details, and ``hmp show`` when you need metadata, metrics, or parameters.

Python reading path
-------------------

.. code-block:: python

   import hydromodpy as hmp

   catalog = hmp.open("~/hydromodpy")
   run = catalog.latest(project="my_basin")
   head0 = catalog.query_field(run.sim_id, "head", timestep=0)
   budget = catalog.query_budget(run.sim_id)
   run.export(variable="head", fmt="netcdf", path="run_outputs/head.nc")

Common catalog operations include listing simulations, resolving ids, finding
the latest or best run, querying fields and timeseries, reading budget and
mass-balance records, exporting portable packages, and importing a package into
another workspace.

Query cookbook
--------------

List completed runs for one project:

.. code-block:: python

   import hydromodpy as hmp

   catalog = hmp.open("~/hydromodpy")
   runs = catalog.list_simulations(
       project="my_basin",
       status="completed",
       order_by="created_at DESC",
   )

Resolve a run id prefix, then open the ``Run`` view:

.. code-block:: python

   sim_id = catalog.resolve("ab12")
   run = catalog[sim_id]

Read a field from the Zarr-backed store:

.. code-block:: python

   head = catalog.query_field(sim_id, "head", timestep=0)
   seepage = catalog.query_field(sim_id, "seepage", timestep=-1)

Read station time series:

.. code-block:: python

   q = catalog.query_timeseries(
       sim_id,
       station_id="J1234010",
       variable="discharge",
       period=("2000-01-01", "2005-12-31"),
   )

Read budgets, mass balance, and provenance:

.. code-block:: python

   budgets = catalog.query_budget(sim_id)
   outlet_budget = catalog.query_budget(sim_id, zone_id="outlet")
   mass_balance = catalog.query_mass_balance(sim_id)
   provenance = catalog.get_provenance(sim_id)

Use SQL when you need a cross-run table:

.. code-block:: python

   ranking = catalog.sql(
       """
       SELECT s.project, s.name, m.metric_name, m.value
         FROM simulations s
         JOIN metrics m ON s.sim_id = m.sim_id
        WHERE s.status = 'completed'
          AND m.metric_name = ?
        ORDER BY m.value DESC
       """,
       ["nse"],
   )

Export cookbook
---------------

Export all persisted timeseries to CSV:

.. code-block:: python

   run.to_csv("exports/timeseries.csv")

Export one field to common external formats:

.. code-block:: python

   run.export(variable="head", fmt="netcdf", path="exports/head.nc")
   run.export(variable="head", fmt="geotiff", path="exports/head_last.tif", timestep=-1)
   run.export(variable="head", fmt="vtu", path="exports/head_last.vtu", timestep=-1)

Package a full run for exchange:

.. code-block:: python

   catalog.export_package(run.sim_id, "exports/my_run.hmp")
   catalog.import_package("exports/my_run.hmp")

Export formats
--------------

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Format
     - Command / API
     - Typical use
   * - CSV
     - ``hmp export`` / ``Run.export``
     - Tables, metrics, timeseries, and lightweight exchange.
   * - GeoTIFF
     - ``hmp export`` / ``Run.export``
     - Raster fields for GIS tools.
   * - NetCDF
     - ``hmp export`` / ``Run.export``
     - Gridded scientific arrays and model outputs.
   * - Shapefile
     - ``hmp export`` / ``Run.export``
     - Vector GIS exchange where legacy tooling needs shapefiles.
   * - VTU
     - ``hmp export --vtu``
     - Mesh and field visualization in ParaView.
   * - ``.hmp``
     - ``hmp export`` / ``hmp add`` / ``hmp import``
     - Portable run package containing config, inputs, results, and manifest.

Temporal conventions in CSV exports
-----------------------------------

Comparison CSV files distinguish state snapshots from period values explicitly.
Use the ``time_role`` column before interpreting ``time_index`` or
``elapsed_seconds``.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - ``time_role``
     - Meaning
   * - ``initial_state``
     - Explicit state before the first transient period. It is useful for
       initial-condition diagnostics, but it is not a budget period.
   * - ``state_snapshot``
     - Instantaneous model state at the reported elapsed time, for example a
       hydraulic-head or watertable map.
   * - ``period_value``
     - Value associated with a completed period. Budget tables also provide
       ``period_index``, ``period_start_seconds``, and
       ``period_end_seconds``.
   * - ``reduced``
     - Row obtained by reducing several time rows, for example with a mean,
       min, max, or sum reducer.

For budgets, ``elapsed_seconds`` is the period end time. Do not compare a
``period_value`` row to an ``initial_state`` row. Boussinesq histories may store
an explicit initial state at ``t = 0``; comparison budget exports skip that row
instead of treating it as a zero-duration budget.

Package exchange
----------------

.. code-block:: bash

   hmp export <sim_id> -o my_run.hmp
   hmp add my_run.hmp
   hmp add my_run.hmp --dry-run

Use ``.hmp`` packages for reproducible handoff between workspaces. Use format
exports when the next consumer is GIS, ParaView, a notebook, or an external
analysis tool.

Documentation boundaries
------------------------

This page is the user entry point. For low-level classes and methods, see
:doc:`../api/hydromodpy-project-results`. For result-page reading order, see
:doc:`../getting_started/reading-results-pages`.
