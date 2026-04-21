Project vs Run
==============

HydroModPy v0.6 names every object in the hierarchy explicitly so the API
stops overloading the word "simulation".

Three levels
------------

.. list-table::
   :header-rows: 1
   :widths: 15 40 45

   * - Level
     - Object
     - Role
   * - 1
     - **Workspace**
     - One directory with ``hydromodpy.duckdb``, ``data/``, ``simulations/``,
       and ``projects/``. Open with ``hmp.open(path)`` — returns a
       :class:`~hydromodpy.results.catalog.SimulationCatalog`.
   * - N
     - **Project**
     - One runnable TOML under ``projects/<name>/``. Instantiate with
       :class:`hmp.Project <hydromodpy.project.Project>` for a
       setup-once/run-many Python session, or fire-and-forget with
       ``hmp run project.toml``.
   * - N
     - **Run**
     - One simulation result in the catalog, identified by UUID. Built by
       ``project.run(**overrides)`` or retrieved from ``catalog[sim_id]`` /
       ``catalog.best(...)`` / ``SimulationGroup`` queries as a
       :class:`~hydromodpy.results.run.Run`.

Programmatic flow
-----------------

.. code-block:: python

   import hydromodpy as hmp

   project = hmp.Project("~/ws/projects/canut/project.toml")

   # Setup-once / run-many: share the context between runs
   baseline = project.run(K=5e-5, name="baseline")
   sensitivity = project.run(K=1e-4, name="K_up")
   project.close()

   # Open-and-query: jump straight to any run
   catalog = hmp.open("~/ws")
   best = catalog.best("canut", metric="nse")
   best.plot("watertable_map")

CLI equivalents
---------------

+---------------------+-------------------------------------------+
| CLI                 | Python                                    |
+=====================+===========================================+
| ``hmp run cfg.toml``| ``hmp.Project(cfg.toml).run()``           |
+---------------------+-------------------------------------------+
| ``hmp list``        | ``hmp.open(ws).simulations``              |
+---------------------+-------------------------------------------+
| ``hmp show <id>``   | ``hmp.open(ws)[sim_id]``                  |
+---------------------+-------------------------------------------+
| ``hmp display``     | ``hmp.open(ws)[sim_id].plot(...)``        |
+---------------------+-------------------------------------------+

Migration from v0.5
-------------------

The v0.5 names ``Simulation`` (in ``hydromodpy.project``) and
``SimulationView`` (in ``hydromodpy.results.simulation``) are removed in
v0.6. Update imports:

.. code-block:: diff

   - from hydromodpy.project import Simulation
   - with Simulation(cfg) as sim:
   + from hydromodpy.project import Project
   + with Project(cfg) as project:
         ...

   - from hydromodpy.results.simulation import SimulationView
   + from hydromodpy.results.run import Run

The top-level module exports ``hmp.Project`` and ``hmp.Run`` for the same
effect.
