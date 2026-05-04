User API
========

Use this layer for normal modelling work. It keeps the public entry points in
one place and points to generated pages for signatures and docstrings.

Task Map
--------

.. list-table::
   :header-rows: 1
   :widths: 30 34 36

   * - Task
     - Start with
     - Then read
   * - Open an existing workspace
     - :func:`hydromodpy.open`
     - :class:`hydromodpy.results.catalog.SimulationCatalog`
   * - Run a TOML workflow
     - :func:`hydromodpy.run`
     - :class:`hydromodpy.project.Project`
   * - Work from Python
     - :class:`hydromodpy.project.Project`
     - :class:`hydromodpy.results.run.Run`
   * - Read and compare results
     - :class:`hydromodpy.results.run.Run`
     - :class:`hydromodpy.results.simulation_group.SimulationGroup`
   * - Export persisted data
     - Export helpers
     - :doc:`hydromodpy-project-results`
   * - Validate a configuration
     - ``HydroModPyConfig.from_toml``
     - :doc:`hydromodpy-config`
   * - Build a UI or frontend
     - ``hydromodpy.schema``
     - :doc:`hydromodpy-schema`

Reference Groups
----------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-project-results
      :link-type: doc

      **Project and results**
      ^^^
      Top-level functions, ``Project``, ``Run``, ``SimulationCatalog``,
      simulation groups, and export helpers.

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-config
      :link-type: doc

      **Configuration**
      ^^^
      Root TOML contracts, workspace settings, and geographic configuration
      models.

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-display
      :link-type: doc

      **Display**
      ^^^
      Figure registry, figure classes, and solver-independent rendering entry
      points.

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-schema
      :link-type: doc

      **Schema**
      ^^^
      JSON Schema export and field validation hooks for external interfaces.

Import Rule
-----------

Prefer the documented public path. If two paths expose the same concept, the
path shown in this API section is the one to use in user code.

.. toctree::
   :hidden:
   :maxdepth: 2

   hydromodpy-project-results
   hydromodpy-config
   hydromodpy-display
   hydromodpy-schema
