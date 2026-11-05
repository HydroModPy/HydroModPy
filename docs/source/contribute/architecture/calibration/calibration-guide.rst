How the calibration engine runs
===============================

This page is for a contributor who changes the calibration code in
``hydromodpy/calibration/``. It says how a calibration file becomes trials,
which pipeline steps a trial replays, what is written where, how the cache
recognizes a trial, and what a bisection reports about itself. Every method and
metric is listed from the code in :doc:`/reference/calibration-methods`; the package
map and the diagrams are in :doc:`calibration-architecture`.

The loop
--------

A calibration is an ask/tell loop. An optimizer adapter proposes points
(``ask``), the engine evaluates them, and the costs go back (``tell``). The
adapters live in ``calibration/optim/adapters/`` and register with
``@register_optimizer``; :doc:`../how-to/add-a-calibration-method` says how to
add one. Each adapter declares ``EngineTraits``: how many parameters it moves,
the search space it needs, whether it reads a signed residual, whether it stops on
a precision and which of its options that precision writes, whether it can run
trials side by side, start from a passed value, or be restarted usefully, and
the metric it reads its cost as. The preflight (``calibration/preflight.py``)
faces every search with these traits, phase by phase with the overrides of each
phase, before anything is prepared. Every launch runs it first (``hmp calibrate``,
``hmp run``, ``--dry-run``, ``hmp.calibrate``, ``Project.calibrate``), on the
document the launch runs, ``--set``, ``--overlay`` and ``HMP_SET_*`` included,
and ``hmp config check`` prints it. The reference page renders the traits.

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

``hmp.calibrate`` and ``Project.calibrate`` always return a ``CalibrationReport``, with or
without phases: ``best_cost``, ``best_parameters``, ``best_cases``, ``phases``, ``frozen``,
``windows``, and the properties ``session``, ``best``, ``best_by_case`` and ``trials``, which read
the session on disk. ``hmp.calibration_phases`` says what a file declares, with nothing run: its
phases, the section a protocol unfolds into and what a launch would write. The same words read a
session later: ``proj.sessions["<case>"].best`` is the run of a session of one case, and a session
of several cases refuses it and names ``best_by_case``.

A staged calibration runs one session per phase. Each ``session.json`` carries
the phase name, its index and its parent session, so a rebuilt index gives the
chain back. A phase whose search settled freezes its values
(``FrozenParameter``, with the configuration path) for the phases after it.
The search settled when its engine met its own rule or solved every point of
its plan, or when an engine with no rule of its own (``random_search``,
``cma_es``) spent its budget; that phase says it froze the best of a
budget-only search. A phase whose engine has a rule the budget stopped first
freezes nothing, and a phase that depends on it is refused. The rule is
``settled`` in ``optim/stopping.py``, and the session closes ``completed`` by
the same rule.

What a trial replays
--------------------

Every pipeline step declares the configuration subtrees it reads in a
``config_sections`` class variable. ``workflow/steps/dependencies.py:
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
     - ``domain.supports``, ``mesh``
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
criterion is normalized by.

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
   * - Session identity, cases, bounds, periods, best trial, root-search bracket
     - ``sessions/<session>/session.json``
   * - Series of every trial, when ``persist_trial_series`` is set
     - ``sessions/<session>/trial_series/trial-NNNNNN.parquet``
       (:toml:`calibration.persist_trial_series`)
   * - Fields, tables, figures of a promoted trial
     - ``runs/<run>/``
   * - The index
     - ``calibration_sessions``, ``calibration_session_cases``, ``calibration_iterations``
       and ``calibration_trial_cases`` in
       ``.hmp/index.duckdb``, derived from the two journal files

``calibration_trial_cases.sim_id`` is written before a promotion replays the
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
returns the stored cost. The key holds only what changes the cost of a trial at
given values (the model, its inputs, the content of the maps a network output is scored
against, the outputs, the objective blocks and the scoring window), so a re-run with a
larger ``max_trials``, another method, seed, precision or narrower phase ``bounds``
replays the trials it proposes at values already solved. Turn it off when the inputs,
the observations or the solver version changed, or to time the trials.

What a search reports about itself
----------------------------------

Every ``CalibrationReport`` carries two records in ``extra``:

``extra["search"]``
   ``{stop_state, converged, stopping_rule, max_trials, extension, n_evaluations}``,
   whichever engine ran. ``stop_state`` is ``rule_met``, ``plan_exhausted`` or
   ``budget_spent``, and ``converged`` is true for the first two only.
   ``stopping_rule`` is the option the engine stops on, ``every grid point`` or
   ``every design point`` for a design, or ``"budget"``. A staged run reads
   ``stop_state`` and ``stopping_rule`` to decide what to freeze. The stop
   state is sealed in ``session.json``, in each phase and in
   ``checks.calibrated_by`` of the promoted run.

``extra["bracket"]``
   ``{parameter, low, high, relative_width, closed}``, in physical units, once
   a bisection has found a sign change. It is what the search proved about the
   root. It differs from ``parameter_intervals``, which reads a ``cost_margin`` on
   the trials after the fact: for a root, where the cost against the log of the
   value crosses the margin, by a straight line between two trials. Each end says
   ``crossed``, ``bound`` or ``open``, and ``widths`` in ``session.json`` keeps it.

The trial a bisection returns is the lowest-cost completed trial inside the
final bracket, ends included. A rejected trial that set an end of the bracket
can be the closest to zero without being returned, because it lies outside
what the bracket closed on. Costs within a tight float tolerance count as a
tie, and a tie goes to the trial nearest the middle of the bracket. A trial
outside the bracket is returned only when no completed trial lies inside it,
and a warning says so.

``max_trials = "auto"`` is resolved by ``optim/stopping.py``: an engine that
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
``convergence_rate`` fits the decrease of the best cost, and no report reads
it. ``parameter_correlation`` gives the correlation of the parameters over the
trials, and ``correlated_parameter_pairs`` the pairs past the threshold, the
source of the ``moved together`` caution.

Test cases without a solver
---------------------------

``validation_cases/calibration/recession_hillslope_aquifer/experiment.py`` fits a
recession :math:`Q(t) = Q_0 e^{-t/\tau}` and
``validation_cases/calibration/unconfined_interface_1d/experiment.py`` a one-dimensional
aquifer with an analytical head profile. Neither needs MODFLOW,
so they are the quickest way to check a new adapter against known answers. The
calibration validation cases, which find a known truth with the real forward
model, are listed in :doc:`/theory/validation`.

See also
--------

- :doc:`calibration-architecture`: package map and diagrams.
- :doc:`../how-to/add-a-calibration-method`: register a new engine.
- :doc:`/theory/calibration/inverse-problem-formulation`: what is minimized.
