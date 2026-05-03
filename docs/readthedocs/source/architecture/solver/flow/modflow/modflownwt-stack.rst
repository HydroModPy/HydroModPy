MODFLOW-NWT Flow Stack
======================

This page structures the code path for ``flow/modflownwt``.

Detailed backend notes remain in :doc:`../../modflownwt-architecture-notes`.

Code Reading Layers
-------------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Layer
     - Main paths and responsibility
   * - Registry adapter
     - ``hydromodpy.solver.modflow_nwt.adapters.flow`` declares the
       ``flow/modflownwt`` adapter.
   * - Config
     - ``hydromodpy.solver.modflow_nwt.modflow.nwt_config`` validates the
       ``[modflownwt.*]`` configuration tree.
   * - Translation
     - ``hydromodpy.solver.modflow_nwt.modflow.flow_to_modflow_adapter``
       translates runtime flow state into package-ready MODFLOW-NWT inputs.
   * - Model assembly and execution
     - ``hydromodpy.solver.modflow_nwt.modflow.nwt_solver`` owns concrete
       MODFLOW-NWT model construction and execution.
   * - Postprocess
     - ``hydromodpy.solver.modflow_nwt.modflow.postprocess`` reads and prepares
       backend outputs.
   * - Output extraction
     - ``hydromodpy.solver.modflow_nwt.extractors.flow`` ingests flow outputs
       into the result/catalog layer.
   * - Colocated transport ecosystem
     - ``hydromodpy.solver.modflow_nwt.modpath`` and
       ``hydromodpy.solver.modflow_nwt.mt3dms`` stay next to this flow backend.

Transport Coupling
------------------

``flow/modflownwt`` is the required upstream provider for
``transport/modpath`` and ``transport/mt3dms``.

Related Pages
-------------

- :doc:`../../modflownwt-architecture-notes`
- :doc:`transport-coupling`
- :doc:`../../../../scientific/solvers/flow/modflow/modflownwt`
