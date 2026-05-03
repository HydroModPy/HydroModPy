Display Adapters
================

``display`` entries represent presentation stages that generate figures,
maps, or report-ready artifacts from simulation outputs.

Current Entries
---------------

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Process/solver pair
     - Intended role
     - Current status
   * - ``display/flow``
     - Generate flow-oriented figures from stored flow outputs.
     - Registry stub.
   * - ``display/transport``
     - Generate transport-oriented figures from stored transport outputs.
     - Registry stub.

Documentation Rule
------------------

When these adapters become concrete, document them by:

1. required upstream catalog entries,
2. figure or report parameters,
3. output paths and naming conventions,
4. examples,
5. limitations and maturity status.

Related Architecture
--------------------

- :doc:`../../../architecture/solver/workflow-stages/postprocess-display-adapters`
- :doc:`../../../architecture/solver/process-solver-registry`
