:html_theme.sidebar_secondary.remove:

Architecture and Developer Guide
================================

.. raw:: html

   <p class="lead">
   The developer-facing reference for HydroModPy. Documents the package
   architecture, design patterns, storage layout, test layers, and the
   contributor recipes for extending the toolbox.
   </p>

For user-facing documentation, see :doc:`/user_guide/index`. For
scientific notes and equations, see :doc:`/theory/index`.

Get started as a contributor
----------------------------

.. grid:: 1 1 1 1
   :gutter: 2 2 3 3

   .. grid-item-card:: Contributor handbook
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: ../contribute
      :link-type: doc

      Editable clone, pre-commit hooks, ``[dev,test,docs]`` extras,
      WSL/PETSc helpers, ``ruff`` workflow, test ladder, Sphinx build
      with ``-j auto`` and PlantUML setup, and the pull-request
      conventions. Start here on day one.

Foundations
-----------

.. grid:: 1 2 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Mental model
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: overview/mental-model-and-design-choices
      :link-type: doc

      How a TOML becomes a persisted run. Read this once before
      diving into any package.

   .. grid-item-card:: Design patterns
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: overview/design-patterns
      :link-type: doc

      Canonical patterns reused across the codebase: SolverAdapter,
      Step, Figure, DataManager, ProcessSpatial.

   .. grid-item-card:: Package layout
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: package-layout
      :link-type: doc

      The 14 subpackages, the top-level facade, and the public-symbol
      contract.

   .. grid-item-card:: Layered architecture
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: layered-architecture
      :link-type: doc

      The strict 14-layer dependency matrix and the one-way import
      rule that every commit must respect.

   .. grid-item-card:: Storage layout
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: storage-layout
      :link-type: doc

      DuckDB schema, Zarr stores, Parquet tables, and the basename
      rule that ties them together.

   .. grid-item-card:: Code reading guide
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: overview/code-reading-guide
      :link-type: doc

      Recommended package-by-package reading paths through the
      source tree.

Per-package reference
---------------------

.. grid:: 1 1 1 1
   :gutter: 2 2 3 3

   .. grid-item-card:: All 14 subpackages
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: packages/index
      :link-type: doc

      One focused page per top-level subpackage. Each page covers
      the package role, its sub-modules, the key public symbols,
      and the recommended reading path through the code.

Contributor recipes
-------------------

.. grid:: 1 1 1 1
   :gutter: 2 2 3 3

   .. grid-item-card:: How-to index
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: how-to/index
      :link-type: doc

      Prescriptive recipes: add a solver, a config field, a data
      source, a figure, a test, a CLI command, a calibration method,
      an exporter, or build a frontend. Start here when extending
      HydroModPy.

Subsystem deep dives
--------------------

.. grid:: 1 2 3 3
   :gutter: 2 2 3 3

   .. grid-item-card:: Simulation
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: simulation/index
      :link-type: doc

      Orchestration walkthrough, class diagrams, time-cycle
      diagrams, the comparison-workflow internals, and the testbed
      workflow.

   .. grid-item-card:: Solver backends
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: solver/index
      :link-type: doc

      MODFLOW 6, MODFLOW-NWT, Boussinesq architecture notes, plus
      the MODFLOW DIS and BAS contracts honoured by HydroModPy.

   .. grid-item-card:: Mesh architecture
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mesh/index
      :link-type: doc

      Catchment-conformal Gmsh meshing, structured-grid path, and
      the cross-mesh pivot format used by every backend.

   .. grid-item-card:: Calibration internals
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: calibration/index
      :link-type: doc

      Code-oriented architecture map plus the full operational
      calibration guide for adding methods and objectives.

   .. grid-item-card:: Data and field
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: data_loading/index
      :link-type: doc

      Data planning and runtime loading, the field abstraction
      shared by every solver, and the external data-source policy.

   .. grid-item-card:: Spatial support and hydrography
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: spatial_support/index
      :link-type: doc

      Support selection, hydrography UML, and the simulated active
      network inventory for stream and seepage diagnostics.

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: Foundations

   package-layout
   layered-architecture
   storage-layout
   overview/index

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: How-to

   how-to/index

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: Per-package reference

   packages/index

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: Subsystem deep dives

   simulation/index
   solver/index
   mesh/index
   calibration/index
   data_loading/index
   spatial_support/index
   field/index
   process/process-architecture

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: Contributing

   Contributing handbook <../contribute>
