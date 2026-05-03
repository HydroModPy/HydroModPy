MODPATH Transport Stack
=======================

This page documents the architecture stack for ``transport/modpath``.

Stack
-----

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Layer
     - Role
   * - ``ModpathTransportAdapter``
     - Process/solver adapter for ``transport/modpath``.
   * - ``requires = (("flow", "modflownwt"),)``
     - Ensures an earlier MODFLOW-NWT flow model exists.
   * - ``hydromodpy.solver.modflow_nwt.modpath.Modpath``
     - Concrete MODPATH model wrapper.
   * - ``hydromodpy.solver.modflow_nwt.extractors.modpath``
     - Pathline and endpoint ingestion into the result/catalog layer.

Execution Shape
---------------

The adapter:

- resolves the upstream MODFLOW-NWT flow model;
- constructs ``Modpath`` with domain, transport config, and flow model;
- runs ``pre_processing()``;
- runs ``processing(write_model=True, run_model=True)``;
- returns the MODPATH output directory.

Related Scientific Page
-----------------------

- :doc:`../../../scientific/solvers/transport/particle-tracking/modpath`
