MODFLOW 6 Flow Stack
====================

This page structures the code path for ``flow/modflow6``.

Detailed backend notes remain in :doc:`../../modflow6-architecture-notes`.

Code Reading Layers
-------------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Layer
     - Main paths and responsibility
   * - Registry adapter
     - ``hydromodpy.solver.modflow6.adapters.flow`` declares the
       ``flow/modflow6`` adapter.
   * - Config
     - ``hydromodpy.solver.modflow6.modflow6_config`` validates the
       ``[modflow6.*]`` configuration tree.
   * - Property mapping
     - ``hydromodpy.solver.modflow6.property_mapping`` resolves HydroModPy
       flow properties to MODFLOW 6-ready arrays.
   * - Translation
     - ``hydromodpy.solver.modflow6.flow_to_modflow_adapter`` translates the
       runtime flow state into package-ready MODFLOW inputs.
   * - Model assembly and execution
     - ``hydromodpy.solver.modflow6.modflow6`` owns concrete FloPy model
       construction and execution.
   * - Diagnostics and postprocess
     - ``hydromodpy.solver.modflow6.diagnostics`` and
       ``hydromodpy.solver.modflow6.postprocess`` read and check raw outputs.
   * - Output extraction
     - ``hydromodpy.solver.modflow6.extractors.flow`` ingests flow outputs into
       the result/catalog layer.

Transport Coupling
------------------

``flow/modflow6`` is the required upstream provider for
``transport/modflow6gwt``.

Related Pages
-------------

- :doc:`../../modflow6-architecture-notes`
- :doc:`transport-coupling`
- :doc:`../../../../scientific/solvers/flow/modflow/modflow6`
