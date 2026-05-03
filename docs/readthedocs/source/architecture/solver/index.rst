Solver Architecture
===================

This section documents software architecture for solver wrappers and backend
orchestration.

The navigation follows the same two-level hierarchy as the scientific solver
pages:

1. **process**: ``flow``, ``transport``, or workflow-stage processes;
2. **solver type or family**: MODFLOW, Boussinesq, transport adapters,
   postprocess adapters, or display adapters.

Use it when you want:

- the process/solver registry behind ``flow``, ``transport``,
  ``postprocess``, and ``display`` stages,
- the backend-specific code layout of ``boussinesq``, ``modflow6``,
  ``modflownwt``, ``modpath``, ``mt3dms``, and ``modflow6gwt``,
- the split between generic simulation adapters and concrete solver or
  workflow-stage packages,
- the current mesh contract supported by each flow backend.

Scientific derivations and mathematical solver notes live under
:doc:`../../scientific/solvers/index`.

.. tab-set::

   .. tab-item:: Registry

      The canonical runtime key is ``(process_type, solver_name)``. This
      supports ``flow`` and ``transport`` today and generalizes to
      ``postprocess`` and ``display`` stages. See
      :doc:`process-solver-registry`.

   .. tab-item:: Flow

      Flow solver architecture is grouped by MODFLOW family and Boussinesq
      family. See :doc:`flow/index`.

   .. tab-item:: Transport

      Transport solver architecture is grouped around MODFLOW-linked
      particle-tracking and concentration adapters. See
      :doc:`transport/index`.

   .. tab-item:: Workflow stages

      Postprocess and display entries are registry-backed extension points,
      not groundwater equation solvers. See :doc:`workflow-stages/index`.

.. toctree::
   :maxdepth: 2

   process-solver-registry
   Flow <flow/index>
   Transport <transport/index>
   Workflow stages <workflow-stages/index>
