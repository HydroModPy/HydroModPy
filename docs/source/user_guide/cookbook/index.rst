Cookbook
========

Ten short TOML-first recipes covering the most common HydroModPy
tasks. Each recipe pairs a self-contained TOML snippet with the CLI
command that runs it. Copy, adapt, run.

The Python facade is reserved for prototyping; production paths go
through ``hmp run``. See :doc:`/user_guide/cli-reference` for the full
CLI surface and :doc:`/user_guide/config_reference/index` for every
TOML field.

.. contents::
   :local:
   :depth: 1


1. Run a saved project from one TOML
------------------------------------

When the workspace is already laid out and you just want to launch a
simulation against it.

.. code-block:: toml

   [workflow]
   mode = "simulation"

   [workspace]
   project_root = "./my_basin"

   [simulation]
   name = "first_run"

.. code-block:: bash

   hmp run config.toml


2. Build the project from a DEM and outlet coordinates
------------------------------------------------------

DEM-driven catchment delineation, no shapefile needed.

.. code-block:: toml

   [workflow]
   mode = "simulation"

   [workspace]
   project_root = "./my_basin"

   [geographic]
   catch_def = "from_outlet_coord"
   dem_init_path = "data/regional_dem.tif"
   x_outlet = 332100.0
   y_outlet = 6790000.0
   snap_dist = "50 m"
   buff_area = "200 m"

.. code-block:: bash

   hmp run config.toml


3. Build the project from a polygon shapefile
---------------------------------------------

When the watershed boundary is already digitized.

.. code-block:: toml

   [workflow]
   mode = "simulation"

   [geographic]
   catch_def = "from_polyg_shp"
   dem_init_path = "data/regional_dem.tif"
   polyg_shp_path = "data/basin.shp"
   buff_area = "500 m"

.. code-block:: bash

   hmp run config.toml


4. Heterogeneous hydraulic conductivity by zone
-----------------------------------------------

Three zones along the x axis with distinct conductivities.

.. code-block:: toml

   [workflow]
   mode = "simulation"

   [domain.supports.k_bands]
   provider = "generated_bands"
   axis = "x"
   coordinate_mode = "relative"
   breaks = [0.3, 0.7]
   labels = ["west_zone", "middle_zone", "east_zone"]

   [flow.param.K]
   field.kind = "heterogeneous"
   field.values_source = "inline"
   field.values.west_zone = "2e-4 m/s"
   field.values.middle_zone = "5e-5 m/s"
   field.values.east_zone = "1e-4 m/s"
   field.field_spatial_id = "k_bands"

.. code-block:: bash

   hmp run config.toml


5. 1D Boussinesq synthetic strip
--------------------------------

A pure analytical-style run with the in-house solver.

.. code-block:: toml

   [workflow]
   mode = "simulation"

   [geographic]
   source_mode = "synthetic"

   [geographic.synthetic.grid]
   length_x = "400 m"
   length_y = "50 m"
   nx = 40
   ny = 5

   [solver]
   solver_engine = "boussinesq"

   [flow]
   flow_regime = "steady"
   active_bc = ["west_side", "east_side"]

   [flow.bc.dirichlet.west_side]
   value = "10 m"
   [flow.bc.dirichlet.east_side]
   value = "5 m"

.. code-block:: bash

   hmp run boussinesq_strip.toml


6. Calibration with the grid optimizer
--------------------------------------

Bracket K with the built-in grid sweep, no extra dependency required.

.. code-block:: toml

   [workflow]
   mode = "calibration"

   [calibration]
   method = "grid"
   max_iter = 50
   objective = "nse"

   [calibration.parameters.K]
   kind = "homogeneous"
   bounds = [1e-6, 1e-3]
   prior = "log_uniform"

.. code-block:: bash

   hmp run calibration.toml


7. Compare MODFLOW 6 and Boussinesq on the same case
----------------------------------------------------

The ``comparison`` workflow orchestrates several solver variants and
gathers metrics under one parent run.

.. code-block:: toml

   [workflow]
   mode = "comparison"

   [comparison]
   base_config = "shared_base.toml"

   [[comparison.simulation]]
   name = "modflow6_run"
   override = "[solver]\nsolver_engine = \"modflow6\""

   [[comparison.simulation]]
   name = "boussinesq_run"
   override = "[solver]\nsolver_engine = \"boussinesq\""

.. code-block:: bash

   hmp run comparison.toml


8. Generate a mesh only, no simulation
--------------------------------------

Useful when iterating on conformal meshing before a full run.

.. code-block:: toml

   [workflow]
   mode = "mesh"

   [workspace]
   project_root = "./my_basin"

   [geographic]
   catch_def = "from_polyg_shp"
   dem_init_path = "data/regional_dem.tif"
   polyg_shp_path = "data/basin.shp"
   buff_area = "500 m"

   [mesh_catchment]
   constraints_mode = "geology_rivers"
   [mesh_catchment.geology]
   path = "data/geology.shp"

.. code-block:: bash

   hmp run mesh_only.toml


9. Batch over a regional site catalog
-------------------------------------

Expand the same recipe across many sites listed in a CSV catalog.

.. code-block:: toml

   [workflow]
   mode = "batch"

   [analysis.batch.catalog]
   path = "sites.csv"
   id_field = "site_id"
   x_field = "x"
   y_field = "y"

   [[analysis.batch.recipe]]
   id = "default_simulation"
   label = "Steady simulation per site"
   launcher = "simulation"
   config_path_template = "configs/{site_id}/config.toml"

.. code-block:: bash

   hmp run regional_lab.toml


10. Persist results to NetCDF for downstream tooling
----------------------------------------------------

Toggle the NetCDF exporter from the persistence section.

.. code-block:: toml

   [workflow]
   mode = "simulation"

   [persistence]
   save_zarr = true
   save_parquet = true

   [simulation.results.exporters.netcdf]
   enabled = true

.. code-block:: bash

   hmp run config.toml
