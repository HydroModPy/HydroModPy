Package: calibration
====================

.. include:: ../../../../../hydromodpy/calibration/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: calibration

Inside the package
------------------

The parts
~~~~~~~~~

The parts are listed here from the lowest to the highest. A part is a subpackage or a module
at the root of the package.

- ``targets.py`` says which parameters a resolved project exposes to calibration
  (``hmp config targets``), and ``parameter_resolution.py`` says what a
  ``[calibration.parameters.<name>]`` name means as a config path, at load.
- ``criteria/`` scores one simulated series against one observed series. It holds the scoring
  kernels (``METRICS`` in ``series.py``), their conventions and the network distance.
- ``optim/`` runs the search. It holds the parameter space, the objective, the optimizer
  Protocol and registry, the engine, the stopping rules, the params-hash cache and the
  uncertainty (FOSM, cost margin). ``optim/adapters/`` holds the search methods: grid, random,
  scipy, CMA-ES, Optuna, bisection, GP mapping and DA-MH-GP.
- ``persistence.py`` writes a session, ``sessions/<case>/`` and its journal, and nothing else.
  ``report.py`` holds what a calibration returns (``CalibrationReport``,
  ``CalibrationResult``) and the words about it. The session page is not written there.
- ``evaluation/`` says what one trial must answer. It holds the evaluator port, its registry,
  and ``analytic_bowl``, the evaluator that needs nothing from the calibration document.
- ``config_terms.py``, ``config_network.py``, ``config_outputs.py``, ``config_objective.py``
  and ``config_phases.py`` are the parts of the ``[calibration]`` schema, in that order. They
  hold the shared terms and windows, the matching-network options and network outputs, the
  point outputs, the protocol, parameters and objective blocks, and the phases and the
  uncertainty. ``config.py`` builds ``CalibrationConfig``, the table the modeller wrote, from
  the five of them.
- ``protocols/`` holds the published recipes a calibration can follow and expands each into
  phases and objective blocks.
- ``observations/`` holds what is observed, the observed stream network and its geometry. It
  reads ``results/derive/stream_network/criterion_inputs.py`` and is scored by the kernels of
  ``catchment/stream_network``.
- ``metrics/`` extracts the outputs of one trial and pairs them with observations.
- ``runners/`` runs a calibration. It holds the three entry points, the phases and what they
  hand to each other, the trial primitive, the default evaluator, restarts, resume and the
  promotion of the best trials.
- ``preflight_report.py``, ``preflight_searches.py`` and ``preflight_network.py`` hold the
  finding and the report lines, the searches a document declares and the checks of the
  matching-network criterion. ``preflight.py`` runs every check of a calibration before
  anything is prepared, at the start of every launch, and ``hmp check`` prints it.

The two analytical demonstrators that the regression tests drive from Python live outside the
package, in ``validation_cases/calibration/unconfined_interface_1d/`` and
``validation_cases/calibration/recession_hillslope_aquifer/``.

Import rules
~~~~~~~~~~~~

A part imports only what its row of ``tests/unit/architecture/calibration_layout.yaml``
allows, and the layout test checks every import, at module level, inside a function and under
``TYPE_CHECKING``. A row names only rows above it, so the table cannot allow a cycle. Every
part may import the layers that ``layer_matrix.yaml`` gives calibration.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - part
     - may import
   * - ``targets``, ``criteria``
     - nothing in calibration
   * - ``parameter_resolution``
     - ``targets``
   * - ``optim``
     - ``criteria``
   * - ``persistence``
     - ``optim``
   * - ``report``
     - ``persistence``, ``optim``
   * - ``evaluation``
     - ``optim`` (types only)
   * - ``config_terms``
     - ``optim``
   * - ``config_network``
     - ``config_terms``, ``optim``
   * - ``config_outputs``
     - ``config_network``, ``config_terms``
   * - ``config_objective``
     - ``config_network``, ``config_terms``, ``optim``
   * - ``config_phases``
     - ``config_terms``, ``evaluation``
   * - ``config``
     - the five ``config_*``, and ``criteria``, ``evaluation``, ``optim`` inside validators only
   * - ``protocols``
     - ``config`` and the ``config_*`` it names
   * - ``observations``
     - ``config_network``
   * - ``metrics``
     - ``config``, ``criteria``, ``evaluation``, ``observations``, ``optim`` and the ``config_*`` it names
   * - ``runners``
     - ``config``, ``criteria``, ``evaluation``, ``metrics``, ``optim``, ``parameter_resolution``,
       ``persistence``, ``protocols``, ``report`` and the ``config_*`` it names
   * - ``preflight_report``, ``preflight_searches``, ``preflight_network``
     - ``runners`` and what their row in the layout names
   * - ``preflight``
     - inside its checks: ``criteria``, ``metrics``, ``observations``, ``optim``,
       ``parameter_resolution``, the three ``preflight_*``, ``runners``, ``targets``
   * - ``__init__.py``
     - nothing, it holds no name

Five more rules hold.

1. No module uses a ``_private`` name of another part.
2. Another layer of HydroModPy imports only the modules listed under ``public`` in
   ``calibration_layout.yaml``. They are ``hydromodpy.calibration``, ``config``, ``targets``,
   ``parameter_resolution``, ``preflight``, ``preflight_report``, ``protocols``,
   ``protocols.registry``, ``report``, ``optim.parameters``, ``runners.cli_runner``,
   ``runners.document``, ``runners.staged_report``, ``runners.staged_runner``,
   ``runners.programmatic_runner``, ``runners.trial``, ``runners.promotion``,
   ``runners.session`` and ``runners.recap``.
3. No re-export. A name is imported from the module that defines it.
4. Calibration reaches a solver only through the generic ports of ``solver.base`` (the
   registry and the observables) and the run result (``solver.base.plan.SolverRun``), never
   through a backend package (``hydromodpy.solver.modflow6``,
   ``hydromodpy.solver.modflow_nwt``, ``hydromodpy.solver.modflow_common``,
   ``hydromodpy.solver.boussinesq``). A backend can then be added or replaced
   without touching calibration. ``solver_access`` in ``calibration_layout.yaml`` checks it.
5. One exception holds. ``evaluation/registry.py`` names its built-in evaluators by a dotted
   path written as text and imports one only when a run asks for it, so checking that a
   document names a known evaluator does not import it. The evaluators that read the
   calibration document can then live above ``config`` (``runners/pipeline_evaluator.py``),
   and a third-party evaluator joins the same table.

A plugin outside HydroModPy joins through entry-point groups. An optimizer uses
``hydromodpy.calibration.optimizer`` and is written against ``optim.optimizer.Optimizer``, and
an evaluator uses ``hydromodpy.calibration.evaluator`` and is written against
``evaluation.port``. The in-tree optimizers are declared in ``_BUILTIN_PATHS`` of
``optim/optimizer.py``. The steps to add a search method are in
:doc:`../how-to/add-a-calibration-method`.

How a calibration flows
~~~~~~~~~~~~~~~~~~~~~~~

A calibration runs in ten steps.

1. Load. ``HydroModPyConfig`` validates ``[calibration]`` into ``CalibrationConfig``. A named
   protocol is expanded first (``protocols.expand_calibration_protocol``), and each parameter
   name is resolved to a config path (``parameter_resolution.resolve_parameter_targets``).
   Validators refuse an unknown criterion or evaluator here. An unknown search method loads
   and is refused by the preflight, before anything is prepared.
   ``CalibrationConfig.validate_registry`` refuses it again when the search starts, and
   resolves a method left unwritten through ``method_for`` (``optim.optimizer.choose_method``).
2. Check. Every launch (``hmp calibrate``, ``hmp run``, ``--dry-run``, ``hmp.calibrate`` and
   ``Project.calibrate``) runs ``preflight.preflight_launch`` on the document it runs, with
   ``--set``, ``--overlay`` and ``HMP_SET_*`` written in and each phase with its own
   overrides. It makes every check, gives one report and solves nothing, and an error stops the
   launch before anything is prepared. ``hmp check`` prints the same findings.
3. Start. ``runners/cli_runner.py`` and ``search.py`` (one search), ``staged_runner.py``
   (phases) or ``programmatic_runner.py`` (from Python) names the case. The case is the stem of
   the file that carries ``[calibration]``, unless the file writes ``[simulation] name``
   itself (``runners/session.py``). The runner reserves ``sessions/<case>/`` with
   ``reserve_version_dirname``, freezes the resolved document there as ``config.toml``, then
   builds the ``ParameterSpace``, the optimizer (``optim.optimizer.build_optimizer``), the
   evaluator (``evaluation.registry``) and the ``CalibrationEngine``.
4. Prepare once. ``runners/trial.py`` prepares the model once. Geography, mesh and data are
   built a single time, through the ``TrialPipeline`` that ``project`` installs. The pipeline
   finds the first pipeline step that reads one of the calibrated config paths
   (``earliest_affected_step`` of ``hydromodpy/workflow/steps/dependencies.py``). The steps
   before it run once and every trial shares them. The steps from it up to the solve and the
   extraction run again for each trial (``run_trial_light``). The persistent steps downstream
   run only for a promoted trial (``promote_prepared_trial``). The shared steps read the
   product store, so the mesh and the soil reservoir are built once and kept under
   ``<project>/.hmp/products/``, and a trial whose overrides do not touch the soil reads the
   stored soil product and never reruns the reservoir. Right after each preparation, once per
   search or per phase and before the session is reserved,
   ``runners/prepared_model.check_the_prepared_model`` checks what only the prepared model
   shows, which is a bound the field refuses and the drain and release-package conductances
   that a network search relies on.
5. Trial. The engine asks the optimizer for a point, skips it if its params hash is cached
   (``optim/cache.py``), and hands it to the evaluator. The default evaluator,
   ``runners/pipeline_evaluator.py``, sets the values, runs the solver (``run_trial_light``),
   extracts the outputs (``metrics/solver_extract.py``, ``metrics/composite.py``) and pairs
   them with the observations (``metrics/observed_pairing.py``, which calls
   ``results/score.py:pair``, the pairing a sealed run is scored with). When every calibrated
   path is a property profile (K or Sy), the first trial builds the solver model and the next
   ones of the lane go through ``rerun`` (``runners/lanes.py``). The input files of the
   previous solved trial are copied, the property file is rewritten and only the solve runs
   again. A lane serves one trial at a time, a failed trial leaves nothing to reuse, and the
   cost is the same to the bit as a build.
6. Score. ``optim/objective.py`` turns the paired series into one cost with the kernels of
   ``criteria/``, block by block, and the engine tells the optimizer.
7. Write. Each trial goes to ``sessions/<case>/trials.jsonl`` (``persistence.py``) as events,
   with a number unique in the session across phases and restarts. A ``proposed`` line is
   written when the optimizer asks, in the order of ``ask`` with its ``batch``. A ``finished``
   line carries the cost, its components, the ``rule`` and ``window`` of each case and the
   ``profile``. A ``linked`` line is written when the trial is promoted. Only the session, in
   the parent process, writes the journal. Nothing opens the index, which is rebuilt from the
   session files.
8. Promote. Once per phase, after its last restart, ``runners/promotion.py`` promotes what
   ``save_runs`` names. The best trial of the last phase becomes ``runs/<case>/``, the
   directory paired with the session (same version), with ``lineage`` and
   ``checks.calibrated_by`` naming the session, the phase and the trial. The other kept trials
   go to ``sessions/<case>/trials/<n>/``. With ``promote_phases``, the best of each earlier
   phase goes to ``sessions/<case>/phases/<phase>/best/``. A trial the session may promote
   keeps its solver folder (``runners/kept_solves.py``), and its promotion goes on from
   extraction on that folder instead of solving again. The journal line of a promoted trial
   receives the ``sim_id`` and the ``rel_dir`` of its run. ``hmp campaign promote <case>
   --trial N`` replays a trial after the fact from ``sessions/<case>/config.toml`` and the
   frozen values of its phase (``promote_trial_from_session``), and a trial kept under
   ``trials/<n>/`` is moved with the seal it was written with. ``hmp campaign prune <case>
   --keep best`` trashes the other kept trials (``prune_session``). A reopened session
   promotes once more at its end. A trial already written is not written again, and the paired
   ``runs/<case>/`` is never overwritten. When it holds another trial of the session, the new
   best is reported as a promotion failure, the session closes ``partial``, and ``hmp campaign
   promote`` writes it under the next version.
9. Close. ``session.json`` takes the status (``completed``, ``partial``, ``failed``,
   ``aborted``) and the best trial, ``outcome.json`` the issue and ``README.md`` the summary. A
   promotion failure closes a completed search ``partial`` and never ``failed``. The three
   runners close their session through one scope (``closing_session`` of
   ``runners/session_scope.py``). SIGTERM or SIGINT writes ``aborted``, marks the cut phase and
   points at the best trial of the last completed phase, or of the cut phase, in under a
   second. It then promotes that trial from its kept solve when it has one, with
   ``calibrated_by.session_status = aborted``. An error of the search writes ``failed``.
   ``hmp calibrate --resume`` reopens the latest session of the case. A phase that completed
   with the same fingerprint is read back (``runners/resume.py``), and the cut phase is solved
   again with its trials preloading the cache.
10. Report. ``hydromodpy.project.report.report_session`` writes the session report from the
    rows of ``results/session/summary.py``. ``hmp calibrate`` writes it (``--no-report`` skips
    it) and ``hmp show SESSION --report`` writes it again. ``promotion.py`` reads
    ``BOUND_TOLERANCE`` and ``on_bound`` from ``results/session/journal.py``.

What a calibration writes
~~~~~~~~~~~~~~~~~~~~~~~~~

A calibration occupies two sibling directories of one name, ``sessions/<case>/`` for what the
search evaluated and ``runs/<case>/`` for the calibrated run. What a trial writes depends on
:toml:`calibration.save_runs` (``best_n`` with :toml:`calibration.save_best_n` of 1 by
default, ``all`` or ``none``).

Inside the loop a trial lives in memory, as the aligned simulated series and the scalar
metrics, and ``run_trial_light`` never writes to the store of runs. Every trial leaves its
events in ``sessions/<case>/trials.jsonl`` (``results/session/journal.py``), numbered once
across phases and restarts. A reader folds them to one line per trial, and the highest event
wins. ``session.json`` is the descriptor and names the optimizer, its options, its seed and the
versions of its libraries. ``phases/<phase>/session.json`` is one per phase, ``outcome.json``
holds the issue and ``config.toml`` the frozen document that the promotion replays from. The
index is rebuilt from these files, and the calibration never opens it. Zarr and Parquet exist
only for promoted trials, the best under ``runs/<case>/`` and the others under
``sessions/<case>/trials/<n>/``, each linked to its journal line by ``sim_id`` and ``rel_dir``.

The params hash (``optim/cache.py``) keys the cache. It is the SHA-256 of the canonical JSON of
the rounded parameter values and of a context that fingerprints the inputs. The context holds
only what changes the cost of a trial at given values, which are the model and its inputs, the
outputs, the objective blocks, the scoring window and what the evaluator reads. The method, its
options, the seed, the precision, the budget and the bounds are outside it, so a search that
changes one of them replays the trials it proposes at values already solved. With
:toml:`calibration.use_cache` true, which is the default, a run preloads the hashes of every
``trials.jsonl`` of the project (``runners/state.py:preload_hash_cache``), so a point evaluated
in an earlier session of the same project is not solved again.

Protocols and phases
~~~~~~~~~~~~~~~~~~~~

A calibration runs as one or more phases. A phase says which parameters it moves, in which flow
regime, and against which objective blocks with which share for each. The search method follows
from what is scored. A signed criterion (``distance_gap``) on one parameter in log space is a
zero to find, searched by bisection (the stopping rule, the two roots and the budget arithmetic
are in :doc:`/theory/downslope-distance`, section "How a search reaches the zero"). Anything
else is a cost to minimize, by Nelder-Mead. That choice applies to a phase and, the same way, to
a calibration with no phases at all (``optim.optimizer.choose_method``, read through
``CalibrationConfig.method_for``). A ``method`` is written only to choose otherwise
(``"cma_es"``, ``"optuna"``, ``"grid"`` and so on). A protocol is a named recipe tied to a
publication. It writes the phases of a published method, cites it, and lets the user set its
options but not its sequence. Everything a protocol does, phases written by hand can say too,
and ``hmp calibrate FILE --expand`` prints the phases a protocol writes, as TOML to start from.

One rule links the phases, in declaration order. A phase moves the parameters it lists. Every
other parameter holds the last value an earlier settled phase found for it, or the value of the
model file when no phase has calibrated it yet. A phase that lists a parameter an earlier phase
calibrated moves it again, starting from that value when its search method accepts a start
point.

Blocks are declared once under ``[[calibration.objective_blocks]]``. A phase lists the ones it
scores, or gives each a share. Shares are normalized to sum to one, so ``{ hydrograph = 70,
network = 30 }`` reads as 70 % and 30 % of the cost. The share of a cost counts the same as an
influence only when the costs are comparable. An efficiency (``nse_log``) is a pure number and
a network distance is in meters, so ``normalize_cost = true`` is written on the network block.
Each distance is then divided by the ``validity_length`` of the output (Eq. 4, ``"auto"`` is
2 h_obs), and a gap of one validity length costs 1, as much as an NSE of 0. ``normalize_cost``
stays refused on the efficiency, which is already a pure number.

A spin-up is left out by dates. ``window.start`` on the phase, or on ``[calibration]``, is the
first date scored, for every block alike, and a series keeps its stamps inside the window. A
network output reads one state, dated at the stamp that closes its period. ``time = "last"`` is
the default, and ``"first"`` or a date such as ``"2002-10-15"`` reads the period that holds it.
The window has to hold that stamp, and ``hmp check`` says so before any solve when it does not.
The former ``warmup`` and ``warmup_periods`` counted samples, so their span followed the time
step. A file that writes them is refused with the new form, the start date of the window.

Dates can be kept apart from the search with :toml:`calibration.validation_window` on
``[calibration]``, once for the session. ``[metrics] window`` minus those dates is then the
default ``window``. Each trial is scored on them from the series it has already simulated, as
the ``validation.cost`` component, and the promoted run stores it as
``checks.calibrated_by.validation_cost`` with its period in ``windows``. The cost never reads
them. The score uses the blocks that compare a dated record, so a network block and a steady
phase are left out of it. A window that overlaps a calibration window, leaves no data or falls
outside ``[metrics] window`` is refused.

The declarations that the examples below share, since the published method writes its own
objective blocks, are these.

.. code-block:: toml

   [calibration.parameters.K]
   bounds = [1e-7, 1e-3]

   [calibration.parameters.Sy]
   bounds = [5e-3, 0.35]

   [calibration.outputs.streams]
   support = "network"

   [calibration.outputs.streams.map]
   complete = "nancon_stream_network.gpkg"

   [calibration.outputs.streams.model]
   neighbours = "D8"

   [calibration.outputs.gauge]
   support = "point"
   variable = "discharge"
   observes = "NANCON"

   [[calibration.objective_blocks]]
   name = "network"
   metric = "distance_gap"
   uses_outputs = ["streams"]

   [[calibration.objective_blocks]]
   name = "network_share"         # the same gap, counted in validity lengths
   metric = "distance_gap"
   uses_outputs = ["streams"]
   normalize_cost = true

   [[calibration.objective_blocks]]
   name = "hydrograph"
   metric = "nse_log"
   uses_outputs = ["gauge"]

K first, then Sy with K fixed. K alone in steady state against the mapped network, then Sy alone
in transient against the gauge and the network, with 2000 left out as spin-up.

.. code-block:: toml

   # not checked: fragment, continues the declarations of the first block
   [[calibration.phases]]
   name = "k_steady"
   parameters = ["K"]
   regime = "steady"              # one period over [simulation.time], or steady_window
   objective_blocks = ["network"]
   max_trials = 18

   [[calibration.phases]]
   name = "sy_transient"
   parameters = ["Sy"]            # K holds what k_steady found
   regime = "transient"
   objective_blocks = { hydrograph = 0.8, network_share = 0.2 }   # two pure numbers
   max_trials = 30

   [calibration.phases.window]
   start = "2001-01-01"           # the network state read, December 2002, lies inside

Both at once. One phase, both parameters, one regime. Two parameters and a cost to minimize give
Nelder-Mead, and ``method = "cma_es"`` is written for a global search.

.. code-block:: toml

   # not checked: fragment, continues the declarations of the first block
   [[calibration.phases]]
   name = "k_sy_transient"
   parameters = ["K", "Sy"]
   regime = "transient"
   objective_blocks = ["hydrograph"]
   max_trials = 120

In stages, then both together. A third phase after the two stages above moves K and Sy again,
starting from what they found.

.. code-block:: toml

   # not checked: fragment, continues the declarations of the first block
   [[calibration.phases]]
   name = "k_sy_refine"
   parameters = ["K", "Sy"]       # starts at k_steady's K and sy_transient's Sy
   regime = "transient"
   objective_blocks = ["hydrograph"]
   max_trials = 60

Narrower bounds in a later phase. A phase may write ``bounds`` for the parameters it moves,
inside the bounds that ``[calibration.parameters.<name>]`` gives. The first phase searches wide
and the refinement searches around what it found. A phase never widens a search, and bounds
outside the section's are refused when the file loads. ``hmp calibrate --list-phases`` prints
them.

.. code-block:: toml

   # not checked: fragment, continues the declarations of the first block
   [[calibration.phases]]
   name = "k_refine"
   parameters = ["K"]
   bounds = { K = [2e-6, 2e-5] }  # inside the bounds of [calibration.parameters.K]

The published method. The same first two stages, with the options that the paper leaves open
and its citation recorded in the session.

.. code-block:: toml

   # not checked: fragment, continues the declarations of the first block
   [calibration.protocol]
   name = "matching_hydrographic_network"
   steady_max_trials = 18
   transient_max_trials = 30

The transient stage scores itself through an objective block that reads a ``support = "point"``
output observing the gauging station. The output is added to ``[calibration.outputs]`` when
the station is known from the file alone, which means one source named by ``station_ids``, or
``[site] gauge``. ``--expand`` then shows that output beside the two stages. A file that loads
several stations, or one whose source only discovers its station once the data step runs, keeps
the older form of the protocol, with ``variable`` and ``objective`` written on the phase and no
output named.

From Python the keys are the same, as dictionaries. A call with phases writes the document it
ran into the ``sessions/`` of the project as ``<case>.toml``, so a Python run can be replayed
from a file. The case takes the ``[simulation] name`` of the project, else the stem of its
file, as on the command line.

.. code-block:: python

   import hydromodpy as hmp

   project = hmp.Project("project.toml")
   report = project.calibrate(
       parameters={"K": {"bounds": [1e-7, 1e-3]}, "Sy": {"bounds": [5e-3, 0.35]}},
       outputs={
           "streams": {
               "support": "network",
               "map": {"complete": "nancon_stream_network.gpkg"},
               "model": {"neighbours": "D8"},
           },
           "gauge": {"support": "point", "variable": "discharge", "observes": "NANCON"},
       },
       objective_blocks=[
           {"name": "network", "metric": "distance_gap", "uses_outputs": ["streams"]},
           {
               "name": "network_share",
               "metric": "distance_gap",
               "uses_outputs": ["streams"],
               "normalize_cost": True,
           },
           {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["gauge"]},
       ],
       phases=[
           {
               "name": "k_steady",
               "parameters": ["K"],
               "regime": "steady",
               "objective_blocks": ["network"],
               "max_trials": 18,
           },
           {
               "name": "sy_transient",
               "parameters": ["Sy"],
               "regime": "transient",
               "objective_blocks": {"hydrograph": 0.8, "network_share": 0.2},
               "max_trials": 30,
               "window": {"start": "2001-01-01"},
           },
       ],
   )

A phase takes the search of ``[calibration]`` key by key. ``method``, ``max_trials``,
``precision`` and ``method_options`` written in the phase win, then the ones of the section,
then the default, which is a method chosen from what the phase scores and ``max_trials =
"auto"``. A precision of the section reaches only a phase whose engine stops on one, and not a
phase that writes that stopping option itself. The options of the section reach a phase that
runs the method of the section, and ``method_options = {}`` in a phase states that it takes
none. ``hmp calibrate FILE --list-phases`` says where each key comes from.

Each phase also says how wide its answer is, through ``uncertainty`` with the same keys as
``[calibration.uncertainty]``, which stays the default for every phase. Left unwritten, the
width follows what the phase scores. A phase scored only by network distances takes one mesh
cell, in meters, since a stream cannot move by less, and any other phase takes 5 % of its best
cost. ``cost_margin`` writes it with its unit, ``"5%"`` of the best cost or ``"75 m"`` of
network distance. A bare number is refused, and a length is accepted only on a search scored
by network distances. ``hmp check`` refuses a share on a phase scored only by network
distances. The interval never moves the calibrated value. It says which values the search could
not tell apart from it.

``hmp calibrate FILE --list-phases`` shows, for each phase, the parameters it moves, the ones it
re-opens and from which phase (when it moves a parameter an earlier phase calibrated, and
whether its engine starts from that value), which method it runs and why, the width of its
interval, and for each block what is compared with what, which is the simulated quantity and the
observed source (a station of ``[data.<family>]``, or a network file). After a phase, the report
gives the share of the cost each block actually took, which differs from the declared share when
the blocks have different units. ``overrides`` stays for any other configuration value a phase
must change, as a dotted path into the project configuration.

Where to add what
~~~~~~~~~~~~~~~~~

- A search method is a module in ``optim/adapters/`` on the template of
  :doc:`../how-to/add-a-calibration-method`, plus its options model in
  ``optim/method_config.py`` added to the ``CalibrationMethodConfig`` union. It is tested in
  ``tests/unit/calibration/test_optim_adapters_<method>_adapter.py``.
- A criterion a TOML can name is one row in ``hydromodpy/core/scoring/metric_table.py``, with
  its sense and its flags ``clips_negatives`` and ``dimensionless``. ``MetricKind`` in
  ``config_terms.py`` and ``METRIC_SENSE`` are built from that table. The kernel
  ``(sim, obs) -> float`` goes in ``criteria/series.py`` under its name in ``METRICS``, and
  ``test_metric_table.py`` keeps the two equal. ``criteria/registry.py`` builds from
  ``METRICS``, with no second list.
- An evaluator is a class with ``evaluator_id``, ``needs_prepared_model`` and
  ``evaluate(TrialRequest) -> TrialOutcome`` (``evaluation/port.py``). Its constructor takes
  only names from ``CONSTRUCTION_OPTIONS`` (``evaluation/registry.py``). Outside HydroModPy it
  is published in the ``hydromodpy.calibration.evaluator`` entry-point group. Inside, it goes
  in ``evaluation/`` if it reads nothing from the ``config_*`` modules and beside what it uses
  otherwise, and its dotted path is added to ``_BUILTIN_PATHS``.
- A calibration protocol is a module in ``protocols/`` with a class that satisfies
  ``CalibrationProtocol`` (``protocols/base.py``: references, deviations, ``expand``), an
  instance in ``_PROTOCOLS`` of ``protocols/registry.py``, and its options model in
  ``config_network.py``, which ``config_objective.py`` reads. ``CalibrationProtocolDecl`` then
  becomes a union discriminated on ``name``.
- A phase option is the field on ``CalibPhaseDecl`` in ``config_phases.py`` and its effect in
  ``runners/staged_runner.py`` (``_phase_config``) or, for a model setting, in
  ``runners/phase_regime.py``. A protocol that needs it writes it into the phases it expands
  and never reaches around the phase.
- A ``[calibration]`` field is the field on its model, ``CalibrationConfig`` in ``config.py``
  for a root field and the ``config_*`` module of its table otherwise, with a profile and a
  description. The parameter reference is computed from the model at the next documentation
  build (``tools/docs/field_registry.py``). The committed JSON Schema,
  ``docs/source/_static/hydromodpy-schema.json``, is compared with the model by
  ``tests/unit/docs/test_docs_config_consistency.py``.

Key public symbols and reading path
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The three entry points are ``runners.cli_runner.run_calibration_cli``,
``runners.programmatic_runner.run_calibration_programmatic`` and ``runners.staged_runner``.
``optim.engine.CalibrationEngine`` is the ask and tell loop. ``optim.optimizer`` holds
``build_optimizer`` and ``optimizers``, the registry of search methods with ``optimizers.get``,
``optimizers.names`` and ``optimizers.register``, per ``hydromodpy.core.plugin_registry``.
``optim.objective`` holds ``Objective`` and ``build_objective_from_config``, the cost.
``optim.diagnostics.correlated_parameter_pairs`` gives the parameters that a finished search
moved together, which the report flags. ``convergence_rate`` fits the decrease of the best
cost, and no report reads it. ``metrics.composite.build_metric_extractor`` says how the outputs
of a trial are extracted.

To read the code, start with this page, then ``calibration_layout.yaml`` for the modules that
other layers read, then ``runners/search.py`` and ``optim/engine.py``. ``runners/trial.py``
holds the prepare-once and evaluate-many primitive. ``optim/adapters/optuna_adapter.py`` is the
most generic adapter. ``validation_cases/calibration/recession_hillslope_aquifer/experiment.py``
is one case driven from Python.

Vocabulary
~~~~~~~~~~

- A trial is one run of the model with one set of parameter values.
- A prepared trial (``TrialContext``) is what is built once and reused by every trial of a
  search.
- An evaluator turns a trial request into a cost. It is the unit a document can swap with
  ``evaluator = ...``.
- A criterion, or kernel, is the function that scores one simulated series against one
  observed series. A TOML names it with ``metric``.
- An objective block is one ``[[calibration.objective_blocks]]`` entry, with an output, a
  criterion and a weight. The objective sums the blocks.
- The parameter space is the parameters with their bounds, search space and sampling.
- A phase is one search of a calibration, with its parameters, regime, objective blocks and
  their shares, and method.
- A protocol is a named recipe tied to a publication, which writes phases.
- A share is the weight of an objective block within one phase, normalized to sum to one over
  the blocks of that phase.
- A re-opened parameter is one that a phase moves again after an earlier phase calibrated it.
  The search starts from the earlier value when it can.
- A session is one calibration of a case on disk, ``sessions/<case>/``, with its journal, its
  phases and its frozen configuration.
- The case is the name that a calibration file gives its session and its calibrated run, the
  stem of the file that carries ``[calibration]``.
- The params hash is the key that lets a search skip a point it already ran.
- A promotion runs the pipeline on a trial, from its kept solve when there is one, so that it
  gets a run of its own. The best goes to ``runs/<case>/``.
