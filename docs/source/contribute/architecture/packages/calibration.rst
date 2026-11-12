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

A modeller who writes phases in a TOML file reads :doc:`/how-to/write-calibration-phases`.

Import rules
~~~~~~~~~~~~

A part imports only what its row of ``tests/unit/architecture/calibration_layout.yaml`` allows.
``tests/unit/architecture/test_package_layouts.py`` checks every import, at module level, inside
a function and under ``TYPE_CHECKING``. The same file lists the modules that other layers may
read, and it forbids any import of a solver backend (``solver_access``).

How a calibration flows
~~~~~~~~~~~~~~~~~~~~~~~

1. Load. ``HydroModPyConfig`` validates ``[calibration]``. A named protocol is expanded
   (``expand_calibration_protocol``) and each parameter name becomes a config path
   (``resolve_parameter_targets``). An unknown criterion or evaluator is refused here. An
   unknown search method loads and is refused by the preflight, before anything is prepared.
2. Check. Every launch runs ``preflight_launch`` on the document it will run, with ``--set``,
   ``--overlay`` and each phase's overrides written in. It solves nothing, and an error stops
   the launch. ``hmp check`` prints the same findings.
3. Start. A runner of ``runners/`` names the case, which is the stem of the file that carries
   ``[calibration]`` unless ``[simulation] name`` is set. It reserves ``sessions/<case>/``,
   freezes the resolved document there as ``config.toml``, then builds the parameter space, the
   optimizer, the evaluator and the ``CalibrationEngine``.
4. Prepare once. Geography, mesh and data are built a single time, through the
   ``TrialPipeline`` that ``project`` installs. ``earliest_affected_step`` finds the first
   workflow step that reads a calibrated config path. The steps before it run once and every
   trial shares them. The steps from it to the solve and the extraction run again for each
   trial (``run_trial_light``). The persistent steps run only for a promoted trial
   (``promote_prepared_trial``). Shared products come from the product store, so a trial that
   leaves the soil alone never rebuilds the soil reservoir.
5. Trial. The engine asks the optimizer for a point and skips it when its params hash is
   cached. The default evaluator (``runners/pipeline_evaluator.py``) sets the values, solves,
   extracts the outputs and pairs them with the observations. When every calibrated path is a
   property profile (K or Sy), the next trials of a lane only rewrite the property file and
   solve again (``runners/lanes.py``). The cost is the same to the bit as a full build.
6. Score. ``optim/objective.py`` turns the paired series into one cost, block by block, with
   the kernels of ``criteria/``.
7. Write. Each trial goes to ``sessions/<case>/trials.jsonl`` as events (``proposed``,
   ``finished``, ``linked``). Only the session, in the parent process, writes the journal.
8. Promote. Once per phase, ``runners/promotion.py`` promotes what ``save_runs`` names. The
   best trial of the last phase becomes ``runs/<case>/``, paired with the session by version.
   A trial that may be promoted keeps its solver folder, so its promotion extracts again and
   does not solve again. A promotion failure closes the session ``partial``, never ``failed``.
9. Close. ``session.json`` takes the status (``completed``, ``partial``, ``failed``,
   ``aborted``). SIGTERM or SIGINT writes ``aborted`` in under a second and promotes the best
   trial so far. ``hmp calibrate --resume`` reads back a phase that completed with the same
   fingerprint and solves the cut phase again, with its trials preloading the cache.
10. Report. ``report_session`` writes the session report, and ``hmp show SESSION --report``
    writes it again.

What a calibration writes
~~~~~~~~~~~~~~~~~~~~~~~~~

A calibration writes two sibling directories of one name, ``sessions/<case>/`` for what the
search evaluated and ``runs/<case>/`` for the calibrated run. Inside the loop a trial lives in
memory, and Zarr and Parquet exist only for promoted trials. The index is rebuilt from the
session files and the calibration never opens it. The layout is in :doc:`../storage-layout`
and the arrays and series are listed in :doc:`/reference/outputs`.

The params hash (``optim/cache.py``) keys the cache. It covers the model, its inputs, the
outputs, the objective blocks, the scoring window and what the evaluator reads. The method,
its options, the seed, the budget and the bounds are outside it, so a search that changes one
of them replays points already solved. :toml:`calibration.use_cache` preloads the hashes of
every ``trials.jsonl`` of the project.

Where to add what
~~~~~~~~~~~~~~~~~

- A search method is a module in ``optim/adapters/`` on the template of
  :doc:`../how-to/add-a-calibration-method`, plus its options model in
  ``optim/method_config.py``. Its test is
  ``tests/unit/calibration/test_optim_adapters_<method>_adapter.py``.
- A criterion a TOML can name is one row in ``hydromodpy/core/scoring/metric_table.py``, and
  its kernel ``(sim, obs) -> float`` goes in ``criteria/series.py`` under its name in
  ``METRICS``. ``tests/unit/core/scoring/test_metric_table.py`` keeps the two equal.
- An evaluator satisfies the port of ``evaluation/port.py``. Its dotted path is added to
  ``_BUILTIN_PATHS`` of ``evaluation/registry.py``, or it is published in the
  ``hydromodpy.calibration.evaluator`` entry-point group.
- A calibration protocol is a module in ``protocols/`` that satisfies ``CalibrationProtocol``
  (``protocols/base.py``), an instance in ``_PROTOCOLS`` of ``protocols/registry.py``, and its
  options model in ``config_network.py``.
- A phase option is a field on ``CalibPhaseDecl`` in ``config_phases.py`` and its effect in
  ``_phase_config`` of ``runners/staged_runner.py``. A protocol that needs it writes it into
  the phases it expands.
- A ``[calibration]`` field goes on the model of its table, with a profile and a description.
  The parameter reference is computed from the model at the next documentation build.

Reading path
~~~~~~~~~~~~

Start with this page, then ``calibration_layout.yaml``, then ``runners/search.py`` and
``optim/engine.py``. ``runners/trial.py`` holds the prepare-once and evaluate-many primitive.
