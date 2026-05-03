Postprocess Adapters
====================

``postprocess`` entries represent analysis or export stages that run after one
or more simulation outputs exist.

Current Entries
---------------

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Process/solver pair
     - Intended role
     - Current status
   * - ``postprocess/timeseries``
     - Build time-series products from stored flow or transport outputs.
     - Registry stub.
   * - ``postprocess/netcdf``
     - Export catalog products to NetCDF-oriented deliverables.
     - Registry stub.

Documentation Rule
------------------

When these adapters become concrete, document them like solver families:

1. required upstream outputs,
2. input parameters,
3. produced catalog entries or files,
4. examples,
5. limitations and maturity status.

Related Architecture
--------------------

- :doc:`../../../architecture/solver/workflow-stages/postprocess-display-adapters`
- :doc:`../../../architecture/solver/process-solver-registry`
