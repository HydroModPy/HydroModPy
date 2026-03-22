Solver Architecture
===================

This section documents solver-level notes implemented in
``hydromodpy.solver``.

It focuses on:

- backend-specific mathematical formulations,
- nonlinear runtime strategies,
- mappings between equations and implementation points.

For higher-level runtime handoffs from process objects to solver wrappers, see
:doc:`../process/process-runtime-to-solver-sequence-diagram`.

.. toctree::
   :maxdepth: 2

   boussinesq-mathematical-notes
