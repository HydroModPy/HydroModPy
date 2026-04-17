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

Code map
--------

- ``launchers/process_simulation/launcher.py``:
  session lifecycle around setup, data, and execution.
- ``hydromodpy/simulation/planning/plan.py``:
  immutable run schedule consumed at execution time.
- ``hydromodpy/simulation/execution/runner.py``:
  ordered runtime dispatch and callback lifecycle.
- ``hydromodpy/simulation/adapters/registry.py``:
  backend-resolution boundary.

Recommended reading path
------------------------

1. ``launchers/process_simulation/launcher.py``
2. ``hydromodpy/simulation/planning/plan.py``
3. ``hydromodpy/simulation/execution/runner.py``
4. ``hydromodpy/simulation/adapters/registry.py``

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

Related diagrams
----------------

- :doc:`launcher-simulation-sequence-diagram`
- :doc:`../simulation/launcher-simulation-class-diagram`
- :doc:`../process/process-runtime-to-solver-sequence-diagram`
