calibration
===========

``hydromodpy.calibration`` runs the ask/tell loop that estimates
parameters against observations. It sits on top of the simulation
layer and reuses the prepare-once / evaluate-many primitive in
``hydromodpy/simulation/execution/trial.py``.

Sub-modules
-----------

- ``calibration/cli_runner.py`` -- CLI driver
  (``run_calibration_cli``). Loads the TOML, prepares the trial
  context, runs the engine, persists iterations, optionally promotes
  best trials.
- ``calibration/programmatic_runner.py`` -- in-process driver used
  by ``hmp.calibrate`` and the regional_lab pipeline.
- ``calibration/runners/`` -- per-method runner variants
  (twin experiments, trial helpers, contracts).
- ``calibration/promotion.py`` -- top-N promotion of best trials to
  full simulations.
- ``calibration/state.py`` -- in-memory session state shared between
  ask/tell loops and the persistence layer.
- ``calibration/engine.py`` -- ``CalibrationEngine`` drives the
  ask/tell loop until convergence or ``max_iter``. Returns a
  ``CalibrationSession``.
- ``calibration/adapters/`` -- one adapter per optimizer
  (``Grid``, ``RandomSearch``, ``ScipyNelderMead``, ``ScipyDE``,
  ``Optuna`` with TPE / CMA-ES samplers, ``CmaEs``,
  ``GpMapping``, ``DaMhGp``, plus prior sampling).
- ``calibration/cases/`` -- runnable analytical benchmarks that the
  loop can exercise end-to-end without MODFLOW
  (``recession_brutsaert``, ``groundwater_1d``).
- ``calibration/lumped/`` -- lumped-model helpers reused by the
  cases.
- ``calibration/metrics.py`` -- trial-side metric extractor
  (``build_metric_extractor``).
- ``calibration/objective.py`` -- ``Objective`` aggregates one or
  more weighted metrics into a scalar loss.
- ``calibration/persistence.py`` -- DuckDB writes for
  ``calibration_sessions`` and ``calibration_iterations``.
- ``calibration/report.py`` -- HTML report assembly.
- ``calibration/diagnostics.py`` -- ``convergence_rate``,
  ``parameter_correlation``, and other post-loop helpers.

Ask / tell flow
---------------

.. code-block:: text

   load TOML -> CalibrationConfig
   prepare_trials() runs steps [0..earliest) once
   for iter in range(max_iter):
       suggestion = optimizer.ask()
       result = run_trial_light(trial_ctx, suggestion, ...)
       optimizer.tell(result)
       persist iteration to DuckDB
   if save_runs != "none":
       promote selected trials to full simulations

``earliest`` is computed by
``hydromodpy/workflow/internals/dependencies.earliest_affected_step``
from the dotted paths in ``[calibration.parameters.*]``. Steps
``[0..earliest)`` are shared across every trial; steps
``[earliest..8]`` re-run lightweight per trial; steps
``[9..11]`` only run when ``promote_trial`` is invoked after the
loop.

Storage rule
------------

- RAM only inside the loop (aligned simulated vector + scalar
  metrics).
- DuckDB rows for the trace
  (``calibration_iterations.sim_id`` stays NULL by default).
- Zarr / Parquet only for promoted trials (``save_runs = "best_n"``
  or ``"all"``), with ``sim_id`` back-filled.

The ``ParamsHashCache`` (SHA-256 of canonical parameter JSON)
deduplicates trials across sessions when ``use_cache = true``
(default).

Key public symbols
------------------

- ``hydromodpy.calibration.cli_runner.run_calibration_cli``
- ``hydromodpy.calibration.programmatic_runner.run_calibration_programmatic``
- ``hydromodpy.calibration.engine.CalibrationEngine``
- ``hydromodpy.calibration.adapters.{Grid, RandomSearch,
  ScipyNelderMead, ScipyDE, OptunaAdapter, CmaEsAdapter,
  GpMappingAdapter, DaMhGpAdapter}``
- ``hydromodpy.calibration.metrics.build_metric_extractor``
- ``hydromodpy.calibration.objective.Objective``
- ``hydromodpy.calibration.diagnostics.{convergence_rate,
  parameter_correlation}``

Recommended reading path
------------------------

1. ``hydromodpy/calibration/__init__.py`` for the public surface.
2. ``hydromodpy/calibration/cli_runner.py``
3. ``hydromodpy/calibration/engine.py``
4. ``hydromodpy/simulation/execution/trial.py``
5. one adapter (``hydromodpy/calibration/adapters/optuna_adapter.py``
   is the most generic).
6. one case (``hydromodpy/calibration/cases/recession_brutsaert.py``).

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``physics``, ``data``,
  ``spatial``, ``solver``, ``simulation``, ``calibration``,
  ``results``.
- Allowed sources: ``config``, ``workflow``, ``project`` and ``cli``.

See also
--------

- :doc:`/architecture/calibration/calibration-architecture` --
  package map plus every UML view.
- :doc:`/architecture/calibration/calibration-guide` -- full
  operational reference.
- :doc:`/architecture/how-to/add-a-calibration-method` --
  step-by-step recipe.
- :doc:`/user_guide/workflows/calibration` -- user-facing hub.
