Simulation Architecture
=======================

This section documents the simulation orchestration layer implemented in
``hydromodpy.simulation``.

For runtime views that include the top-level launcher, see
:doc:`../launchers/launcher-simulation-sequence-diagram` and
:doc:`../launchers/launcher-simulation-activity-diagram`.

Use this section when you want:

- the static orchestration model around planner, runner, and adapters,
- the execution-time cycle inside the simulation layer,
- one code-oriented walkthrough from TOML config to solver outputs.

.. toctree::
   :maxdepth: 2

   toml-to-solver-walkthrough
   launcher-simulation-class-diagram
   simulation-time-cycle-diagrams
