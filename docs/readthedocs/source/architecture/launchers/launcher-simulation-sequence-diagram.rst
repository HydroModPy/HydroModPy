Launcher To Simulation Sequence
===============================

Scope
-----

This diagram documents the runtime path from launcher entry-point to solver
execution for the simulation-plan workflow.

It focuses on:

- plan creation in ``SimulationPlanner``,
- setup/data phase preparation in ``HydroModPyLauncher``,
- ordered execution of ``ProcessRun`` entries in ``SimulationRunner``,
- the handoff from process runtimes to concrete solver wrappers.

Diagram source
--------------

.. uml:: diagrams/launcher_simulation_orchestration_sequence.wsd

.. literalinclude:: diagrams/launcher_simulation_orchestration_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - launcher to simulation sequence

Notes
-----

- The launcher builds the plan before any solver work starts, so orchestration
  errors (duplicate ids, missing dependencies, unsupported bindings) fail early.
- ``_run_setup()`` and ``_run_data()`` prepare shared objects once; the runner
  then reuses them across all planned runs.
- Flow runs publish their produced model into ``models_by_run_id``. Transport
  runs retrieve that exact upstream model through ``depends_on``.
- The sequence stays backend-agnostic at the orchestration level: solver
  selection changes the wrapper class, not the launcher contract.
