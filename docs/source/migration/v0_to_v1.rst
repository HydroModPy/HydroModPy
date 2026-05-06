Migration from HydroModPy v0 to v1
==================================

HydroModPy 1.0 promotes a TOML-first interface and consolidates the
former Python-driven API into a single :class:`Project` facade. The
previous ``Watershed`` and ``master_config`` entry points are no
longer publicly supported.

This page lists the explicit mappings so you can update existing
notebooks and scripts.

Top-level entry point
---------------------

.. list-table::
   :header-rows: 1
   :widths: 38 38 24

   * - v0 (legacy)
     - v1 (current)
     - Stability
   * - ``Watershed(...)``
     - ``hmp.open(<toml>)`` or ``Project(config)``
     - :deprecated:`removed in 1.0`
   * - ``master_config = {...}``
     - ``HydroModPyConfig.from_toml(<toml>)``
     - :deprecated:`removed in 1.0`
   * - ``run_modflow_nwt(...)``
     - ``hmp run <toml>`` (CLI) or ``Project(config).run()``
     - :stable:`since 1.0`
   * - ``ws.calibrate(...)``
     - ``Project(config).calibrate()`` driven by ``[calibration]``
     - :stable:`since 1.0`
   * - manual ``flopy.modflow`` glue
     - solver selected via ``[solver] solver_engine``, configured per backend
     - :stable:`since 1.0`

Configuration namespace
-----------------------

In v0 every parameter lived as a Python attribute on ``Watershed``.
In v1 every parameter lives in a TOML section validated by Pydantic.
A few representative renames:

.. list-table::
   :header-rows: 1
   :widths: 36 36 28

   * - v0 attribute
     - v1 TOML location
     - Notes
   * - ``ws.dem_path``
     - ``[geographic] dem_init_path``
     - Same semantics, validated path resolution.
   * - ``ws.outlet = (x, y)``
     - ``[geographic] x_outlet`` and ``y_outlet``
     - Pair with ``catch_def = "from_outlet_coord"``.
   * - ``ws.K = 1e-4``
     - ``[flow.param.K] kind = "homogeneous"`` etc.
     - Heterogeneous fields now require an explicit support id.
   * - ``ws.nx, ws.ny``
     - ``[modflownwt.sgrid.planar] nx, ny`` or ``[modflow6.sgrid.planar] nx, ny``
     - Solver-scoped to keep MODFLOW 6 and NWT independent.
   * - ``ws.run_modpath()``
     - ``[transport.modpath]`` plus ``[[simulation.process]]`` for transport
     - Particle tracking now flows through the simulation orchestrator.

Mesh-only workflow
------------------

The standalone mesh build that was driven by ``Watershed.build_mesh``
is now an explicit workflow in TOML:

.. code-block:: toml

   workflow = "mesh"

   [workspace]
   project_root = "./my_basin"

   [geographic]
   catch_def = "from_polyg_shp"
   dem_init_path = "data/dem.tif"
   polyg_shp_path = "data/basin.shp"
   buff_area = "500 m"

   [mesh_catchment]
   constraints_mode = "geology_rivers"
   [mesh_catchment.geology]
   path = "data/geology.shp"

Calibration
-----------

The legacy ``ws.calibrate(method="...")`` call is replaced by a
declarative ``[calibration]`` block plus the ``calibration``
workflow:

.. code-block:: toml

   workflow = "calibration"

   [calibration]
   method = "grid"
   max_iter = 100
   objective = "nse"

   [calibration.parameters.K]
   kind = "homogeneous"
   bounds = [1e-6, 1e-3]
   prior = "log_uniform"

Removed knobs
-------------

The following options no longer exist in v1 and the migration story
is to drop them. They were either replaced by a more general field or
relied on private state.

- ``Watershed.draw(...)``: replaced by the registered figure catalog
  (see ``[display.figures]`` and the :doc:`/user_guide/figures` page).
- ``Watershed.export_to_excel(...)``: replaced by Parquet exports
  controlled via ``[persistence] save_parquet``.
- private attributes prefixed with ``_`` on ``Watershed``: removed.
  See :doc:`/user_guide/troubleshooting` if a script breaks because of
  one of these.

Where to go next
----------------

- :doc:`/getting_started/index` for the v1 first-run path.
- :doc:`/user_guide/config_reference/index` for every TOML field.
- :doc:`/how_to_cite` if you want to cite v1 in a paper.
