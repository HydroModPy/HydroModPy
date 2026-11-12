From TOML to solver outputs
===========================

This note follows the main execution chain, from one TOML file to the solver outputs and the
stored run. It answers the question "which file runs next when HydroModPy executes a
configuration?". :doc:`../mental-model` gives the same path as a diagram of concepts, and
:doc:`../pipeline_resume` says how an interrupted run restarts. The planner, the runner and the
adapter calls are described in the section "How a run reaches a backend" of
:doc:`../packages/solver`, and the backends are on :doc:`backends`.

The chain
---------

1. ``hmp run <file>`` enters at ``hydromodpy/cli/commands/run.py``, which builds a
   ``RunRequest`` with ``request_of`` (``hydromodpy/project/request.py``). The file is a
   ``.toml`` file or a ``.json`` run request. ``hydromodpy.run`` in
   ``hydromodpy/project/api.py`` builds the same request from Python, and a server or a Docker
   container hands over the same JSON.
2. ``DISPATCH`` in ``hydromodpy/project/dispatch/workflow.py`` selects the launcher:
   ``simulation``, ``overview`` or ``calibration``. ``[workflow].mode`` names it. When it is
   unwritten, the sections say it: ``[calibration]`` calibrates, ``[overview]`` without
   ``[simulation]`` draws the overview, and anything else simulates.
3. For ``simulation``, ``run_simulation`` loads the document into a ``HydroModPyConfig``
   (``hydromodpy/config/loading.py``), claims the run folder, resolves the inputs and opens
   ``Project`` (``hydromodpy/project/facade.py``), which calls ``Project.simulate``. The next
   section gives the order.
4. ``simulate`` builds the shared model phase once, then runs the ``Pipeline``
   (``hydromodpy/workflow/runner.py``) over the steps of ``standard_steps()``.
5. Inside the pipeline, ``SimulationPlanner`` builds a ``SimulationPlan``, and
   ``RunSolverStep`` hands it to ``SimulationRunner`` (both in ``hydromodpy/solver/base/``).
   The runner asks ``registry.py`` for the adapter of each ``<process_type>_<name>`` key, and
   the adapter builds and runs the model of its backend.
6. The extract, derive, export, seal and display steps write the run to disk.

The order of a run
------------------

``run_simulation(request, base=, environment=)`` does the following in this order. A refusal in
steps 1 and 2 leaves nothing on the disk.

1. ``load`` reads the document of the request, with its ``set`` changes, from the base. The base
   is the folder that relative paths are read from. It is an argument, so a document in memory
   needs one and is refused without it.
2. ``Environment.check`` tests the credentials and the bounds of the call, and ``check_name``
   tests the name of the run against the rule of ``core/state/names.py``: ``[a-z0-9_-]``, 40
   characters, no reserved Windows name.
3. The run claims ``runs/<name>[.vN]``. A completed name gets a new version, and a failed or
   aborted one continues as the next attempt. The claim writes ``outcome.json`` and starts the
   pulse. Its ``sim_id`` is a uuid taken here, and it enters no identity.
4. A request given as JSON or as a dict is written as ``request.json``, whole and never
   redacted. ``config.toml``, which is what the run was given, is written from the loaded
   configuration. A run that stops before the mesh can then be resumed. ``config.resolved.toml``
   comes later, from ``prepare_solver``.
5. ``resolve_inputs`` turns every input into a file with a digest. A download that fails closes
   the outcome as ``failed``. The result goes into ``WorkflowContext.inputs``, so the setup
   step does not resolve a second time.
6. The ``request_id`` is computed and written into ``outcome.json`` at once.
7. A resumed attempt starts over when its ``request_id`` differs from the one of the last
   attempt, or when that attempt recorded none.
8. A plain run is not a resume, a partial window, a forced run or a replay. It computes its
   ``solution_key`` and looks for a sealed run of the same name with an equal key. When it
   finds one, the claim is withdrawn without a trace and that run is given back. The file of
   each API source that the found run cites must still be in the cache with the same sha256,
   or the run is computed. ``hmp run`` and ``hmp calibrate`` skip this way, and no other verb
   does.
9. ``if_exists = "fail"`` is tested after the skip, so an identical run is always given back.
10. The pipeline runs.

The request id says what a run asks for. It is the sha256 of the document as a file writes it,
without ``[workspace]``, ``[workflow]``, :toml:`simulation.name`, every ``deliver_to`` key and
the mesh that the run builds. Each input enters by its digest and the state of its bytes. A URL
enters by its pinned sha256, so the address leaves the document. The edition of the defaults
enters too, and so does the digest of the ``final_state/`` that a window starts from. The
solution key adds the code that computes, the mesh engine and its version, the sha256 of the
solver binaries and the versions of the numeric packages. The name of the run, its ``sim_id``
and its path are in neither key. The code is ``hydromodpy/results/record/request_identity.py``,
and the claim and restart of a folder is ``hydromodpy/results/storage/attempt.py``.

The model phase and the steps
-----------------------------

``Project`` keeps the session state and builds the model phase once per session and not once
per solver. ``setup_workspace``, ``build_geographic``, ``load_data`` and ``build_mesh`` are its
methods. They do no I/O when built, so a notebook can run only the phase that changed.

``standard_steps()`` in ``hydromodpy/workflow/steps/sequence.py`` is the canonical order of
the pipeline. Each step is a class in ``hydromodpy/workflow/steps/`` with a ``name``, a
``run(state)`` method and the payload keys it reads and writes.

The thirteen steps run in this order: ``ValidateStep``, ``ResolveStep``,
``BuildGeographicStep``, ``LoadDataStep``, ``BuildMeshStep``, ``SetupProcessStep``,
``PrepareSolverStep``, ``RunSolverStep``, ``ExtractStep``, ``DeriveStep``, ``ExportStep``,
``SealStep`` and ``DisplayStep``.

The order of the tail has a reason. ``ExportStep`` removes the solver files and the scratch,
``SealStep`` certifies the run with ``manifest.json``, then the data exports, the metadata
views and the figures read the sealed run. A render that fails after the seal leaves the run
sealed.

The disk is the truth and the index is derived (:doc:`../storage-layout`).
``PrepareSolverStep`` registers the run and creates the paths of its artifacts. ``ExtractStep``
writes the solver outputs into them. ``DeriveStep`` writes the catchment aggregates, the
observation samples and the fit metrics, and the derived fields are rebuilt on read.

Planning and execution
----------------------

``SimulationPlanner.build`` turns the ``[simulation]`` block into one ordered, immutable
``SimulationPlan`` of ``ProcessRun`` objects. It expands one ``[[simulation.process]]`` entry
into one ``ProcessRun`` per solver, binds each run to the earlier runs its adapter
``requires``, and rejects an impossible graph early. The plan is a schedule only, and the
mutable state belongs to the workflow context that ``Project`` carries between phases.
``SimulationRunner.execute`` walks the plan in order and calls the adapter. It knows nothing of a
solver API. The steps of that call are in :doc:`../packages/solver`.

The time cycle
--------------

``[simulation.time]`` drives one canonical time grid. The code is in
``hydromodpy/core/time/window.py``.

1. ``resolve_simulation_time_window(cfg)`` validates the declared window, and
   ``resolve_simulation_time_grid(cfg)`` builds the ``ResolvedSimulationTimeGrid``, with period
   lengths in seconds (``SIMULATION_TIME_UNIT``). A step that does not align with the window
   is refused.
2. ``require_flow_simulation_time_grid`` refuses a flow process that has no grid. ``Project``
   stores the grid in ``setup.time_grid``.
3. A data section that declares no dates gets the window from
   ``resolve_simulation_time_window_dates``. A section that declares its own dates keeps them.
4. ``hydromodpy/model/forcing/time_alignment.py`` aggregates a forcing series onto the periods.
   It takes the mean over ``[start, end)`` and carries the last earlier value over an empty
   period. ``validate_recharge_coverage`` applies the coverage policy of the window, and
   ``hydromodpy/model/forcing/time_forcing.py`` prepares the flow-side payload for the adapters.
5. Each solver reads the grid for its number of periods and their lengths.

Comparison of sealed runs
-------------------------

``hmp diff`` compares runs that already finished. It never runs a simulation and reads no
comparison TOML. The runs to compare are recipes of one project (``[sites.recipes]``), run like
any other case. All the code is ``hydromodpy/project/compare.py``, which reads every run through
the public ``Run`` API. From Python, ``hmp.compare([...])`` gives the same tables without
writing anything, and ``Comparison.write`` writes them.

.. code-block:: bash

   hmp diff nancon-mf6 nancon-bouss --to ../nancon_study
   hmp diff a b --by site

A reference is a run directory, a run name under ``runs/`` or a recipe, which stands for the
latest version of every case of that recipe. The first run is the reference of the differences.
A comparison stops with a message when the runs model different sites, when they share no date,
or when steady and transient runs are mixed. Two steady runs always compare.

A stamp closes its period. Two series are compared on the whole periods that every run covers,
at the coarsest step among them, with each value averaged over the period and weighted by
duration. A daily run and a monthly run compare on the months, and a month that one run covers
in part is left out. Two maps are compared at the last date that all the runs share, per unit of
surface, and the table is empty when no date is shared. On another mesh, each cell of the
reference reads the nearest cell of the other run, and no further than one cell size.
``same_mesh`` and ``n`` say what was compared.

The folder is ``summary/report/compare/<refs>/`` of the project, or ``--to``. Under ``--by site``
each site has its own sub-folder, and ``by_site.csv`` joins their scores. A ``README.md`` lists
the reference, the dates and every table and figure. The zones of ``budget.csv`` are never added,
because the catchment holds water that the domain already counts. Its term ``residual`` sums the
others. It is near zero on the domain, and on a catchment it also holds the lateral exchange.

A new table is one function in ``compare.py``, one line in ``compare``, and one test in
``tests/unit/project/test_compare.py``. The module computes nothing that ``Run`` can answer, and
it converts no unit, so a quantity stays as the run stores it.
