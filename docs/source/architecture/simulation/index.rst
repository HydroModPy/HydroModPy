Simulation Architecture
=======================

This section documents the simulation orchestration layer implemented in
``hydromodpy.simulation``. The public entry point is the ``Project``
facade in ``hydromodpy/project.py``, instantiated by the CLI command
``hmp run`` or by user Python code.

Use this section when you want:

- the static orchestration model around planner, runner, and adapters,
- the execution-time cycle inside the simulation layer,
- one code-oriented walkthrough from TOML config to solver outputs.

.. toctree::
   :maxdepth: 2

   toml-to-solver-walkthrough
   simulation-orchestration-class-diagram
   simulation-time-cycle-diagrams
