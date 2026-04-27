TOML To Solver Walkthrough
==========================

Scope
-----

This page is a code-oriented walkthrough of the main execution chain
from one TOML config file to concrete solver outputs.

It complements the UML views by answering a more practical question:

"Which file runs next when HydroModPy executes one simulation config?"

End-to-end chain
----------------

For the standard simulation workflow, the runtime path is:

1. ``hydromodpy/_cli/commands/run.py`` (the ``hmp run <toml>`` entry
   point) and ``hydromodpy/_cli/workflows.py`` (workflow dispatch)
2. ``HydroModPyConfig.from_toml(...)`` builds the typed config tree
3. ``hydromodpy/project.py`` instantiates the public ``Project``
   facade and runs setup, data, and optional mesh preparation
4. ``hydromodpy/simulation/planning/planner.py``
5. ``hydromodpy/simulation/execution/runner.py``
6. one registered adapter under ``hydromodpy/simulation/adapters/``
7. one concrete solver package under ``hydromodpy/solver/``
8. solver-side postprocess and catalog persistence through
   ``hydromodpy/results/catalog.py``

Step 1: config loading and project bootstrap
--------------------------------------------

The CLI is a thin entry point. ``hmp run`` reads the TOML, dispatches
based on the top-level ``workflow = "..."`` field, then instantiates
``Project``. ``Project`` owns the bootstrap:

- it validates the typed config tree,
- it keeps the raw TOML for optional top-level sections,
- it resolves the simulation time window,
- it derives the effective data-loading plan,
- it prepares optional runtime mesh inputs.

This stays project-level code because these concerns mix paths,
workspaces, optional top-level sections, and runtime state assembly.

Step 2: setup, data, and optional mesh phases
---------------------------------------------

Before any solver run is planned, ``Project`` prepares the shared
runtime context:

- ``setup_workspace`` creates the workspace catalog and the project
  layout,
- ``build_geographic`` builds the catchment delineation, DEM, and
  domain-facing state,
- ``load_data`` resolves the required forcing and observation
  families,
- ``build_mesh`` either builds a runtime Gmsh mesh or loads one from
  disk.

These phases run once per project session, not once per solver. Lazy
projects (``Project.lazy(cfg)``) trigger each phase explicitly so
notebooks can re-execute only the phase that changed.

Step 3: declarative simulation config to executable plan
--------------------------------------------------------

``SimulationPlanner`` turns the declarative ``[simulation]`` block into
one ordered immutable ``SimulationPlan``.

Its main responsibilities are:

- preserve user-declared process order,
- expand one process entry into one concrete ``ProcessRun`` per solver,
- bind each run to earlier compatible providers using the static
  compatibility matrix,
- reject invalid or ambiguous execution graphs early.

At this point the result is still only a plan, not execution.

Step 4: process-family runtime execution
----------------------------------------

``SimulationRunner`` walks the resolved plan in order.

It owns:

- process-family transitions,
- process-context materialization (``Flow``, ``Transport``),
- dependency lookup through ``models_by_run_id``,
- adapter dispatch for each ``ProcessRun``.

It does not know solver-specific API details.

Step 5: adapter boundary
------------------------

The adapter layer is the narrow bridge between generic simulation
orchestration and concrete solver APIs.

Examples:

- ``solver/modflow_nwt/adapters/flow.py``
- ``solver/modflow6/adapters/flow.py``
- ``solver/boussinesq/adapters/flow.py``
- ``solver/modflow_nwt/adapters/transport_mt3dms.py``
- ``solver/modflow6/adapters/transport.py``

For MODFLOW-family flow runs, backend-specific adapters stay
intentionally thin, while the shared execution lifecycle lives in
``solver/modflow_common/flow_adapter_helpers.py``.

Step 6: concrete solver packages
--------------------------------

Once the adapter has built the concrete solver object, execution moves
into one package under ``hydromodpy/solver``.

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

When reading or modifying the pipeline, the right file usually depends
on the kind of change:

- change CLI dispatch or workflow registration:
  ``hydromodpy/_cli/workflows.py``
- change top-level project orchestration or workspace behaviour:
  ``hydromodpy/project.py``
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

- :doc:`simulation-orchestration-class-diagram`
- :doc:`simulation-time-cycle-diagrams`
- :doc:`../solver/index`
