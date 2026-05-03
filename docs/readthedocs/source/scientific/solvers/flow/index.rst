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
       structure: common MODFLOW part, :doc:`MODFLOW 6 version
       <modflow/modflow6-version/index>`, and :doc:`MODFLOW-NWT version
       <modflow/modflownwt-version/index>`.
   * - Boussinesq family
     - ``boussinesq``
     - In-house shallow-groundwater finite-volume backend. Internal
       structure: :doc:`boussinesq/index`.
   * - Shared flow numerics
     - Applies to several flow solvers.
     - Mesh, discretization, vertical representation, and field-to-cell
       parameter transfer notes.

.. toctree::
   :maxdepth: 2

   modflow-family
   boussinesq-family
   shared-flow-numerics

Related Pages
-------------

- :doc:`../solver-capability-matrix`
- :doc:`../../../user_guide/solver-process-map`
- :doc:`../../../architecture/solver/flow/index`
