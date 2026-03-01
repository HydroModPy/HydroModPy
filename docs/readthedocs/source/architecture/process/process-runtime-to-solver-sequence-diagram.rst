Process Runtime To Solver Sequence
==================================

Scope
-----

This diagram shows the main runtime handoff from process objects to solver
backends.

It focuses on:

- runtime construction of ``Flow`` from validated config,
- adapter-level transformation into solver payloads,
- backend-specific execution path (MODFLOW-NWT or MODFLOW 6).

Diagram source
--------------

.. literalinclude:: diagrams/runtime_to_solver_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - process runtime to solver sequence

Notes
-----

- The sequence is logical and backend-agnostic at the high level.
- Payload conversion is explicitly separated from process runtime state.
- Solver wrappers remain consumers of already-normalized process data.
- For detailed DIS payload semantics, see
  ``docs/developers/modflow_discretization_contract.md``.
