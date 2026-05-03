Results and Exports
===================

HydroModPy writes durable results at the workspace level. The DuckDB catalog
stores run metadata, metrics, parameters, budgets, provenance, and lookup
tables. Per-run stores hold fields, meshes, rasters, timeseries, and derived
arrays.

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
   metrics = catalog.query_field(run.sim_id, "head")
   run.export("run_outputs", formats=["netcdf", "geotiff"])

Common catalog operations include listing simulations, resolving ids, finding
the latest or best run, querying fields and timeseries, reading budget and
mass-balance records, exporting portable packages, and importing a package into
another workspace.

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
