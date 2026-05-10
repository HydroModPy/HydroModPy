Flow Solvers
============

This section groups solver documentation for the ``flow`` process.

Use it when the main output of interest is hydraulic head, water-table depth,
groundwater storage, recharge response, or flow-budget terms.

The hierarchy is:

1. process: ``flow``,
2. solver type or family: MODFLOW family, Boussinesq family, or shared
   numerical support used by flow solvers.

Current Flow Solver Families
----------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 30 46

   * - Family
     - Solver names
     - Role
   * - MODFLOW family
     - ``modflownwt``, ``modflow6``
     - Structured-grid and MODFLOW 6 groundwater-flow backends. Internal
       structure: :doc:`MODFLOW 6 <modflow/modflow6>` and
       :doc:`MODFLOW-NWT <modflow/modflownwt>` pages, plus the
       cross-cutting comparison, worked cases, and transport coupling.
   * - Boussinesq family
     - ``boussinesq``
     - In-house shallow-groundwater finite-volume backend. Consolidated theory
       page: :doc:`../../boussinesq`.
   * - Shared flow numerics
     - Applies to several flow solvers.
     - See :doc:`../mesh-and-discretization-strategies`,
       :doc:`../vertical-representation-and-storage-assumptions`,
       and :doc:`../field-to-cell-parameter-transfer`.

.. toctree::
   :maxdepth: 1

   modflow-family

Related Pages
-------------

- :doc:`../../boussinesq`
- :doc:`../solver-capability-matrix`
- :doc:`../../../user_guide/solvers`
- :doc:`../../../architecture/process/flow-boundary-conditions`
- :doc:`../../../architecture/solver/index`
