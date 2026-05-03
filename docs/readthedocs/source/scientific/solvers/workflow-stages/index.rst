Workflow-Stage Adapters
=======================

This section groups registry entries that use the same process/solver planning
model but are not groundwater governing-equation solvers.

The hierarchy is:

1. process: ``postprocess`` or ``display``,
2. solver type: analysis/export adapter or presentation adapter.

Current Stage Types
-------------------

.. list-table::
   :header-rows: 1
   :widths: 24 28 48

   * - Process
     - Solver names
     - Role
   * - ``postprocess``
     - ``timeseries``, ``netcdf``
     - Derive analysis products and exports after solver execution.
   * - ``display``
     - ``flow``, ``transport``
     - Generate visual or report-ready artifacts from stored outputs.

.. toctree::
   :maxdepth: 2

   postprocess-adapters
   display-adapters

Status
------

The current entries are registry stubs. They are documented here because they
define the intended extension pattern: future workflow stages should be
classified by process, then by adapter type, just like numerical solvers.

Related Pages
-------------

- :doc:`../process-solver-taxonomy`
- :doc:`../../../architecture/solver/workflow-stages/index`
