MODFLOW 6 GWT Transport Stack
=============================

This page documents the architecture stack for ``transport/modflow6gwt``.

Stack
-----

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Layer
     - Role
   * - ``Modflow6GwtTransportAdapter``
     - Process/solver adapter for ``transport/modflow6gwt``.
   * - ``requires = (("flow", "modflow6"),)``
     - Ensures an earlier MODFLOW 6 flow model exists.
   * - ``hydromodpy.solver.modflow6.modflow6.Modflow6Transport``
     - Concrete MODFLOW 6 GWT model wrapper.
   * - ``hydromodpy.solver.modflow6.extractors.transport``
     - MODFLOW 6 GWT concentration output ingestion into the result/catalog
       layer.

Execution Shape
---------------

The adapter:

- resolves the upstream MODFLOW 6 flow model;
- constructs ``Modflow6Transport`` with domain, transport config, flow model,
  and output suffix;
- runs ``pre_processing()``;
- runs ``processing(write_model=True, run_model=True, verbose=True)``;
- returns the MODFLOW 6 GWT output directory.

Related Scientific Page
-----------------------

- :doc:`../../../scientific/solvers/transport/concentration-transport/modflow6gwt`
