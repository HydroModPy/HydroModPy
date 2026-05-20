Calibration Guide
=================

Audience: hydrogeologists, modelers, and HydroModPy contributors who
need to calibrate the parameters of a catchment-scale groundwater
model. Suggested reading order: §1 (principles), §2 (workflow), §3
(TOML), §7 (reading the results). Sections §4 to §9 are reference
material to consult once the loop is running.

This guide is the single source of truth for the calibration
sub-system. Code: ``hydromodpy/calibration/``.

For complementary reading, see :doc:`index` (calibration architecture
root), :doc:`../overview/design-patterns` (item 7 covers the calibration
adapters), :doc:`../overview/two-databases`, and
:doc:`../../user_guide/workflows/calibration`.

Overview
--------

A HydroModPy calibration is an ask/tell loop that iteratively adjusts a
few model parameters (hydraulic conductivity ``K``, specific yield
``Sy``, drain conductance) so that the simulated output matches a
reference series (discharge at a station, head at a piezometer). The
loop is driven by an optimizer that proposes values and reacts to a
scalar objective (NSE, KGE, RMSE) computed at every trial.

Compared to a plain ``hmp run``, a calibration:

- produces a trace of N evaluations (one row per trial in the DuckDB
  catalog), not a single simulation;
- reuses the expensive setup steps (geographic, mesh, data loading)
  across trials through the ``prepare-once-evaluate-many`` primitive;
- only writes the best runs to disk as full Zarr / Parquet
  simulations. Other trials remain as lightweight rows in DuckDB;
- can be resumed across sessions through the content-addressed
  ``params_hash`` cache.

Use a calibration to fit a model to observations. Use a plain
``hmp run`` when the parameters are already known.

Specific terms used in this guide:

- ``TrialContext``: prepared runtime, reused by every trial of a
  session (§2, §4).
- ``earliest_affected_step``: integer that decides which pipeline
  steps are skipped per trial (§4).
- ``params_hash``: SHA-256 fingerprint used by the cross-session cache
  (§8).
- ``promote_trial``: action that turns a lightweight trial row into a
  complete Zarr / Parquet simulation (§2, §5).

End-to-end workflow
-------------------

.. list-table:: Calibration data flow
   :header-rows: 1
   :widths: 24 76

   * - Stage
     - What flows into it and what it produces
   * - ``TOML``
     - User config with ``[workflow].mode = "calibration"``. Read by ``hmp run``.
   * - ``hmp run``
     - Dispatches the TOML to ``prepare_trials``.
   * - ``prepare_trials``
     - Runs pipeline steps ``[0..earliest)`` once. Builds the prepared
       ``WorkflowContext`` consumed by the ask/tell loop.
   * - Ask/tell loop (``run_trial_light``)
     - Each trial reads the prepared context, writes one row to DuckDB
       (``calibration_iterations``). After the loop ends, control passes
       to ``promote_trial``.
   * - DuckDB (``calibration_sessions`` + ``calibration_iterations``)
     - Stores trial fingerprints and session metadata. Read by
       ``hmp report``.
   * - ``promote_trial`` (top-N)
     - Replays the chosen trials through the full pipeline. Writes
       Zarr + Parquet + ``simulations`` rows and back-fills
       ``calibration_iterations.sim_id``.
   * - Catalog (simulations + Zarr + Parquet)
     - Read by ``hmp report`` alongside the DuckDB iteration history.
   * - ``hmp report``
     - Reads sessions, iterations, simulation outputs, and renders the
       calibration HTML report with figures.

Node by node:

- **TOML**: a regular HydroModPy project TOML extended with a
  ``[calibration]`` section and a top-level
  ``[workflow].mode = "calibration"`` marker. The rest of the file
  (``[simulation]``, ``[flow]``, ``[data]``, ``[solver]``) is exactly
  what you would write for a single run.
- **``hmp run``**: the unified CLI entry point. It reads
  ``[workflow].mode = "calibration"`` and dispatches to
  ``hydromodpy.calibration.cli_runner.run_calibration_cli``. Calibration
  has no separate top-level subcommand.
- **``prepare_trials``**: runs pipeline steps ``[0..earliest)`` exactly
  once. ``earliest`` is computed from the dotted paths declared by
  ``[calibration.parameters.*]`` (see §4). The prepared
  ``WorkflowContext`` (geographic, mesh, loaded forcings) is held in
  RAM and forked by every trial.
- **Ask/tell loop**: the optimizer proposes a parameter point, the
  loop forks the prepared context, injects the values, runs steps
  ``[earliest..8]`` in **lightweight** mode (no disk writes beyond the
  solver's own scratch files), extracts the scalar objective from RAM,
  and tells the optimizer. Repeat up to ``max_iter``.
- **DuckDB**: every trial adds one row to ``calibration_iterations``
  (``sim_id`` stays ``NULL``). The session metadata lives in one row
  of ``calibration_sessions`` finalized at the end.
- **``promote_trial`` (top-N)**: if ``save_runs != "none"``, the
  chosen trials are replayed through the *full* pipeline (steps
  ``00..11``) by ``hydromodpy.Project(cfg_path).run(**values)``. Each
  promotion creates a Zarr store, a Parquet directory, and a
  ``simulations`` row, and back-fills the corresponding
  ``calibration_iterations.sim_id``.
- **``hmp report <session_id>``**: post-processing CLI that reads the
  session and iterations from DuckDB, renders the six calibration
  figures, and emits a standalone HTML report at
  ``<workspace>/reports/<session_id>/report.html``.

The user TOML
-------------

The examples below come from the canonical case shipped with the
repository:
``examples/projects/02_nancon_watershed/run_calibration_k.toml``.

Overlay and workflow marker
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: toml

   base_config = "project.toml"

   [workflow]
   mode = "calibration"

- ``base_config``: relative path to the *base* project TOML
  (``project.toml`` here). All sections of the base are inherited and
  overridden by the current file. This is how a single description of
  the catchment is shared between simulation, calibration, and sweep
  overlays.
- ``[workflow].mode = "calibration"``: the single switch that tells
  ``hmp run`` to dispatch to the ask/tell loop instead of the default
  single-simulation path. Dispatch logic lives in
  ``hydromodpy/cli/workflows.py:DISPATCH``.

Standard simulation block
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: toml

   [simulation]
   name = "nancon_calibration_k"
   description = "Optuna calibration of K on NSE(discharge), Sy/Ss frozen."

   [simulation.time]
   start_datetime = "2000-01-01"
   end_datetime = "2002-12-31"
   step_value = "1 month"
   coverage_policy = "warn"

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflownwt"]

The ``[simulation]`` tree is exactly what you write for a single
``hmp run``: a name, a time window, and one or more processes.
**Changing the solver does not change anything in the
``[calibration]`` section**: the calibration code is solver-agnostic
(no ``modflow``, ``modflow6``, ``boussinesq``, or ``solver_engine``
string appears anywhere in ``hydromodpy/calibration/``). Swap
``"modflownwt"`` for ``"modflow6"`` and the same TOML calibrates the
other solver (subject to the metric extractor coverage noted in §6).

Frozen parameters
~~~~~~~~~~~~~~~~~

.. code-block:: toml

   [domain.depth_model]
   thickness = 30.0

   [flow.param.Sy.field]
   value = 0.05

   [flow.param.Ss.field]
   value = 1e-5

   [flow.sinks_sources.recharge]
   first_clim = "first"

Any leaf not listed under ``[calibration.parameters.*]`` is **frozen**
at the value written in the TOML. Here ``Sy`` and ``Ss`` are frozen at
``0.05`` and ``1e-5``; only ``K`` is calibrated.

The ``[calibration]`` section
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: toml

   [calibration]
   method = "grid"
   max_iter = 40
   batch_size = 1
   save_runs = "best_n"
   save_best_n = 5
   seed = 42
   objective = "nse"
   variable = "discharge"
   use_cache = true

Exhaustive option reference:

.. list-table::
   :header-rows: 1

   * - Option
     - Values
     - Default
     - Effect
   * - ``method``
     - ``grid`` / ``random_search`` / ``optuna`` / ``scipy_de`` / ``scipy_nelder_mead``
     - ``grid``
     - Sampler backing the ask/tell loop. ``optuna`` is installed by
       default; ``cma_es`` and the Optuna ``cmaes`` sampler require the
       calibration extra.
   * - ``max_iter``
     - integer >= 1
     - ``100``
     - Maximum number of trial evaluations.
   * - ``save_runs``
     - ``none`` / ``best_n`` / ``all``
     - ``none``
     - How many trials to promote to full simulations after the loop.
   * - ``save_best_n``
     - integer >= 0
     - ``10``
     - Number of top trials promoted when ``save_runs = "best_n"``.
       **Ignored** when ``save_runs != "best_n"``.
   * - ``objective``
     - ``nse`` / ``kge`` / ``rmse`` / ``"module.path:fn"``
     - ``nse``
     - Scalar metric; the string form is the Python escape hatch
       (§10).
   * - ``variable``
     - ``discharge`` / ``head``
     - ``head``
     - Observed variable to compare against. ``"discharge"`` reads
       from ``[data.hydrometry]``; ``"head"`` from
       ``[data.piezometry]``.
   * - ``seed``
     - integer or ``null``
     - ``null``
     - Random seed for reproducibility. ``null`` =
       non-reproducible.
   * - ``use_cache``
     - bool
     - ``true``
     - Enable the ``params_hash`` cross-session cache (§8).
   * - ``batch_size``
     - integer >= 1
     - ``1``
     - Suggestions drawn per ``ask``. Reserved for future parallel
       trials. Leave at ``1`` today.
   * - ``optimizer_kwargs``
     - dict
     - ``{}``
     - Extra kwargs forwarded to the sampler (for example
       ``{sampler = "cmaes"}`` for Optuna).

Per-parameter declarations
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: toml

   [calibration.parameters.K]
   bounds = [1e-6, 1e-3]
   transform = "log"
   prior = "log_uniform"
   path = "flow.param.K.field.value"
   units = "m/s"

Exhaustive option reference for each
``[calibration.parameters.<name>]`` block:

.. list-table::
   :header-rows: 1

   * - Option
     - Values
     - Required
     - Effect
   * - ``bounds``
     - ``[low, high]``
     - yes (except some grid/fixed-space setups)
     - Physical bounds. For ``optuna`` / ``scipy_de`` / ``grid`` these
       are the sampling bounds.
   * - ``transform``
     - ``identity`` / ``log`` / ``logit``
     - no (defaults to ``identity``)
     - Internal sampling space. Use ``log`` for strictly-positive
       quantities spanning several orders of magnitude (K,
       conductances, storage).
   * - ``prior``
     - ``uniform`` / ``log_uniform`` / ``normal``
     - no (defaults to ``uniform``)
     - Prior used by Bayesian samplers (``gp_mapping``,
       ``da_mh_gp``). Non-Bayesian methods ignore this.
   * - ``path``
     - dotted path
     - yes
     - Where to inject the value in ``HydroModPyConfig`` each trial
       (see §4).
   * - ``units``
     - free string
     - no
     - Informational label used in figures and reports.

Recipes for common parameter shapes:

.. code-block:: toml

   # Homogeneous K
   [calibration.parameters.K]
   bounds = [1e-6, 1e-3]
   transform = "log"
   path = "flow.param.K.field.value"

   # Zoned K: one block per zone, each with its own `path`
   [calibration.parameters.K_granite]
   bounds = [1e-6, 1e-3]
   transform = "log"
   path = "flow.param.K.field.values.zone_granite"

   [calibration.parameters.K_schiste]
   bounds = [1e-6, 1e-3]
   transform = "log"
   path = "flow.param.K.field.values.zone_schiste"

   # Specific yield (no log: already O(1))
   [calibration.parameters.Sy]
   bounds = [0.02, 0.30]
   transform = "identity"
   path = "flow.param.Sy.field.value"

   # Drain conductance
   [calibration.parameters.drain_cond]
   bounds = [1e-4, 1e-1]
   transform = "log"
   path = "flow.sinks_sources.stream_drain.conductance"

   # Aquifer thickness
   [calibration.parameters.thickness]
   bounds = [10.0, 80.0]
   transform = "identity"
   path = "domain.depth_model.thickness"

Recipe cheat sheet
~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Use case
     - Block
   * - Quick exploratory sweep (1-2 params)
     - ``method = "grid"``, ``max_iter ~= 25``,
       ``save_runs = "none"``
   * - Default production calibration
     - ``method = "grid"``, ``max_iter = 100``,
       ``save_runs = "best_n"``, ``save_best_n = 5``,
       ``seed = 42``
   * - Multi-dim continuous (3+ params)
     - ``method = "optuna"``,
       ``optimizer_kwargs = {sampler = "cmaes"}``,
       ``max_iter = 300``
   * - Local refinement near a known optimum
     - ``method = "scipy_nelder_mead"``, ``max_iter = 80``
   * - Full Bayesian posterior (Phase 4)
     - ``method = "da_mh_gp"``, ``max_iter = 2000``,
       ``save_runs = "best_n"``, ``save_best_n = 10``

Automatic step invalidation
---------------------------

Every pipeline step declares which TOML subtrees it reads via a
``config_sections`` class variable. When a calibration mutates
``flow.param.K.field.value``, only the steps that consume ``flow.*``
(and their downstream siblings) need to re-run. The earlier steps
produce the same result on every trial and are executed exactly once
inside ``prepare_trials``.

.. list-table:: Pipeline steps and their role during calibration
   :header-rows: 1
   :widths: 8 22 22 48

   * - Step
     - Name
     - Phase
     - TOML subtrees consumed
   * - 00
     - Validate
     - Shared (run once)
     - ``workspace``, ``simulation``
   * - 01
     - Resolve
     - Shared (run once)
     - ``workspace``, ``simulation``
   * - 02
     - LoadData
     - Shared (run once)
     - ``data``
   * - 03
     - BuildGeographic
     - Shared (run once)
     - ``geographic``, ``data.dem``
   * - 04
     - BuildMesh
     - Shared (run once)
     - ``domain.supports``
   * - 05
     - SetupProcess
     - Shared (run once)
     - ``domain.depth_model``, ``flow.ic``
   * - 06
     - PrepareSolver
     - Looped per trial
     - ``flow``, ``transport``, ``solver``
   * - 07
     - RunSolver
     - Looped per trial
     - ``flow``, ``transport``, ``solver``
   * - 08
     - Extract
     - Looped per trial
     - none (in-memory extraction)
   * - 09
     - Derive
     - Promoted only
     - ``postprocess``
   * - 10
     - Export
     - Promoted only
     - none (write Zarr/Parquet)
   * - 11
     - Display
     - Promoted only
     - ``display``

- **Green (shared)**: steps ``00..05``. Executed once by
  ``prepare_trials``. Geographic, mesh, and loaded forcings live in
  ``TrialContext.ctx`` and are shared by reference across every fork.
- **Orange (looped)**: steps ``06..08``. Re-run per trial in
  ``run_trial_light``. The trial fork deep-copies the config, injects
  the new parameter values, and re-executes this slice only.
- **Blue (promoted)**: steps ``09..11``. Never run during the
  calibration loop. Executed only for the trials picked up by
  ``promote_trial`` after the loop converges.

If I calibrate X, what is replayed?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Calibrated path
     - ``earliest``
     - Steps shared (run once)
     - Steps re-run per trial
     - Rough speedup
   * - ``flow.param.K.field.value``
     - 6
     - 00-05
     - 06-08
     - ~3x
   * - ``flow.param.Sy.field.value``
     - 6
     - 00-05
     - 06-08
     - ~3x
   * - ``flow.param.K.field.values.zone_granite``
     - 6
     - 00-05
     - 06-08
     - ~3x
   * - ``flow.sinks_sources.stream_drain.conductance``
     - 6
     - 00-05
     - 06-08
     - ~3x
   * - ``domain.depth_model.thickness``
     - 5
     - 00-04
     - 05-08
     - ~2x
   * - ``domain.supports.cell_size``
     - 4
     - 00-03
     - 04-08
     - ~1.7x
   * - ``geographic.buff_area``
     - 3
     - 00-02
     - 03-08
     - ~1.3x

**Matching rule: dotted longest-prefix.** Given an override path like
``flow.param.K.field.value``, the selector walks each step's
``config_sections`` and accepts a match when the section is a
dotted-prefix of the path. ``flow`` matches, ``flow.param.K``
matches, ``flow.param.K.field.value`` matches, but ``flow_runtime``
does not. The lowest index among matching steps wins; everything
downstream of it is forced to re-run even if its own sections did not
match (step 08 Extract, for instance, has empty
``config_sections``, yet it re-runs because it consumes the state
produced by step 07).

Implementation:
``hydromodpy/workflow/internals/dependencies.py:earliest_affected_step``.
Per-step annotations: ``config_sections: ClassVar[tuple[str, ...]]``
on each of the 12 ``step_<nn>_*.py`` modules.

Storage
-------

Calibration storage flow, by container:

.. list-table::
   :header-rows: 1
   :widths: 22 28 50

   * - Container
     - Component
     - Role during the calibration loop
   * - RAM (loop only)
     - Aligned vector + scalar metrics
     - Built per trial by ``run_trial_light`` and discarded at end of
       trial. Never reaches disk.
   * - ``catalog.duckdb``
     - ``calibration_sessions``
     - One row per session (start, finalize, status).
   * - ``catalog.duckdb``
     - ``calibration_iterations`` (``sim_id`` NULL)
     - One row per trial: parameters, objective, scalar metrics,
       ``params_hash``.
   * - ``catalog.duckdb``
     - ``simulations``, ``parameters``, ``metrics``, ``tags``
     - Promoted top-N trials only (``promote_trial``). Updates the
       matching ``calibration_iterations.sim_id``.
   * - Filesystem
     - ``simulations/<basename>.zarr/``
     - Spatial fields written **only** for promoted trials.
   * - Filesystem
     - ``simulations/<basename>.parquet/``
     - Detailed timeseries, budgets, mass balance for promoted
       trials only.
   * - Filesystem
     - ``<project>/figures/<session_id>/``
     - PNG figures rendered post-loop via the display registry.
   * - Filesystem
     - ``<project>/reports/<session_id>/report.html``
     - HTML report rendered by ``hmp report <session_id>``.

Rule of thumb: **RAM inside the loop, DuckDB for the trace, Zarr /
Parquet only for promoted runs.**

.. list-table::
   :header-rows: 1

   * - Artefact
     - Lives in
     - Written when
   * - Simulated vector aligned on observations
     - RAM only
     - Each ``run_trial_light``: discarded at end of trial
   * - Per-station scalar metrics (NSE, KGE, RMSE)
     - ``calibration_iterations.metrics`` (JSON column)
     - After each trial
   * - Session metadata
     - ``calibration_sessions`` (1 row / session)
     - Start + finalize
   * - Parameters + scalar objective
     - ``calibration_iterations`` (sim_id NULL by default)
     - After each trial
   * - ``params_hash``
     - Column in ``calibration_iterations``
     - After each trial
   * - Spatial fields ``head(x, y, t)``
     - ``simulations/<basename>.zarr/`` or ``.zarr.zip``
     - **Only** via ``promote_trial``
   * - Detailed timeseries (head, Q)
     - ``simulations/<basename>.parquet/timeseries.parquet``
     - **Only** via ``promote_trial``
   * - Figures (PNG)
     - ``<workspace>/projects/<name>/figures/<session_id>/``
     - Post-loop via Display registry
   * - HTML report
     - ``<workspace>/reports/<session_id>/report.html``
     - ``hmp report <session_id>``

Disk-space cheat sheet for a representative 100-trial session on a
moderately fine mesh:

.. list-table::
   :header-rows: 1

   * - ``save_runs``
     - DuckDB
     - Zarr dirs
     - Parquet dirs
     - Typical total
   * - ``none``
     - 100 iter + 1 session
     - 0
     - 0
     - ~500 KB
   * - ``best_n = 5``
     - 100 iter + 5 sim + 5 param + 5 metric + 1 session
     - 5
     - 5
     - ~2.5 GB
   * - ``all``
     - 100 iter + 100 sim + ...
     - 100
     - 100
     - ~50 GB

**Recommendation.** Use ``save_runs = "best_n"`` as your default. It
keeps the full trace queryable in DuckDB while only materializing the
trials you might actually inspect later. Use ``"all"`` only for short
diagnostic calibrations (<= 20 trials) when you want every single run
on disk.

Optimization methods
--------------------

.. list-table::
   :header-rows: 1

   * - Method
     - Type
     - Typical budget
     - Deterministic
     - Strength
     - When to pick it
   * - ``grid``
     - Enumeration
     - Product of ``n_points``
     - Yes
     - Simple, exhaustive
     - 1-2 params, unlimited budget
   * - ``optuna`` (default TPE)
     - Light Bayesian
     - 50-200
     - Seed-dependent
     - Adaptive, easy
     - Sensible default
   * - ``optuna`` (``sampler="cmaes"``)
     - Evolutionary
     - 100-500
     - Seed-dependent
     - Continuous multi-dim
     - 3+ continuous params
   * - ``scipy_de``
     - Evolutionary
     - 100-500
     - Seed-dependent
     - Robust
     - Alternative to Optuna CMA-ES
   * - ``scipy_nelder_mead``
     - Local simplex
     - 50-100
     - Partially
     - Fast local
     - Refine around a known optimum
   * - ``gp_mapping`` (Phase 4)
     - GP surrogate + EI
     - 30-100
     - Seed-dependent
     - Few expensive evaluations
     - Slow solvers
   * - ``da_mh_gp`` (Phase 4)
     - MCMC + GP surrogate
     - 1000+
     - No
     - Full posterior
     - Uncertainty quantification

``optimizer_kwargs`` hints:

- ``grid``: ``{ "n_points": {K = 10, Sy = 5} }`` to set per-parameter
  granularity. Defaults to a uniform count across all parameters.
- ``optuna``:
  ``{ "sampler": "tpe" | "cmaes" | "random", "pruner": "median" }``.
  Default sampler is TPE and is available in the base install; ``cmaes``
  requires the calibration extra and is strongly recommended when you
  have 3+ continuous parameters.
- ``scipy_de``:
  ``{ "popsize": 15, "mutation": [0.5, 1.0], "recombination": 0.7 }``,
  the standard ``scipy.optimize.differential_evolution`` knobs.
- ``scipy_nelder_mead``:
  ``{ "xatol": 1e-4, "fatol": 1e-4, "adaptive": true }``.
  ``adaptive = true`` is friendlier in higher dimensions.
- ``gp_mapping``: ``{ "n_initial": 10, "acq": "ei" }``: expected
  improvement over an RBF Gaussian Process surrogate.
- ``da_mh_gp``:
  ``{ "burn_in": 200, "thin": 5, "proposal_scale": 0.3 }``,
  Metropolis-Hastings tuned by the surrogate.

Reading the results
-------------------

Python API and DuckDB
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import hydromodpy as hmp

   catalog = hmp.open("~/workspace")
   sessions = catalog.calibration_sessions()
   iters = catalog.calibration_iterations(session_id=sessions.iloc[0]["session_id"])
   best = catalog.best(project="calibration", metric="nse")
   best.plot("watertable_map", save="~/figures/")
   print(iters.head())

- ``catalog.calibration_sessions()`` returns a ``DataFrame`` with one
  row per session (method, objective, best_objective, duration_s).
- ``catalog.calibration_iterations(session_id=...)`` returns the full
  per-trial trace (parameters, objective_value, status, sim_id,
  params_hash).
- ``catalog.best(project, metric)`` returns a ``Run`` object for the
  best promoted trial across sessions matching ``project``.

Figures via the display registry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Six named figures ship with HydroModPy. Each implements the ``Figure``
Protocol and is registered in
``hydromodpy/display/figures/__init__.py``.

- ``calibration_convergence``: best-so-far objective vs iteration.
- ``calibration_trace``: parallel plots of every parameter and the
  objective across iterations.
- ``calibration_landscape``: 2D scatter of any pair of parameters
  coloured by objective value.
- ``calibration_posterior``: marginal histograms per parameter.
- ``calibration_objective_surface``: interpolated NSE surface over
  any 2-parameter slice.
- ``calibration_pairplot``: pairwise grid of scatter plus
  histograms.

Render one figure at a time from the CLI (the session id is printed on
stderr during ``hmp run``):

.. code-block:: bash

   hmp display run_calibration_k.toml --session <session_id> --figure calibration_convergence
   hmp display run_calibration_k.toml --session <session_id> --figure calibration_trace
   hmp display run_calibration_k.toml --session <session_id> --figure calibration_landscape
   hmp display run_calibration_k.toml --session <session_id> --figure calibration_posterior
   hmp display run_calibration_k.toml --session <session_id> --figure calibration_objective_surface
   hmp display run_calibration_k.toml --session <session_id> --figure calibration_pairplot

Pre-rendered examples for a Dupuit / MODFLOW 6 twin benchmark live
under ``docs/source/_static/capability_gallery/calibration/``: reuse
them as visual references.

The loop can also render figures automatically at the end of the
session by listing them under ``[display] figures = [...]`` in the
TOML.

HTML report
~~~~~~~~~~~

For users who do not want to drop into Python:

.. code-block:: bash

   hmp report <session_id>
   xdg-open ~/workspace/reports/<session_id>/report.html

The report embeds the six figures together with a summary table
(method, objective, best parameters, best_sim_id, duration). It is
fully standalone: the HTML file plus its sibling PNGs can be shipped
as a single folder.

Cross-session cache and reproducibility
---------------------------------------

Every trial is fingerprinted by a ``params_hash``: the SHA-256 of its
canonical parameter JSON representation (keys sorted, floats
normalized). The hash is written on every ``calibration_iterations``
row.

- ``use_cache = true`` (default): before running a trial, the engine
  looks up ``params_hash`` in the ``ParamsHashCache``. The cache is
  preloaded at session start from every *completed* and *promoted*
  iteration of every previous session on the same workspace. On a
  hit, the ``sim_id`` is reused, the solver is skipped entirely, and
  the cached objective value is returned.
- ``seed = 42``: seeds the sampler. Combined with a deterministic
  solver, this makes the whole sequence reproducible. Leave ``null``
  for stochastic exploration.

Disable the cache (``use_cache = false``) when:

- the input data changed (new forcings, new DEM, new observations);
- the solver version changed;
- you want to benchmark true per-trial wall time.

Common pitfalls and how to avoid them
-------------------------------------

- **``path`` points to a missing field.** The engine raises a
  ``CalibrationSetupError`` with the list of valid paths.
  Double-check with ``hmp doctor --toml run_calibration_k.toml``.
- **Bounds too tight.** The optimizer converges on a plateau and
  reports a false "best". Widen ``bounds`` and re-run.
- **``transform = "identity"`` for K from 1e-6 to 1e-3.** Uniform
  sampling in the physical space burns 99% of the budget on the top
  decade. Always use ``transform = "log"`` for multi-order quantities
  (K, conductances, storage coefficients).
- **``save_runs = "all"`` on 100 trials.** You end up with ~50 GB of
  Zarr. Use ``best_n`` unless you really want every trial on disk.
- **``max_iter`` too low for a Bayesian method.** Optuna TPE needs
  at least ~50 trials before exploiting; ``da_mh_gp`` needs a few
  hundred before the posterior stabilizes.
- **Variable ``"discharge"`` but no hydrometry in ``[data]``.** The
  metric extractor returns ``NaN`` on every trial; the session
  completes in seconds with no usable output. Check that
  ``[data.hydrometry]`` (or ``[data.piezometry]`` for head) is
  populated.
- **MODFLOW 6 + discharge calibration.** The extractor in
  ``hydromodpy.calibration.metrics`` currently covers MODFLOW-NWT
  only; MODFLOW 6 returns ``NaN``. Scheduled as future work: use
  MODFLOW-NWT in the meantime, or plug in a custom extractor through
  §10.
- **Forgetting ``[workflow].mode = "calibration"``.** ``hmp run``
  then treats the TOML as a simulation and runs ``K`` exactly once
  with its default value. The ``[calibration]`` section is silently
  ignored.

Python API reference
--------------------

Programmatic entry point (no CLI needed):

.. code-block:: python

   from hydromodpy.calibration.cli_runner import run_calibration_cli

   summary = run_calibration_cli(
       "run_calibration_k.toml",
       objective="mypkg.metrics:custom_nse",
       workspace="~/workspace",
       project="nancon_K",
   )
   print(summary["best_sim_id"], summary["best_objective"])

- The positional argument is the TOML path; resolved relative to the
  current working directory.
- ``objective="module.path:fn"`` is the Python escape hatch. The
  callable must match the ``TrialMetricFn`` signature
  ``(ctx, *, objective, variable) -> (primary_metric, {component: value})``.
  Use it when the default NSE / KGE / RMSE extractor does not fit
  your variable (multi-station weighted, filtered seasons, etc.).
- ``workspace`` overrides the workspace root resolved from the TOML
  (same rule as the binary resolver in ``WorkspaceConfig``).
- ``project`` is a free string written to
  ``calibration_sessions.project``.

Return dict keys:

.. code-block:: text

   session_id, method, n_iterations, best_objective,
   best_sim_id, duration_s, save_runs, promoted

Low-level primitives
~~~~~~~~~~~~~~~~~~~~

The CLI is a thin wrapper around three primitives you can call
directly for custom orchestration:

.. code-block:: python

   from hydromodpy.simulation.execution.trial import (
       prepare_trials, run_trial_light, promote_trial,
   )

   trial_ctx = prepare_trials(
       "run_calibration_k.toml",
       override_paths={"K": "flow.param.K.field.value"},
   )
   result = run_trial_light(
       trial_ctx, {"K": 1e-4},
       objective="nse", variable="discharge",
   )
   if result.status == "completed":
       sim_id = promote_trial(
           "run_calibration_k.toml",
           {"K": 1e-4},
           paths={"K": "flow.param.K.field.value"},
           name="manual_k_1e-4",
       )

Useful diagnostics on a persisted trace:

.. code-block:: python

   from hydromodpy.calibration.diagnostics import (
       convergence_rate, parameter_correlation,
   )

   rate = convergence_rate(iters)
   print(rate["slope"], rate["r_squared"])
   corr = parameter_correlation(iters, parameters=["K", "Sy"])
   print(corr)

Render a specific figure programmatically (equivalent to the
``hmp display`` call above):

.. code-block:: python

   from pathlib import Path
   import hydromodpy as hmp

   catalog = hmp.open("~/workspace")
   fig = hmp.display.get("calibration_convergence").plot(
       session_id="abcd1234ef...",
       catalog=catalog,
       save_path=Path("~/figures/convergence.png").expanduser(),
   )

Analytical test cases
~~~~~~~~~~~~~~~~~~~~~

Two pure-Python demos ship for local experimentation (no MODFLOW
install needed):

- ``hydromodpy.calibration.cases.recession_brutsaert``: hydrograph
  recession fit (``Q(t) = Q0 * exp(-t/tau)``) used as the golden for
  ``grid_search``, ``random_search``, ``nelder_mead``, ``simplex``,
  ``cma_es``, ``gp_mapping``, ``da_mh_gp``.
- ``hydromodpy.calibration.cases.groundwater_1d``: 1D synthetic
  aquifer with analytical head profile.

They are the quickest way to check that a new optimizer adapter
behaves against the known-good ``METHOD_ABS_TOL`` tolerances.

See also
--------

- :doc:`index` for the calibration architecture root.
- :doc:`calibration-architecture` for the package map and every UML
  diagram (config, runtime, execution flows, case structure).
- :doc:`../../user_guide/workflows/calibration` for the user-facing hub.
- :doc:`../../theory/calibration/index` for the inverse-problem
  formulation and methods.
- :doc:`../../capability_gallery/calibration` for stable benchmark
  pages.
