Calibration internals
=====================

This note is for a contributor who changes ``hydromodpy/calibration/``. It says how a file
becomes trials, which pipeline steps a trial replays, what is written where, how the cache
recognizes a trial and what a search reports. The package map and the ten steps of a session are
on :doc:`../packages/calibration`, the methods in :doc:`/reference/calibration-methods`, the
phases in :doc:`/how-to/write-calibration-phases` and the mathematics in
:doc:`/theory/calibration/inverse-problem-formulation`.

The loop
--------

A calibration is an ask/tell loop. An optimizer adapter proposes points (``ask``), the engine
evaluates them, and the costs go back (``tell``). The engine decides when to stop. The model
run, the catalog and the promotion all happen in the evaluator. An adapter is one module of
``calibration/optim/adapters/``, and :doc:`../how-to/add-a-calibration-method` says how to add
one.

Each adapter declares ``EngineTraits`` in ``calibration/optim/optimizer.py``, such as the
parameters it moves, whether it stops on a precision and whether it can run trials side by
side. The preflight (``calibration/preflight.py``) faces every search with these traits, phase
by phase, before anything is prepared. Every launch runs it on the document it will run, with
``--set``, ``--overlay`` and ``HMP_SET_*`` included.

From the file to the trials
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Stage
     - What it does
   * - Dispatch
     - ``run_calibration`` in ``project/dispatch/workflow.py`` reads ``[workflow].mode =
       "calibration"``. A file with ``[[calibration.phases]]`` goes to
       ``run_staged_calibration`` of ``runners/staged_runner.py``, any other to
       ``run_calibration_cli`` of ``runners/cli_runner.py``. A protocol is expanded into
       phases first (``calibration/protocols``).
   * - ``prepare_trials``
     - Runs the pipeline steps before ``earliest_affected_step`` once and holds the prepared
       context in memory (``TrialContext``).
   * - ``run_trial_light``
     - Forks the context, writes the parameter values into a copy of the configuration,
       replays the remaining steps up to ``extract`` and scores the objective in memory. The
       session writes the events of the trial. A trial after the first of a lane starts from
       the last solved trial of that lane (``runners/lanes.py``) and only solves again.
   * - Promotion
     - After the loop, ``runners/promotion.py`` (``promote_phase_best``) replays the chosen
       trials through the whole pipeline, so they get fields, tables, figures and exports.

A staged calibration runs one session per phase. Each ``session.json`` carries the phase name,
its index and its parent session, so a rebuilt index gives the chain back. A phase whose search
settled freezes its values (``FrozenParameter`` in ``report.py``) for the phases after it. The
rule is ``settled`` in ``optim/stopping.py``, and the session closes ``completed`` by the same
rule. A search settled when its engine met its own rule or solved every point of its plan.
An engine with no rule of its own (``random_search``, ``cma_es``) settles by spending its
budget, and its phase says it froze the best of a budget-only search. An engine whose rule the
budget stopped first freezes nothing, and a phase that depends on it is refused.

What a trial replays
--------------------

Every pipeline step declares the configuration subtrees it reads in a ``config_sections``
class variable. ``earliest_affected_step`` in ``workflow/steps/dependencies.py`` takes the
parameter paths of the search and returns the lowest index of a step whose section is a dotted
prefix of one of them. Everything from there on is replayed per trial, even a step whose own
sections do not match, because it reads the state of the step before it. The order of the steps
is ``standard_steps`` in ``workflow/steps/sequence.py``.

A trial of :toml:`flow.param.K.field.value` replays ``prepare_solver``, ``run_solver`` and
``extract``. A trial of :toml:`domain.depth_model.thickness` replays from ``setup_process``.
The steps from ``derive`` on run for promoted runs only.

A mesh setting is refused as a calibration parameter, because a finer mesh also moves the
yardstick of the network criterion.

Storage
-------

The simulated series live in memory and are dropped at the end of the trial. Only scalars reach
disk, in ``sessions/<session>/``. ``trials.jsonl`` gets one line per event (``proposed``,
``finished``, ``linked``) and is folded to one line per trial when read, so an interrupted
search keeps what it asked and what it evaluated. ``session.json`` is written before the first
trial and rewritten at the end. :toml:`calibration.persist_trial_series` adds ``trial_series/``.
The tables of ``.hmp/index.duckdb`` derive from the two journal files, and
``hmp catalog reindex`` rebuilds them. The contract is in
:doc:`/contribute/architecture/storage-layout`.

``calibration_trial_cases.sim_id`` is written before a promotion replays the trial, because the
display step of the promoted run draws the calibration figures only when an iteration row names
that run. A failed promotion clears the link. The best trial is promoted as ``<name>_<phase>``,
or ``<name>`` for one phase. Another kept trial is ``<name>_<phase>_trial_<iteration>``.

The cache across sessions
-------------------------

``params_hash`` in ``optim/cache.py`` is a SHA-256 of the canonical parameter record of a
trial. With :toml:`calibration.use_cache` on, which is the default, ``ParamsHashCache`` is
loaded at session start from the completed and promoted iterations of the earlier sessions of
the project. A hit skips the solver and returns the stored cost.

The key holds only what changes the cost at given values: the model, its inputs, the maps a
network output is scored against, the outputs, the objective blocks and the scoring window. So a
re-run with a larger ``max_trials``, another method, seed or precision, or narrower phase
``bounds``, replays at once the trials it proposes at values already solved. Turn the cache off
when the inputs, the observations or the solver version changed, or to time the trials.

What a search reports about itself
----------------------------------

Every ``CalibrationReport`` carries two records in ``extra``.

``extra["search"]`` holds ``stop_state``, ``converged``, ``stopping_rule``, ``max_trials``,
``extension`` and ``n_evaluations``. The stop state is ``rule_met``, ``plan_exhausted`` or
``budget_spent``, and ``converged`` is true for the first two only. A staged run reads the stop
state and the stopping rule to decide what to freeze. The stop state is sealed in
``session.json``, in each phase and in ``checks.calibrated_by`` of the promoted run.

``extra["bracket"]`` exists once a bisection has found a sign change. It holds the parameter,
the two ends in physical units, the relative width and whether the bracket closed, which is what
the search proved about the root. ``parameter_intervals`` is another record, read from a
``cost_margin`` on the trials after the fact.

The trial a bisection returns is the lowest-cost completed trial inside the final bracket, ends
included. A rejected trial that set an end can be closer to zero without being returned, because
it lies outside what the bracket closed on. Costs within a tight float tolerance tie, and a tie
goes to the trial nearest the middle. A trial outside the bracket is returned only when none
lies inside, and a warning says so.

``max_trials = "auto"`` is resolved by ``optim/stopping.py``. An engine that publishes a
``CountedBudget`` (the bisection, the Latin hypercube) gets its worst case, and any other engine
gets a fixed default.

Driving the primitives from Python
----------------------------------

The runners are thin wrappers around two primitives of ``runners/trial.py``, for a custom loop.

.. code-block:: python

   from hydromodpy.calibration.runners.trial import prepare_trials, run_trial_light

   paths = {"K": "flow.param.K.field.value"}
   ctx = prepare_trials("run_calibration.toml", override_paths=paths)
   result = run_trial_light(ctx, {"K": 1e-4}, objective="nse", variable="discharge")

``promote_trial`` of ``hydromodpy/project/calibrate.py`` turns one stored trial into a run. The
cases of ``validation_cases/calibration/`` that need no MODFLOW check a new adapter fastest.
