Project API
===========

The ``Project`` facade is the Python path for users who want the same behavior
as TOML workflows but need programmatic control.

``Project`` is the session object: it owns the resolved config, workspace,
geographic/domain runtime, loaded data, mesh, and catalog handles. The
``Pipeline`` is the execution engine: it runs ordered steps with checkpoint and
resume support. Both call the same ``workflow.steps`` helpers; ``Project`` only
offers a more interactive way to drive them.

Minimal paths
-------------

.. code-block:: python

   import hydromodpy as hmp

   result = hmp.run("examples/projects/00_getting_started/run_demo.toml")
   catalog = hmp.open("~/hydromodpy")

For explicit lifecycle control:

.. code-block:: python

   import hydromodpy as hmp

   with hmp.Project.lazy("project.toml") as project:
       project.setup_workspace()
       project.build_geographic()
       project.load_data()
       project.build_mesh()
       run = project.run()

Lifecycle methods
-----------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Method
     - Role
   * - ``Project.lazy(config)``
     - Build the facade without immediately running setup/data/mesh phases.
   * - ``setup_workspace()``
     - Bootstrap the shared runtime anchor: workspace, geographic context,
       domain, and process objects.
   * - ``build_geographic()``
     - Mark the geographic/domain runtime ready and invalidate downstream
       data/mesh state when rerun.
   * - ``load_data()`` / ``reload_data()``
     - Load configured data managers and bind external data to the runtime.
   * - ``rebuild_geographic()``
     - Rerun geographic preprocessing and invalidate dependent mesh state.
   * - ``build_mesh()``
     - Build or load the mesh used by the solver.
   * - ``prepare()``
     - Run the setup/data/mesh phases needed before execution.
   * - ``execute()``
     - Run the configured solver or process execution phase.
   * - ``ingest()``
     - Persist solver outputs into the result store.
   * - ``render()``
     - Render configured display figures.
   * - ``cleanup()``
     - Close runtime resources and temporary state.
   * - ``run()``
     - Execute the complete workflow path.

Workflow helpers
----------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Method
     - Role
   * - ``overview()``
     - Generate a data/geographic overview without a solver run.
   * - ``simulate()``
     - Run a standard simulation workflow.
   * - ``compare()``
     - Launch pairwise or workflow-level comparison logic.
   * - ``batch()``
     - Run regional or multi-case batches.
   * - ``calibrate()``
     - Run calibration from the project configuration.
   * - ``sweep()``
     - Execute controlled parameter or configuration sweeps.

State accessors
---------------

Useful read-only properties include ``phase``, ``status``, ``data``, ``runs``,
``geographic``, ``domain``, ``store``, ``time_grid``, and ``loaded_data``.
They expose the same runtime state that TOML workflows populate through the
pipeline.

When to prefer the CLI
----------------------

Use TOML plus ``hmp run`` for reproducible research, teaching material, and CI.
Use ``Project`` when a notebook, calibration method, custom analysis loop, or
application needs to orchestrate the same steps directly.

For autosummary references, see :doc:`../api/index`.
