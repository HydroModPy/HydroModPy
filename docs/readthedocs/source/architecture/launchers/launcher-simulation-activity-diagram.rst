Launcher To Simulation Activity
===============================

Scope
-----

This diagram documents the control-flow view of the launcher-driven
simulation-plan workflow.

It focuses on:

- early validation and plan building,
- one-time setup and data preparation,
- sequential execution of resolved ``ProcessRun`` entries,
- the flow-versus-transport execution branches,
- publication of produced models back into the launcher state.

Diagram source
--------------

.. uml:: diagrams/launcher_simulation_orchestration_activity.wsd

.. literalinclude:: diagrams/launcher_simulation_orchestration_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - launcher to simulation activity

Notes
-----

- ``setup`` and ``data`` happen once per launcher session, regardless of how
  many concrete runs the plan contains.
- ``SimulationRunner`` never recomputes dependencies. It only consumes the
  already-resolved ``SimulationPlan``.
- ``models_by_run_id`` is the explicit handoff point between earlier flow runs
  and later transport runs.
- Process callbacks are opened and closed per contiguous process-family block,
  not per individual solver call.
