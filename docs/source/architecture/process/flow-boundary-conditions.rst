.. _flow-boundary-conditions-runtime-contract:

Flow Boundary Conditions
========================

Scope
-----

This page documents the runtime contract used for groundwater flow boundary
conditions.

The public TOML grammar remains under ``[flow.bc]`` and ``flow.active_bc``.
The runtime architecture now adds one explicit middle layer:

- ``FlowBoundaryConditionConfig`` stores one normalized boundary payload.
- ``FLOW_BOUNDARY_DEFINITIONS`` is the canonical registry of known boundary
  identifiers and backend capabilities.
- ``BoundaryConditionBundle`` groups configured and active boundaries for
  solver adapters.

This keeps the user-facing contract stable while making backend support and
future extensions easier to inspect.

Quick Access
------------

.. list-table::
   :header-rows: 1
   :widths: 28 38 34

   * - Question
     - Primary code location
     - What to look for
   * - Which ids can appear in ``flow.active_bc``?
     - ``hydromodpy.physics.flow.FLOW_BOUNDARY_DEFINITIONS``
     - Canonical id, family, support kind, and backend support.
   * - How is TOML normalized?
     - ``hydromodpy.physics.flow.boundary_conditions_config``
     - Accepted ``[flow.bc]`` shapes before typed validation.
   * - What does a solver adapter consume?
     - ``hydromodpy.physics.flow.BoundaryConditionBundle``
     - Configured boundary payloads plus explicit active ids.
   * - Where is MF6 assembly handled?
     - ``hydromodpy.solver.modflow6.builders.boundary_conditions``
     - ``CHD`` and ``DRN`` package payload construction.
   * - Where is MODFLOW-NWT assembly handled?
     - ``hydromodpy.solver.modflow_nwt.nwt._chd_payloads``
     - ``BAS`` / ``CHD`` boundary-head payloads.
   * - Where is Boussinesq assembly handled?
     - ``hydromodpy.solver.boussinesq.forcing``
     - Prescribed-head support and drainage operator resolution.
   * - Which tests cover the registry contract?
     - ``tests/unit/physics/test_flow_boundary_condition_registry.py``
     - Registry ids, backend support, bundle behavior, and Flow integration.

Code Map
--------

- ``hydromodpy.physics.flow.boundary_conditions``:
  normalized boundary-condition payload model.
- ``hydromodpy.physics.flow.boundary_conditions_config``:
  TOML shape normalization.
- ``hydromodpy.physics.flow.boundary_condition_registry``:
  canonical boundary registry and runtime bundle helpers.
- ``hydromodpy.physics.flow.flow``:
  runtime ``Flow`` object storing the boundary bundle.
- ``hydromodpy.solver.modflow6.builders.boundary_conditions``:
  MF6 ``CHD`` / ``DRN`` translation.
- ``hydromodpy.solver.modflow_nwt.nwt._chd_payloads`` and
  ``_well_drainage_payloads``:
  MODFLOW-NWT ``BAS`` / ``CHD`` / ``DRN`` translation.
- ``hydromodpy.solver.boussinesq.forcing``:
  prescribed-head and drainage operator resolution.

Current Boundary Ids
--------------------

.. list-table::
   :header-rows: 1
   :widths: 18 24 22 36

   * - Id
     - Family
     - Support kind
     - Backend package/operator
   * - ``west_side``
     - ``dirichlet``
     - ``side``
     - MF6 ``CHD``; NWT ``BAS/CHD``; Boussinesq ``prescribed_head``.
   * - ``east_side``
     - ``dirichlet``
     - ``side``
     - MF6 ``CHD``; NWT ``BAS/CHD``; Boussinesq ``prescribed_head``.
   * - ``north_side``
     - ``dirichlet``
     - ``side``
     - MF6 ``CHD``; NWT ``BAS/CHD``; Boussinesq ``prescribed_head``.
   * - ``south_side``
     - ``dirichlet``
     - ``side``
     - MF6 ``CHD``; NWT ``BAS/CHD``; Boussinesq ``prescribed_head``.
   * - ``stream``
     - ``dirichlet``
     - ``stream``
     - MF6 ``CHD``; Boussinesq ``prescribed_head``. Not implemented for NWT.
   * - ``ocean``
     - ``dirichlet``
     - ``ocean_stage``
     - MF6 ``CHD``; NWT ``BAS/CHD``; Boussinesq ``prescribed_head``.
   * - ``drainage``
     - ``head_dependent_exchange``
     - ``top``
     - MF6 ``DRN``; NWT ``DRN``; Boussinesq ``top_drainage``.

Diagram 1: Component View
-------------------------

.. uml:: diagrams/flow_boundary_conditions_components.wsd

.. literalinclude:: diagrams/flow_boundary_conditions_components.wsd
   :language: text
   :caption: PlantUML (.wsd) source - flow boundary-condition component view

Diagram 2: Runtime Sequence
---------------------------

.. uml:: diagrams/flow_boundary_conditions_sequence.wsd

.. literalinclude:: diagrams/flow_boundary_conditions_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - flow boundary-condition runtime sequence

Notes
-----

- ``active_bc`` remains explicit: declared boundaries are not assembled unless
  their id is active.
- The registry is deliberately small. It describes the current canonical ids
  and backend support; it does not hide backend-specific package semantics.
- Adding a new canonical boundary should start in the registry, then each
  backend should either implement it or explicitly leave it unsupported.

Related Diagrams
----------------

See :doc:`process-architecture` for the process config class, runtime class, and runtime-to-solver sequence diagrams.
