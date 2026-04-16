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
- legacy edge-based boundary diagnostics are rebuilt explicitly in one adapter
  layer instead of driving the solve path;
- the method and engine taxonomy is explicit;
- runtime state construction is centralized;
- the process-to-solver contract is explicit.

The main remaining simplification targets are:

- continue shrinking the legacy ``imposed_head_*`` compatibility surface
  toward an export-only adapter;
- factor common runtime bookkeeping now repeated across local, SciPy and PETSc
  backends.

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
- ``imposed_head_*`` still appears in the package only because a legacy
  compatibility layer still exists for exports, plots and regression tests.
- The diagrams deliberately separate:

  - hydrological problem definition;
  - method and formulation selection;
  - execution-engine selection;
  - nonlinear runtime execution;
  - export and diagnostics.
