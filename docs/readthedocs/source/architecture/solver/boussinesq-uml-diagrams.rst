Boussinesq Solver UML Diagrams
==============================

Scope
-----

These diagrams document the software architecture of
``hydromodpy.solver.boussinesq``.

They are intentionally limited to four views:

- package context;
- core classes;
- process-to-backend runtime sequence;
- transient-step activity.

This is the right level for this package. The mathematical derivation already
lives in the scientific notes, so the architecture documentation should focus
on structure, responsibilities and handoff boundaries.

Simplification Review
---------------------

The current Boussinesq package is already much clearer than before:

- the canonical Dirichlet concept is now prescribed boundary cells;
- the active driver/runtime path now uses that prescribed-cell representation;
- edge-based boundary diagnostics are rebuilt explicitly in
  ``boundary_flux_reconstruction.py`` instead of driving the solve path;
- the method and engine taxonomy is explicit;
- runtime state construction is centralized;
- steady and transient orchestration have been extracted out of the main
  driver;
- process-to-runtime normalization is extracted into ``solver_contract.py``;
- forcing resolution is now split into a stable facade plus specialized
  submodules;
- shared boundary/ocean/drainage preparation is isolated in
  ``driver_forcing.py``;
- the public assembly layer is now one facade over dedicated internal modules
  for inputs, fluxes, surface closures and residual builders;
- the public semianalytic Jacobian layer is now one facade over dedicated
  internal modules for common helpers and sparse triplet builders;
- runtime summary shaping and common runtime-result packaging are extracted
  into dedicated helpers;
- the process-to-solver contract is explicit.

The main remaining simplification targets are:

- keep the driver thin and avoid regrowing orchestration logic in
  ``boussinesq.py``;
- keep future cleanups focused on ``assembly_residuals.py``,
  ``assembly_fluxes.py``, ``jacobian_operator_triplets.py`` and
  ``jacobian_partition_triplets.py``, which are now the main size hotspots;
- continue factoring small pieces of common runtime bookkeeping only when the
  resulting helper stays clearer than the duplicated code.

Diagram 1: Package Context
--------------------------

.. uml:: diagrams/boussinesq_context.wsd

.. literalinclude:: diagrams/boussinesq_context.wsd
   :language: text
   :caption: PlantUML (.wsd) source - Boussinesq package context

Diagram 2: Core Classes
-----------------------

.. uml:: diagrams/boussinesq_core_classes.wsd

.. literalinclude:: diagrams/boussinesq_core_classes.wsd
   :language: text
   :caption: PlantUML (.wsd) source - Boussinesq core classes

Diagram 3: Process To Backend Sequence
--------------------------------------

.. uml:: diagrams/boussinesq_process_to_backend_sequence.wsd

.. literalinclude:: diagrams/boussinesq_process_to_backend_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - Boussinesq process to backend sequence

Diagram 4: Transient Step Activity
----------------------------------

.. uml:: diagrams/boussinesq_transient_step_activity.wsd

.. literalinclude:: diagrams/boussinesq_transient_step_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - Boussinesq transient step activity

Notes
-----

- The canonical runtime path is now based on ``prescribed_head_m_by_cell``.
- The main orchestration split is now:

  - ``boussinesq.py`` for top-level coordination;
  - ``driver_steady.py`` and ``driver_transient.py`` for solve execution;
  - ``solver_contract.py`` for process-to-runtime normalization;
  - ``runtime_summary.py`` for runtime-summary shaping;
  - ``forcing_resolution.py`` plus ``forcing/`` for process-to-array mapping;
  - ``driver_forcing.py`` for shared boundary and drainage preparation;
  - ``jacobian_semianalytic.py`` plus its internal triplet modules for the
    semianalytic linearization layer.
- The diagrams deliberately separate:

  - hydrological problem definition;
  - method and formulation selection;
  - execution-engine selection;
  - nonlinear runtime execution;
  - export and diagnostics.
