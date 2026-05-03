Transport Shared Lifecycle
==========================

This page documents the common architecture shared by current transport
adapters.

Lifecycle
---------

The transport lifecycle is:

.. code-block:: text

   simulation plan
   -> transport run selected
   -> required upstream flow model resolved
   -> backend transport model constructed
   -> pre_processing()
   -> processing(write_model=True, run_model=True)
   -> extractor ingests outputs into the catalog

The central architectural point is dependency resolution. A transport adapter
does not search the whole project for a flow model. It receives a run context
and asks for the compatible upstream model declared by its ``requires`` field.

Common Adapter Contract
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Contract element
     - Meaning
   * - ``process_type``
     - Always ``transport`` for these adapters.
   * - ``solver_name``
     - ``modpath``, ``mt3dms``, or ``modflow6gwt``.
   * - ``requires``
     - Compatible upstream flow pair.
   * - ``execute(ctx)``
     - Builds and runs the concrete backend model.
   * - ``RunExecutionResult``
     - Returns the primary model and solver output directory.

Shared Helpers
--------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Path
     - Role
   * - ``hydromodpy.simulation.adapters.transport_helpers``
     - Dependency resolution and output suffix helpers.
   * - ``hydromodpy.physics.transport.transport_config``
     - Validated transport-process configuration.
   * - ``hydromodpy.physics.transport.transport``
     - Runtime transport object exposing solver-specific parameter mappings.

Related Pages
-------------

- :doc:`modflow-transport-adapters`
- :doc:`../../../scientific/solvers/transport/common-concepts`
- :doc:`../process-solver-registry`
