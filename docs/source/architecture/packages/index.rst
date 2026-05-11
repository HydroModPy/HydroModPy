Per-Package Reference
=====================

One focused page per top-level subpackage of ``hydromodpy/``. Each
page covers:

- the package role (what question it answers);
- the sub-modules and their responsibilities;
- the key public symbols a contributor needs to know;
- the recommended reading path inside the code;
- the layer-matrix neighbours and the documented tolerances.

For high-level questions (mental model, layer matrix, design
patterns), see :doc:`/architecture/index` and the foundation pages
listed there.

For prescriptive questions ("how do I add X"), see
:doc:`../how-to/index`.

Subpackages
-----------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: core
      :link: core
      :link-type: doc

      Kernel leaf: units, ``Profile``, workspace, metrics, I/O, runtime
      state, input-file tracking.

   .. grid-item-card:: config
      :link: config
      :link-type: doc

      Root ``HydroModPyConfig`` Pydantic model that aggregates every
      TOML section.

   .. grid-item-card:: physics
      :link: physics
      :link-type: doc

      Process layer: ``ProcessSpatial``, ``Flow``, ``Transport``,
      forcing bridge, hydrology helpers.

   .. grid-item-card:: data
      :link: data
      :link-type: doc

      17 variables, source registry, planner, DuckDB cache.

   .. grid-item-card:: spatial
      :link: spatial
      :link-type: doc

      Delineation, geographic context, domain, mesh (Cartesian and
      Gmsh), field abstractions, ``HydroMesh`` pivot.

   .. grid-item-card:: solver
      :link: solver
      :link-type: doc

      Backend abstraction plus three concrete backends: MODFLOW 6,
      MODFLOW-NWT, Boussinesq.

   .. grid-item-card:: simulation
      :link: simulation
      :link-type: doc

      Planner, runner, extraction post-run, simulation-side
      adapters.

   .. grid-item-card:: calibration
      :link: calibration
      :link-type: doc

      Ask/tell engine, parameter sets, objective dispatch, optimizer
      adapters.

   .. grid-item-card:: results
      :link: results
      :link-type: doc

      Workspace catalog, ``Run`` facade, importers, exporters.

   .. grid-item-card:: display
      :link: display
      :link-type: doc

      33 named figures registered through a single catalog.

   .. grid-item-card:: analysis
      :link: analysis
      :link-type: doc

      Cross-run analysis: regional batch, simulation comparison,
      testbed, stream-network metrics.

   .. grid-item-card:: workflow
      :link: workflow
      :link-type: doc

      Composable steps and the immutable ``PipelineState`` payload.

   .. grid-item-card:: schema
      :link: schema
      :link-type: doc

      JSON Schema export and partial-field validator for frontends.

   .. grid-item-card:: cli
      :link: cli
      :link-type: doc

      ``hmp`` and ``hydromodpy`` console entry points; one verb per
      module under ``cli/commands/``.

.. toctree::
   :hidden:
   :maxdepth: 1

   core
   config
   physics
   data
   spatial
   solver
   simulation
   calibration
   results
   display
   analysis
   workflow
   schema
   cli
