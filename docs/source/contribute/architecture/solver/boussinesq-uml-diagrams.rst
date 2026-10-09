Boussinesq solver diagrams
==========================

Scope
-----

These diagrams document the software architecture of
``hydromodpy.solver.boussinesq``.

They are intentionally limited to four views:

- package context;
- core classes;
- process-to-backend runtime sequence;
- transient-step activity.

The mathematical derivation lives in the theory notes
(:doc:`/theory/boussinesq`). These pages cover structure, responsibilities and
handoff boundaries. ``hydromodpy/solver/boussinesq/README.md`` is the map of the package.

Package context
---------------

.. uml:: diagrams/boussinesq_context.wsd

Core classes
------------

.. uml:: diagrams/boussinesq_core_classes.wsd

Process to backend sequence
---------------------------

.. uml:: diagrams/boussinesq_process_to_backend_sequence.wsd

Transient step activity
-----------------------

.. uml:: diagrams/boussinesq_transient_step_activity.wsd

Notes
-----

- The canonical runtime path uses ``prescribed_head_m_by_cell``.
- The orchestration is split as follows:

  - ``boussinesq.py`` for top-level coordination;
  - ``drivers/steady.py`` and ``drivers/transient.py`` for solve execution, and
    ``drivers/forcing.py`` for shared boundary and drainage preparation;
  - ``solver_contract.py`` for process-to-runtime normalization;
  - ``runtime_selection.py`` for the method and engine resolution, and
    ``runtime_summary.py`` for runtime-summary shaping;
  - ``forcing_resolution.py`` plus ``forcing/`` for process-to-array mapping;
  - ``assembly/`` for the residual and the fluxes, and ``jacobian/`` for the
    linearization;
  - ``runtimes/`` for the execution engines.

- The diagrams separate the hydrological problem definition, the method and
  formulation selection, the engine selection, the nonlinear runtime execution, and the
  export and diagnostics.
