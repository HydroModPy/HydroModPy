From TOML to solver outputs
===========================

A code-oriented walkthrough of the main execution chain, from one TOML file to
the solver outputs and the stored run. It answers "which file runs next when
HydroModPy executes a simulation config?". :doc:`../mental-model` gives the same
path as a diagram of concepts, and :doc:`../pipeline_resume` says how an
interrupted run restarts.

End-to-end chain
----------------

1. ``hmp run <file>`` enters at ``hydromodpy/cli/commands/run.py``, which builds a ``RunRequest``
   with ``request_of`` (``hydromodpy/project/request.py``). The file is a ``.toml`` file or a
   ``.json`` run request. ``hydromodpy.run`` in ``hydromodpy/_api.py`` builds the same request
   from Python, and a server or a Docker container hands over the same JSON.
2. The workflow of the request selects the launcher through ``DISPATCH`` in
   ``hydromodpy/project/dispatch/workflow.py``: ``simulation``, ``overview`` or
   ``calibration``. ``[workflow].mode`` names it; left unwritten, the sections
   of the document say it (``[calibration]`` calibrates, ``[overview]`` without
   ``[simulation]`` draws the overview, anything else simulates).
3. For ``simulation``, ``run_simulation`` loads the document into a ``HydroModPyConfig``
   (``hydromodpy/config/loading.py``), claims the run folder, resolves the inputs and opens
   ``Project`` (``hydromodpy/project/facade.py``), which calls ``Project.simulate``. The next
   section gives the order.
4. ``simulate`` builds the shared model phase once, then runs the ``Pipeline``
   (``hydromodpy/workflow/runner.py``) over the twelve steps of
   ``standard_steps()`` in ``hydromodpy/workflow/steps/sequence.py``.
5. Inside that pipeline, the planning code builds a ``SimulationPlan`` with
   ``SimulationPlanner`` (``hydromodpy/solver/base/planner.py``), and
   ``RunSolverStep`` hands it to ``SimulationRunner``
   (``hydromodpy/solver/base/runner.py``).
6. The runner asks ``hydromodpy/solver/base/registry.py`` for the adapter of each
   ``<process_type>_<name>`` key. The adapter sits under
   ``hydromodpy/solver/<backend>/adapters/``.
7. The backend package under ``hydromodpy/solver/`` builds and runs the model.
8. The extract, derive, display and export steps write the run to disk.

The order of a run
------------------

``run_simulation(request, base=, environment=)`` does these things in this order. A refusal in
steps 1 and 2 leaves nothing on the disk.

1. ``load`` reads the document of the request, with its ``set`` changes, from the base. The base
   is the folder relative paths are read from. It is an argument, so a document in memory needs
   one and is refused without it.
2. ``Environment.check`` tests the credentials and the bounds of the call, and ``check_name``
   tests the name of the run against the rule of ``core/state/names.py``: ``[a-z0-9_-]``, 40
   characters, no reserved Windows name.
3. The run claims ``runs/<name>[.vN]``. A completed name gets a new version, a failed or aborted
   one continues as the next attempt. The claim writes ``outcome.json`` and starts the pulse. Its
   ``sim_id`` is a uuid taken here, and it enters no identity.
4. A request given as JSON or as a dict is written as ``request.json``, whole and never
   redacted. ``config.toml``, what the run was given, is written from the loaded configuration.
   A run that stops before the mesh can then be resumed. ``config.resolved.toml`` comes later,
   from ``prepare_solver``.
5. ``resolve_inputs`` turns every input into a file with a digest. A download that fails closes
   the outcome as ``failed``. The result is put in ``WorkflowContext.inputs``, so the setup step
   does not resolve a second time.
6. The ``request_id`` is computed and written into ``outcome.json`` at once.
7. A resumed attempt starts over when its ``request_id`` differs from the one of the last
   attempt, or when that attempt recorded none.
8. A plain run (not a resume, a partial window, a forced run or a replay) computes its
   ``solution_key`` and looks for a sealed run of the same name whose key is equal. Found, the
   claim is withdrawn without a trace and that run is given back. The file of each API source that
   the found run cites must still be in the cache with the same sha256, or the run is computed.
   ``hmp run`` and ``hmp calibrate`` skip this way, and no other verb does.
9. ``if_exists = "fail"`` is tested after the skip, so an identical run is always given back.
10. The pipeline runs.

The request id says what a run asks for. It is the sha256 of the document as a file writes it,
without ``[workspace]``, ``[workflow]``, ``simulation.name`` and every ``deliver_to`` key, and
without the mesh the run builds. Each input enters by the digest and the state of its bytes, and a
URL enters by its pinned sha256, so the address leaves the document. The edition of the
defaults enters too, and so does the digest of the ``final_state/`` a window starts from, when
it starts from one. The solution
key adds the code that computes, the mesh engine and its version, the sha256 of the solver
binaries and the versions of the numeric packages. The name of the run, its ``sim_id`` and its
path are in neither.

Config loading and the model phase
----------------------------------

The CLI is a thin entry point. ``Project`` keeps the session state: the typed
config tree, the raw TOML for the optional sections, the resolved time window, the
data-loading plan and, once it is built, the cell mesh. These concerns mix paths,
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
runs a run declares in ``depends_on``, fills the ``RunSlot`` of the run, builds a
``RunContext`` and calls the adapter through ``validate``, ``build`` and ``run``. It
knows nothing of a solver API.

The adapter is the narrow bridge to a solver:

- ``solver/modflow_nwt/adapter.py``
- ``solver/modflow6/adapter.py``
- ``solver/boussinesq/adapter.py``
- ``solver/modflow_nwt/mt3dms/mt3dms.py`` and
  ``solver/modflow_nwt/modpath/modpath.py``
- ``solver/modflow6/transport.py`` and ``solver/modflow6/prt.py``

For the MODFLOW family, the adapters stay thin and the shared lifecycle is in
``solver/modflow_common/flow_adapter_helpers.py``. The flow backends are
``solver/modflow_nwt``, ``solver/modflow6`` and ``solver/boussinesq``.

Persistence
-----------

The disk is the truth and the DuckDB index is derived from it
(:doc:`../storage-layout`). ``PrepareSolverStep`` registers the run and creates the
paths of its artifacts. ``ExtractStep`` writes the solver outputs into them,
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
   * - The request, the base of relative paths
     - ``hydromodpy/project/request.py`` and ``hydromodpy/config/loading.py``
   * - The rule of a project name and of a run name
     - ``hydromodpy/core/state/names.py``
   * - The request id and the solution key
     - ``hydromodpy/results/record/request_identity.py``
   * - Claim, restart and withdrawal of a run folder
     - ``hydromodpy/results/storage/attempt.py``
   * - Project orchestration, workspace behavior
     - ``hydromodpy/project/facade.py``
   * - Planning rules, dependency binding
     - ``hydromodpy/solver/base/plan.py`` and ``planner.py``
   * - Execution order, process transitions
     - ``hydromodpy/solver/base/runner.py``
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
   ``hydromodpy/model/forcing/time_alignment.py`` (the mean over ``[start, end)``, with
   the last earlier value carried forward over an empty period).
   ``validate_recharge_coverage`` applies the coverage policy of the window.
   ``hydromodpy/model/forcing/time_forcing.py`` prepares the flow-side payload for the
   adapters.
5. Each solver reads the grid for its number of periods and their lengths.

See also
--------

- :doc:`comparison-workflow` for the comparison of sealed runs.
- :doc:`../solver/backends` for the solver backends.
