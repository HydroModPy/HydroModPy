Architecture and Developer Guide
================================

This section is the developer-facing reference for HydroModPy. It
documents the package architecture, the design patterns, the storage
layout, the test layers, and the contributor recipes for extending the
toolbox.

For user-facing documentation, see :doc:`/user_guide/index`. For
scientific notes and equations, see :doc:`/theory/index`.

Where to start
--------------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: New to the codebase?
      :link: overview/mental-model-and-design-choices
      :link-type: doc

      Read the mental model first: how a TOML becomes a persisted run.

   .. grid-item-card:: Want to extend HydroModPy?
      :link: how-to/index
      :link-type: doc

      Step-by-step recipes: add a solver, a config field, a data
      source, a figure, a test, a CLI command, a calibration method,
      or build a frontend.

   .. grid-item-card:: Looking for a subpackage?
      :link: packages/index
      :link-type: doc

      One concise reference page per top-level subpackage of
      ``hydromodpy/``.

   .. grid-item-card:: Need a precise contract?
      :link: layered-architecture
      :link-type: doc

      The 14-layer dependency matrix that every commit must respect.

Foundations
-----------

The pages below are the architectural backbone. Read them once before
diving into a specific package.

- :doc:`package-layout` -- the 14 subpackages and the top-level facade.
- :doc:`layered-architecture` -- the strict layer matrix and the
  one-way import rule.
- :doc:`overview/mental-model-and-design-choices` -- how a configuration
  becomes a persisted result, and why the layers are split that way.
- :doc:`overview/design-patterns` -- the canonical patterns reused
  across the codebase (SolverAdapter, Step, Figure, DataManager,
  ProcessSpatial, etc.).
- :doc:`overview/code-reading-guide` -- recommended package-by-package
  reading paths.
- :doc:`overview/two-databases` -- the workspace layout with one input
  cache and one simulation catalog.
- :doc:`storage-layout` -- the full DuckDB schema, Zarr stores,
  Parquet tables, and the basename rule.
- :doc:`overview/schema-evolution` -- the versioning policy applied to
  future storage migrations.
- :doc:`overview/frontend-hooks` -- the JSON Schema and partial-validator
  contract that any UI integration consumes.
- :doc:`overview/test-families-and-quality-roles` -- the test ladder
  with role and command per family.

Contributor recipes
-------------------

The :doc:`how-to/index` section answers prescriptive questions: "I
need to add X, where does it go and what contract must I honour?".
Read the matching recipe before opening files.

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Add a solver
      :link: how-to/add-a-solver
      :link-type: doc

      A new flow / transport / postprocess backend bound to a
      ``(process_type, solver_name)`` pair.

   .. grid-item-card:: Add a config field
      :link: how-to/add-a-config-field
      :link-type: doc

      A new TOML knob backed by a Pydantic model with units and a
      Profile annotation.

   .. grid-item-card:: Add a data source
      :link: how-to/add-a-data-source
      :link-type: doc

      A new public API or local-file source bound to an existing data
      variable.

   .. grid-item-card:: Add a figure
      :link: how-to/add-a-figure
      :link-type: doc

      A new entry in the display registry consumable by ``Run.plot``
      and the ``[display]`` section.

Per-package reference
---------------------

The :doc:`packages/index` section gives one focused page per top-level
subpackage. Each page covers the package role, its sub-modules, the
key public symbols, and the recommended reading path inside the code.

Detailed reference pages
------------------------

These pages remain as deep dives for specific subsystems. They
complement the per-package summaries.

.. toctree::
   :maxdepth: 2
   :caption: Foundations

   package-layout
   layered-architecture
   storage-layout
   overview/index

.. toctree::
   :maxdepth: 2
   :caption: How-to (contributor recipes)

   how-to/index

.. toctree::
   :maxdepth: 2
   :caption: Per-package reference

   packages/index

.. toctree::
   :maxdepth: 2
   :caption: Detailed pages

   data_loading/index
   spatial_support/index
   field/index
   mesh/index
   mesh_pivot
   gmsh_meshing
   modflow_contracts
   process/index
   solver/index
   simulation/index
   calibration/index

.. toctree::
   :maxdepth: 2
   :caption: Contributing

   Contributing handbook <../contribute>
