Architecture Overview
=====================

.. raw:: html

   <p class="lead">
   Cross-cutting architecture notes that complement the per-package
   pages and the contributor recipes. Open these pages when the
   question is "where does this responsibility live" or "which layer
   should I change", rather than "how does one package work".
   </p>

For the entry point of the developer section, see
:doc:`/architecture/index`. For one focused page per subpackage, see
:doc:`/architecture/packages/index`. For step-by-step extension recipes,
see :doc:`/architecture/how-to/index`.

Foundations
-----------

.. grid:: 1 2 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Mental model and design choices
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mental-model-and-design-choices
      :link-type: doc

      How a TOML payload becomes a persisted run. The reasoning
      behind the package boundaries and the layer matrix.

   .. grid-item-card:: Design patterns
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: design-patterns
      :link-type: doc

      Canonical patterns reused across the codebase: SolverAdapter,
      Step, Figure, DataManager, ProcessSpatial, and friends.

   .. grid-item-card:: Code reading guide
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: code-reading-guide
      :link-type: doc

      Recommended package-by-package reading paths through the
      source tree.

   .. grid-item-card:: Three databases
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: two-databases
      :link-type: doc

      The three-level v2 layout: machine global index, workspace
      input cache, per-project simulation catalog. Why the split
      exists.

Contracts and integration
-------------------------

.. grid:: 1 2 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Schema evolution
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: schema-evolution
      :link-type: doc

      Alembic-like migration runner that applies versioned SQL
      migrations on every catalog DuckDB plus the
      ``ZARR_SCHEMA_VERSION`` and ``PARQUET_SCHEMA_VERSION`` pins.

   .. grid-item-card:: Protocols and contracts
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: contracts
      :link-type: doc

      ``CatalogBackend`` Protocol, ``SimulationStore`` Protocol, and
      the field registry consumed by the ``hmp.read`` facade.

   .. grid-item-card:: Frontend hooks
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: frontend-hooks
      :link-type: doc

      JSON Schema export, OpenAPI 3.1 wrapper, and the
      partial-validator contract that any UI integration consumes.

   .. grid-item-card:: Test families and quality roles
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: test-families-and-quality-roles
      :link-type: doc

      The test ladder: unit, integration, regression, validation,
      MMS, solver sanity, calibration twins, with the role and
      command per family.

   .. grid-item-card:: Test inventory
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: test-inventory
      :link-type: doc

      Snapshot of the collected pytest suite: counts by family,
      largest unit-test areas, validation subsets, and regression
      coverage.

.. toctree::
   :hidden:
   :maxdepth: 1

   mental-model-and-design-choices
   design-patterns
   code-reading-guide
   two-databases
   schema-evolution
   contracts
   frontend-hooks
   test-families-and-quality-roles
   test-inventory
