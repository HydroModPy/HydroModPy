How the calibration engine runs
===============================

This page is for a contributor who changes the calibration code in
``hydromodpy/calibration/``. It says how a calibration file becomes trials,
which pipeline steps a trial replays, what is written where, how the cache
recognises a trial, and what a bisection reports about itself. Every method and
metric is listed from the code in :doc:`/reference/calibration-methods`; the package
map and the diagrams are in :doc:`calibration-architecture`.

The loop
--------

A calibration is an ask/tell loop. An optimizer adapter proposes points
(``ask``), the engine evaluates them, and the costs go back (``tell``). The
adapters live in ``calibration/optim/adapters/`` and register with
``@register_optimizer``; :doc:`../how-to/add-a-calibration-method` says how to
add one. Each adapter declares ``EngineTraits``: how many parameters it moves,
the transform it needs, whether it reads a signed residual, whether it stops on
a precision and which of its options that precision writes, whether it can run
trials side by side, start from a passed value, or be restarted usefully, and
the metric it reads its cost as. ``hmp calibrate --check``
(``calibration/preflight.py``) faces every search with these traits before
anything solves, and the reference page renders them.

Specific terms:

- ``TrialContext``: the prepared runtime every trial of a session forks.
- ``earliest_affected_step``: the first pipeline step a parameter path touches.
- ``params_hash``: the fingerprint of one trial, used by the cache.
- ``promote_trial``: the replay of a trial as a full run.

From the file to the trials
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Stage
     - What it does
   * - Dispatch
     - ``hmp run`` or ``hmp calibrate`` reads ``[workflow].mode =
       "calibration"``. A file with ``[[calibration.phases]]`` goes to
       ``runners/staged_runner.py:run_staged_calibration``, any other to
       ``runners/cli_runner.py:run_calibration_cli``. A protocol is expanded
       into phases first (``calibration/protocols``).
   * - ``prepare_trials``
     - Runs the pipeline steps before ``earliest_affected_step`` once, and
       holds the prepared context in memory.
   * - ``run_trial_light``
     - Forks the context, writes the parameter values into a copy of the
       configuration, replays the remaining steps up to ``extract``, scores the
       objective in memory, appends one line to ``trials.jsonl`` and one row to
       the index.
   * - ``promote_trial``
     - After the loop, replays the chosen trials through the whole pipeline
       with ``Project.simulate``, so they get fields, tables, figures and
       exports.
   * - Session journal
     - ``sessions/<session>/session.json`` is written before the first trial
       and rewritten at the end; ``trials.jsonl`` grows one line per trial, so
       an interrupted search keeps what it evaluated. ``hmp catalog reindex``
       rebuilds the index from these files.

A staged calibration runs one session per phase. Each ``session.json`` carries
the phase name, its index and its parent session, so a rebuilt index gives the
chain back. A phase that converges freezes its values (``FrozenParameter``,
with the configuration path) for the phases after it; one that does not
freezes nothing, and a phase that depends on it is refused.

What a trial replays
--------------------

Every pipeline step declares the configuration subtrees it reads in a
``config_sections`` class variable. ``workflow/internals/dependencies.py:
earliest_affected_step`` takes the parameter paths of the search and returns
the lowest index of a step whose section is a dotted prefix of one of them.
Everything from there on is replayed per trial, even a step whose own sections
do not match, because it reads the state the step before it produced.

.. list-table::
   :header-rows: 1
   :widths: 8 18 18 56

   * - Index
     - Step
     - During a calibration
     - ``config_sections``
   * - 0
     - ``validate``
     - once
     - ``workspace``, ``simulation``
   * - 1
     - ``resolve``
     - once
     - ``workspace``, ``simulation``
   * - 2
     - ``build_geographic``
     - once
     - ``geographic``, ``data.dem``
   * - 3
     - ``load_data``
     - once
     - ``data``
   * - 4
     - ``build_mesh``
     - once
     - ``domain.supports``, ``mesh_catchment``, ``mesh_input``
   * - 5
     - ``setup_process``
     - once, or per trial for a depth-model parameter
     - ``domain.depth_model``, ``flow.ic``, ``simulation``
   * - 6
     - ``prepare_solver``
     - per trial
     - the flow, transport and solver sections
   * - 7
     - ``run_solver``
     - per trial
     - ``flow``, ``transport``, ``solver``, ``modflownwt``, ``modflow6``
   * - 8
     - ``extract``
     - per trial
     - none
   * - 9 to 11
     - ``derive``, ``display``, ``export``
     - promoted runs only
     - ``postprocess``, ``display``, none

A trial of ``flow.param.K.field.value`` therefore replays steps 6 to 8. A trial
of ``domain.depth_model.thickness`` replays from step 5. The mesh step reads
its sections from the raw file once, so a mesh setting is refused as a
calibration parameter: refining the mesh also moves the yardstick the network
criterion is normalised by.

Storage
-------

Inside the loop, the simulated series aligned on the observations live in
memory and are dropped at the end of the trial. Only scalars reach disk:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Written
     - Where
   * - Parameters, cost, per-block costs, diagnostics, ``params_hash``
     - ``sessions/<session>/trials.jsonl``, one line per trial
   * - Session identity, search space, best trial, root-search bracket
     - ``sessions/<session>/session.json``
   * - Series of every trial, when ``persist_trial_series`` is set
     - ``sessions/<session>/trial_series/trial-NNNNNN.parquet``
       (:toml:`calibration.persist_trial_series`)
   * - Fields, tables, figures of a promoted trial
     - ``runs/<run>/``
   * - The index
     - ``calibration_sessions`` and ``calibration_iterations`` in
       ``.hmp/index.duckdb``, derived from the two journal files

``calibration_iterations.sim_id`` is written before a promotion replays the
trial, not after: the display step of the promoted run draws the calibration
figures only when an iteration row names that run. A promotion that fails
clears the link. The best trial is promoted as ``<name>_<phase>``, or
``<name>`` for a calibration of one phase, and another kept trial as
``<name>_<phase>_trial_<iteration>``. The storage contract as a whole is in
:doc:`/contribute/architecture/storage-layout`.

The cache across sessions
-------------------------

Each trial is fingerprinted by ``optim/cache.py:params_hash``, a SHA-256 of
its canonical parameter record. With ``use_cache`` on (the default), the
``ParamsHashCache`` is loaded at session start from the completed and promoted
iterations of the earlier sessions of the project. A hit skips the solver and
returns the stored cost. This is what lets a re-run with a larger ``max_iter``
replay the trials already solved. Turn it off when the inputs, the observations
or the solver version changed, or to time the trials.

What a search reports about itself
----------------------------------

Every ``CalibrationReport`` carries two records in ``extra``:

``extra["search"]``
   ``{converged, stopping_rule, max_iter, extension, n_evaluations}``,
   whichever engine ran. ``stopping_rule`` is the option the engine stopped on,
   or ``"budget"``. A staged run reads ``converged`` to decide what to freeze.

``extra["bracket"]``
   ``{parameter, low, high, relative_width, closed}``, in physical units, once
   a bisection has found a sign change. It is what the search proved about the
   root. It differs from ``parameter_intervals``, which reads a tolerance on
   the trials after the fact.

The trial a bisection returns is the lowest-cost completed trial inside the
final bracket, ends included. A rejected trial that set an end of the bracket
can be the closest to zero without being returned, because it lies outside
what the bracket closed on. Costs within a tight float tolerance count as a
tie, and a tie goes to the trial nearest the middle of the bracket. A trial
outside the bracket is returned only when no completed trial lies inside it,
and a warning says so.

``max_iter = "auto"`` is resolved by ``optim/stopping.py``: an engine that
publishes a ``CountedBudget`` (the bisection, the Latin hypercube) is granted
its worst case, and any other engine a fixed default.

Driving the primitives from Python
----------------------------------

The runners are thin wrappers around three primitives, for a custom loop:

.. code-block:: python

   from hydromodpy.calibration.runners.trial import (
       prepare_trials, promote_trial, run_trial_light,
   )

   trial_ctx = prepare_trials(
       "run_calibration.toml",
       override_paths={"K": "flow.param.K.field.value"},
   )
   result = run_trial_light(
       trial_ctx, {"K": 1e-4}, objective="nse", variable="discharge",
   )
   if result.status == "completed":
       promote_trial(
           "run_calibration.toml",
           {"K": 1e-4},
           paths={"K": "flow.param.K.field.value"},
           name="manual_k_1e-4",
       )

``calibration/optim/diagnostics.py`` reads a persisted trace:
``convergence_rate`` fits the decrease of the best cost, and
``parameter_correlation`` gives the correlation of the parameters over the
trials, the source of the ``moved together`` caution.

Test cases without a solver
---------------------------

``calibration/cases/recession_brutsaert.py`` fits a recession
:math:`Q(t) = Q_0 e^{-t/\tau}` and ``calibration/cases/groundwater_1d.py`` a
one-dimensional aquifer with an analytical head profile. Neither needs MODFLOW,
so they are the quickest way to check a new adapter against known answers. The
calibration validation cases, which find a known truth with the real forward
model, are listed in :doc:`/theory/validation`.

See also
--------

- :doc:`calibration-architecture`: package map and diagrams.
- :doc:`../how-to/add-a-calibration-method`: register a new engine.
- :doc:`/theory/calibration/inverse-problem-formulation`: what is minimised.
