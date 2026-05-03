MT3DMS Transport Stack
======================

This page documents the architecture stack for ``transport/mt3dms``.

Stack
-----

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Layer
     - Role
   * - ``Mt3dmsTransportAdapter``
     - Process/solver adapter for ``transport/mt3dms``.
   * - ``requires = (("flow", "modflownwt"),)``
     - Ensures an earlier MODFLOW-NWT flow model exists.
   * - ``hydromodpy.solver.modflow_nwt.mt3dms.Mt3dms``
     - Concrete MT3DMS model wrapper.
   * - ``hydromodpy.solver.modflow_nwt.extractors.mt3dms``
     - Concentration output ingestion into the result/catalog layer.

Execution Shape
---------------

The adapter:

- resolves the upstream MODFLOW-NWT flow model;
- constructs ``Mt3dms`` with domain, transport config, flow model, and output
  suffix;
- runs ``pre_processing()``;
- runs ``processing(write_model=True, run_model=True, verbose=True)``;
- returns the MT3DMS output directory.

Related Scientific Page
-----------------------

- :doc:`../../../scientific/solvers/transport/concentration-transport/mt3dms`
