Project vs Run
==============

HydroModPy V1 names every level of the hierarchy explicitly so the API
stops overloading the word "simulation". The contract is
**workspace > project > run**.

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
     - Root directory with ``workspace.toml`` plus a shared ``data/``
       folder (``data/cache.duckdb`` and raw inputs). Federated by the
       machine global index ``index.duckdb``.
   * - N
     - **Project**
     - One ``projects/<name>/project.toml`` plus the per-project
       ``catalog.duckdb`` and ``simulations/`` folder. Open with
       :class:`hmp.Project <hydromodpy.project.Project>` for a
       setup-once / run-many Python session, or fire-and-forget with
       ``hmp run project.toml``.
   * - N
     - **Run**
     - One simulation result in the project catalog, identified by
       UUID v7. Built by ``project.simulate(**overrides)`` or retrieved
       from ``catalog[sim_ref]`` / ``catalog.best(...)`` /
       ``RunSet`` queries as a
       :class:`~hydromodpy.results.run.Run`.

Programmatic flow
-----------------

.. code-block:: python

   import hydromodpy as hmp

   project = hmp.Project("~/ws/projects/canut/project.toml")

   # Setup-once / run-many: share the context between runs
   baseline = project.simulate(K=5e-5, name="baseline")
   sensitivity = project.simulate(K=1e-4, name="K_up")
   project.close()

   # Open-and-query: jump straight to any run
   catalog = hmp.open("~/ws/projects/canut")
   best = catalog.best(metric="nse")

   # Read a field through the V1 facade
   head = hmp.read(best, "head", timestep=0)

CLI equivalents
---------------

.. list-table::
   :header-rows: 1

   * - CLI
     - Python
   * - ``hmp run project.toml``
     - ``hmp.Project(toml).simulate()``
   * - ``hmp catalog ls``
     - ``hmp.open(project).frame``
   * - ``hmp catalog show <sim_ref>``
     - ``hmp.open(project)[sim_ref]``
   * - ``hmp display``
     - ``hmp.viz.show(run, ...)``
   * - ``hmp index search``
     - ``hmp.index().search(...)``
