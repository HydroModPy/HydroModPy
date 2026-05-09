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

- :doc:`process-config-class-diagram`
- :doc:`process-runtime-class-diagram`
- :doc:`process-runtime-to-solver-sequence-diagram`
