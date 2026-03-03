Launcher To Simulation Class Diagram
===================================

Scope
-----

This diagram documents the static orchestration layer that connects the
launcher to simulation planning and solver execution.

It focuses on:

- ``HydroModPyLauncher`` as the top-level orchestrator,
- ``SimulationPlanner`` and the immutable ``SimulationPlan`` / ``ProcessRun``
  objects it builds,
- ``SimulationRunner`` as the runtime dispatcher,
- ``RunResult`` as the shared mutable state exchanged between launcher phases,
- process runtimes (``Flow`` / ``Transport``) and the solver wrappers they feed.

Diagram source
--------------

.. uml:: diagrams/launcher_simulation_orchestration_class.wsd

.. literalinclude:: diagrams/launcher_simulation_orchestration_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - launcher to simulation class diagram

Notes
-----

- ``SimulationPlan`` is intentionally immutable: the planner produces it once,
  then the runner consumes it without rewriting scheduling decisions.
- ``RunResult`` is the opposite: it is the mutable execution state that
  gradually accumulates runtime objects and produced models.
- ``SimulationRunner`` does not decide the schedule. It only dispatches the
  already-resolved ``ProcessRun`` entries to the right solver backend.
- Solver wrappers are selected from ``ProcessRun.solver``, which keeps solver
  choice explicit and traceable in the plan itself.
