From TOML to solver outputs
===========================

A code-oriented walkthrough of the main execution chain, from one TOML file to
the solver outputs and the stored run. It answers "which file runs next when
HydroModPy executes a simulation config?". :doc:`../mental-model` gives the same
path as a diagram of concepts, and :doc:`../pipeline_resume` says how an
interrupted run restarts.

End-to-end chain
----------------

1. ``hmp run <file>`` enters at ``hydromodpy/cli/commands/run.py``.
   ``hydromodpy.run`` in ``hydromodpy/_api.py`` takes the same path from Python.
2. ``[workflow].mode`` selects the launcher through ``DISPATCH`` in
   ``hydromodpy/project/dispatch/workflow.py``: ``simulation``, ``overview``,
   ``calibration``, ``comparison``, ``testbed`` or ``site_selection``.
3. For ``simulation``, ``run_simulation`` opens ``Project``
   (``hydromodpy/project/facade.py``), which validates the file into a
   ``HydroModPyConfig`` and calls ``Project.simulate``.
4. ``simulate`` builds the shared model phase once, then runs the ``Pipeline``
   (``hydromodpy/workflow/runner.py``) over the twelve steps of
   ``standard_steps()`` in ``hydromodpy/workflow/orchestrator.py``.
5. Inside that pipeline, the planning code builds a ``SimulationPlan`` with
   ``SimulationPlanner`` (``hydromodpy/simulation/planning/planner.py``), and
   ``RunSolverStep`` hands it to ``SimulationRunner``
   (``hydromodpy/simulation/execution/runner.py``).
6. The runner asks ``hydromodpy/solver/base/registry.py`` for the adapter of each
   ``(process_type, solver_name)`` pair. The adapter sits under
   ``hydromodpy/solver/<backend>/adapters/``.
7. The backend package under ``hydromodpy/solver/`` builds and runs the model.
8. The extract, derive, display and export steps write the run to disk.

Config loading and the model phase
----------------------------------

The CLI is a thin entry point. ``Project`` keeps the session state: the typed
config tree, the raw TOML for the optional sections, the resolved time window, the
data-loading plan and the optional runtime mesh inputs. These concerns mix paths,
workspaces and optional sections, so they stay project-level code. Ordered
execution belongs to ``Pipeline``.

The model phase is built once per project session, not once per solver:
``setup_workspace``, ``build_geographic``, ``load_data`` and ``build_mesh`` are
methods of ``Project``. Construction does no I/O, so a notebook can run only the
phase that changed.

The twelve steps
----------------

``standard_steps()`` is the canonical order: ``ValidateStep``, ``ResolveStep``,
``BuildGeographicStep``, ``LoadDataStep``, ``BuildMeshStep``, ``SetupProcessStep``,
``PrepareSolverStep``, ``RunSolverStep``, ``ExtractStep``, ``DeriveStep``,
``DisplayStep``, ``ExportStep``. Each is a class in ``hydromodpy/workflow/steps/``
with a ``name``, a ``run(state)`` method and the payload keys it reads and writes.
Figures are drawn before ``ExportStep`` because the export seals the store.

Planning
--------

``SimulationPlanner.build`` turns the ``[simulation]`` block into one ordered,
immutable ``SimulationPlan`` of ``ProcessRun`` objects. It keeps the order the user
declared, expands one ``[[simulation.process]]`` entry into one ``ProcessRun`` per
solver, binds each run to the earlier runs its adapter ``requires``, and rejects an
impossible graph early. The plan is only a schedule.

Execution
---------

``SimulationRunner.execute`` walks the plan in order. It makes the process objects
(``Flow``, ``Transport``) exist through the ``ensure_*`` functions, resolves the
models a run declares in ``depends_on``, builds a ``RunContext`` and calls the
adapter. It knows nothing of a solver API.

The adapter is the narrow bridge to a solver:

- ``solver/modflow_nwt/adapters/flow.py``
- ``solver/modflow6/adapters/flow.py``
- ``solver/boussinesq/adapters/flow.py``
- ``solver/modflow_nwt/adapters/transport_mt3dms.py`` and
  ``transport_modpath.py``
- ``solver/modflow6/adapters/transport.py`` and ``prt.py``

For the MODFLOW family, the adapters stay thin and the shared lifecycle is in
``solver/modflow_common/flow_adapter_helpers.py``. The flow backends are
``solver/modflow_nwt``, ``solver/modflow6`` and ``solver/boussinesq``.

Persistence
-----------

The disk is the truth and the DuckDB index is derived from it
(:doc:`../storage-layout`). ``PrepareSolverStep`` registers the run and creates the
paths of its artefacts. ``ExtractStep`` writes the solver outputs into them,
``DeriveStep`` writes the catchment aggregates, the observation samples and the fit
metrics (the derived fields are rebuilt on read, not written), and ``ExportStep``
finalizes the run,
seals it with ``manifest.json`` and removes the transient solver scratch.

Where to change what
--------------------

.. list-table::
   :header-rows: 1
   :widths: 56 44

   * - Change
     - Where
   * - Workflow registration or CLI dispatch
     - ``hydromodpy/project/dispatch/workflow.py``
   * - Project orchestration, workspace behaviour
     - ``hydromodpy/project/facade.py``
   * - Planning rules, dependency binding
     - ``hydromodpy/simulation/planning/``
   * - Execution order, process transitions
     - ``hydromodpy/simulation/execution/runner.py``
   * - How a solver is called from the run state
     - ``hydromodpy/solver/<backend>/adapters/``
   * - The numerical backend
     - ``hydromodpy/solver/<backend>/``
   * - Result indexing, Zarr and Parquet storage, finalization
     - ``hydromodpy/results/`` and ``hydromodpy/workflow/steps/export.py``

Orchestration classes
---------------------

The static view of the objects above: ``Project`` builds a plan with the planner and
hands it to the runner, which reaches the solvers through registered adapters.

.. uml:: diagrams/simulation_orchestration_class.wsd

``SimulationPlan`` is immutable. The planner builds it once and the runner consumes
it without changing the schedule. The mutable state belongs to the workflow context
that ``Project`` carries between phases. An adapter is chosen from
``ProcessRun.solver``, so the solver choice stays visible in the plan.

The time cycle
--------------

``[simulation.time]`` drives one canonical time grid. The code is in
``hydromodpy/core/time/window.py``:

1. ``resolve_simulation_time_window(cfg)`` validates the declared window, and
   ``resolve_simulation_time_grid(cfg)`` builds the ``ResolvedSimulationTimeGrid``, with
   period lengths in seconds (``SIMULATION_TIME_UNIT``). A step that does not align with
   the window is refused.
2. ``require_flow_simulation_time_grid`` refuses a flow process that has no grid.
   ``Project`` stores the grid in ``setup.time_grid``.
3. A data section that declares no dates gets the window from
   ``resolve_simulation_time_window_dates``. A section that declares its own dates keeps
   them.
4. A forcing series is aggregated onto the periods by
   ``hydromodpy/physics/forcing/time_alignment.py`` (the mean over ``[start, end)``, with
   the last earlier value carried forward over an empty period).
   ``validate_recharge_coverage`` applies the coverage policy of the window.
   ``hydromodpy/physics/flow/time_forcing.py`` prepares the flow-side payload for the
   adapters.
5. Each solver reads the grid for its number of periods and their lengths.

See also
--------

- :doc:`comparison-workflow` and :doc:`testbed-workflow-architecture` for the two
  workflows that run simulations as children.
- :doc:`../solver/backends` for the solver backends.
