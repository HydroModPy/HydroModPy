Simulation Orchestration Class Diagram
======================================

Scope
-----

This diagram documents the static orchestration layer that connects the
public ``Project`` facade to simulation planning and solver execution.

It focuses on:

- ``Project`` as the top-level orchestrator that the CLI (``hmp run``)
  and Python users instantiate,
- ``SimulationPlanner`` and the immutable ``SimulationPlan`` /
  ``ProcessRun`` objects it builds,
- ``SimulationRunner`` as the runtime dispatcher,
- the project-owned runtime state exchanged between orchestration
  phases,
- process runtimes (``Flow``, ``Transport``) and the solver adapters
  they feed.

Code map
--------

- ``hydromodpy/project.py``:
  the public ``Project`` facade. Holds the mutable runtime state and
  wires the pipeline phases.
- ``hydromodpy/_cli/commands/run.py`` and
  ``hydromodpy/_cli/workflows.py``:
  the ``hmp run <toml>`` entry point. Loads the TOML, builds a
  ``HydroModPyConfig``, and delegates to ``Project``.
- ``hydromodpy/simulation/planning/planner.py`` and ``plan.py``:
  planner boundary and immutable planning result.
- ``hydromodpy/simulation/execution/runner.py``:
  runtime dispatcher over ``ProcessRun`` entries.
- ``hydromodpy/physics/`` and ``hydromodpy/solver/``:
  downstream runtime objects and concrete backends.

Recommended reading path
------------------------

1. ``hydromodpy/_cli/commands/run.py``
2. ``hydromodpy/project.py``
3. ``hydromodpy/simulation/planning/planner.py``
4. ``hydromodpy/simulation/planning/plan.py``
5. ``hydromodpy/simulation/execution/runner.py``
6. ``hydromodpy/physics/process/flow/flow.py`` or
   ``transport/transport.py``

Diagram source
--------------

.. uml:: diagrams/simulation_orchestration_class.wsd

.. literalinclude:: diagrams/simulation_orchestration_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - simulation orchestration class diagram

Notes
-----

- ``SimulationPlan`` is intentionally immutable. The planner produces it
  once, then the runner consumes it without rewriting scheduling
  decisions.
- The mutable execution state stays owned by ``Project``, which
  gradually accumulates runtime objects and produced models across
  phases (``setup_workspace``, ``build_geographic``, ``load_data``,
  ``build_mesh``, ``prepare``, ``execute``, ``ingest``, ``render``).
- ``SimulationRunner`` does not decide the schedule. It only dispatches
  the already-resolved ``ProcessRun`` entries to the right solver
  adapter.
- Solver adapters are selected from ``ProcessRun.solver``, which keeps
  solver choice explicit and traceable in the plan itself.

Related diagrams
----------------

- :doc:`toml-to-solver-walkthrough`
- :doc:`simulation-time-cycle-diagrams`
