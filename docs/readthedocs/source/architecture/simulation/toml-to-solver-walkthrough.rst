TOML To Solver Walkthrough
==========================

Scope
-----

This page is a code-oriented walkthrough of the main execution chain from one
launcher TOML file to concrete solver outputs.

It complements the UML views by answering a more practical question:

"Which file runs next when HydroModPy executes one simulation config?"

End-to-end chain
----------------

For the standard simulation workflow, the runtime path is:

1. ``launchers/process_simulation/launcher.py``
2. ``HydroModPyConfig.from_toml(...)`` plus launcher-side raw TOML loading
3. setup, data, and optional mesh preparation in the launcher
4. ``hydromodpy/simulation/planning/planner.py``
5. ``hydromodpy/simulation/execution/runner.py``
6. one registered adapter under ``hydromodpy/simulation/adapters/``
7. one concrete solver package under ``hydromodpy/solver/``
8. solver-side postprocess and launcher artifact persistence

Step 1: config loading and launcher bootstrap
---------------------------------------------

``HydroModPyLauncher`` owns the top-level bootstrap:

- it validates the typed config tree,
- it keeps the raw TOML for optional launcher-managed sections,
- it resolves the simulation time window,
- it derives the effective data-loading plan,
- it prepares optional runtime mesh inputs.

This is still launcher code because these concerns mix paths, workspaces,
optional top-level sections, and runtime state assembly.

Step 2: setup, data, and optional mesh phases
---------------------------------------------

Before any solver run is planned, the launcher prepares the shared runtime
context:

- setup creates workspace, geographic, domain, and initial process-facing
  state,
- data loading resolves the required forcing and observation families,
- optional mesh phases either build a runtime Gmsh mesh or load one from disk.

Those phases run once per launcher session, not once per solver.

Step 3: declarative simulation config to executable plan
--------------------------------------------------------

``SimulationPlanner`` turns the declarative ``[simulation]`` block into one
ordered immutable ``SimulationPlan``.

Its main responsibilities are:

- preserve user-declared process order,
- expand one process entry into one concrete ``ProcessRun`` per solver,
- bind each run to earlier compatible providers using the static compatibility
  matrix,
- reject invalid or ambiguous execution graphs early.

At this point the result is still only a plan, not execution.

Step 4: process-family runtime execution
----------------------------------------

``SimulationRunner`` walks the resolved plan in order.

It owns:

- process-family transitions,
- process-context materialization (`Flow`, `Transport`),
- dependency lookup through ``models_by_run_id``,
- adapter dispatch for each ``ProcessRun``.

It does not know solver-specific API details.

Step 5: adapter boundary
------------------------

The adapter layer is the narrow bridge between generic simulation orchestration
and concrete solver APIs.

Examples:

- ``simulation/adapters/flow/modflownwt.py``
- ``simulation/adapters/flow/modflow6.py``
- ``simulation/adapters/flow/boussinesq.py``
- ``simulation/adapters/transport/mt3dms.py``
- ``simulation/adapters/transport/modflow6gwt.py``

For MODFLOW-family flow runs, backend-specific adapters stay intentionally
thin, while the shared execution lifecycle lives in
``simulation/adapters/flow/modflow_common.py``.

Step 6: concrete solver packages
--------------------------------

Once the adapter has built the concrete solver object, execution moves into one
package under ``hydromodpy/solver``.

Typical responsibilities there are:

- solver-specific preprocessing,
- package or matrix assembly,
- binary execution or in-process numerical solve,
- postprocessing of raw outputs into HydroModPy-facing payloads.

Current flow backends are:

- ``hydromodpy/solver/modflow_nwt``
- ``hydromodpy/solver/modflow6``
- ``hydromodpy/solver/boussinesq``

Where to change what
--------------------

When reading or modifying the pipeline, the right file usually depends on the
kind of change:

- change launcher-only config or workspace behavior:
  ``launchers/process_simulation/launcher.py``
- change planning rules or dependency binding:
  ``hydromodpy/simulation/planning/``
- change execution order or process transitions:
  ``hydromodpy/simulation/execution/runner.py``
- change how a solver is called from generic runtime state:
  ``hydromodpy/simulation/adapters/``
- change the numerical backend itself:
  ``hydromodpy/solver/<backend>/``

See also
--------

- :doc:`launcher-simulation-class-diagram`
- :doc:`simulation-time-cycle-diagrams`
- :doc:`../launchers/launcher-simulation-sequence-diagram`
- :doc:`../solver/index`
