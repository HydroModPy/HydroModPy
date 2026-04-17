Launcher To Simulation Class Diagram
====================================

Scope
-----

This diagram documents the static orchestration layer that connects the
launcher to simulation planning and solver execution.

It focuses on:

- ``HydroModPyLauncher`` as the top-level orchestrator,
- ``SimulationPlanner`` and the immutable ``SimulationPlan`` / ``ProcessRun``
  objects it builds,
- ``SimulationRunner`` as the runtime dispatcher,
- the launcher-owned runtime state exchanged between orchestration phases,
- process runtimes (``Flow`` / ``Transport``) and the solver wrappers they feed.

Code map
--------

- ``launchers/process_simulation/launcher.py``:
  top-level orchestration and mutable runtime state.
- ``hydromodpy/simulation/planning/planner.py`` and ``plan.py``:
  planner boundary and immutable planning result.
- ``hydromodpy/simulation/execution/runner.py``:
  runtime dispatcher over ``ProcessRun`` entries.
- ``hydromodpy/process/`` and ``hydromodpy/solver/``:
  downstream runtime objects and concrete backends.

Recommended reading path
------------------------

1. ``launchers/process_simulation/launcher.py``
2. ``hydromodpy/simulation/planning/planner.py``
3. ``hydromodpy/simulation/planning/plan.py``
4. ``hydromodpy/simulation/execution/runner.py``
5. ``hydromodpy/process/flow/flow.py`` or ``transport/transport.py``

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
- The mutable execution state stays owned by the launcher, which gradually
  accumulates runtime objects and produced models across phases.
- ``SimulationRunner`` does not decide the schedule. It only dispatches the
  already-resolved ``ProcessRun`` entries to the right solver backend.
- Solver wrappers are selected from ``ProcessRun.solver``, which keeps solver
  choice explicit and traceable in the plan itself.
- For dynamic views of the same orchestration path, see
  :doc:`../launchers/launcher-simulation-sequence-diagram` and
  :doc:`../launchers/launcher-simulation-activity-diagram`.

Related diagrams
----------------

- :doc:`../launchers/launcher-simulation-sequence-diagram`
- :doc:`../launchers/launcher-simulation-activity-diagram`
- :doc:`toml-to-solver-walkthrough`
