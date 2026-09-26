calibration
===========

``hydromodpy.calibration`` fits model parameters to observations. A
``[calibration]`` table names the parameters to vary, the outputs to
compare, the criterion that scores them and the search method. An
optimizer proposes parameter values, one trial runs the model with them,
the outputs are scored against the observations, and the session is
written to disk as it goes. It sits above the simulation and solver
layers and reuses the prepare-once / evaluate-many primitive of
``hydromodpy/calibration/runners/trial.py``.

The map of the package -- its parts, its import rules, the tree of
modules and where to add a search method, criterion, evaluator, forward
model or protocol -- is ``hydromodpy/calibration/README.md``, enforced by
``tests/unit/architecture/calibration_layout.yaml`` and
``tests/unit/architecture/test_package_layouts.py``.

Ask / tell flow
----------------

.. code-block:: text

   load TOML -> CalibrationConfig
   prepare_trials() runs steps [0..earliest) once
   n_done = 0
   while n_done < max_iter and not optimizer.converged():
       suggestions = optimizer.ask(n=batch_size)
       results = [run_trial_light(trial_ctx, s, ...) for s in suggestions]
       optimizer.tell(results)
       persist each iteration to DuckDB
       n_done += len(results)
   if save_runs != "none":
       promote selected trials to full simulations

``earliest`` is computed by ``hydromodpy/workflow/internals/dependencies.py``
from the dotted paths in ``[calibration.parameters.*]``. Steps
``[0..earliest)`` are shared across every trial; steps ``[earliest..8]``
re-run lightweight per trial; steps ``[9..11]`` only run when
``promote_trial`` is invoked after the loop.

Storage rule
------------

- RAM only inside the loop (aligned simulated vector + scalar metrics).
- DuckDB rows for the trace (``calibration_iterations.sim_id`` stays NULL
  by default).
- Zarr / Parquet only for promoted trials (``save_runs = "best_n"`` or
  ``"all"``), each linked by ``sim_id`` before it replays.

The ``ParamsHashCache`` (SHA-256 of canonical parameter JSON,
``optim/cache.py``) deduplicates trials across sessions when
``use_cache = true`` (default).

Key public symbols
------------------

- ``hydromodpy.calibration.runners.cli_runner.run_calibration_cli``
- ``hydromodpy.calibration.runners.programmatic_runner.run_calibration_programmatic``
- ``hydromodpy.calibration.runners.staged_runner`` -- the phased runner.
- ``hydromodpy.calibration.optim.engine.CalibrationEngine``
- ``hydromodpy.calibration.optim.optimizer.{available_optimizers,
  build_optimizer, register_optimizer}`` -- the search-method registry; see
  the README for the adapters it discovers under ``optim/adapters/``.
- ``hydromodpy.calibration.metrics.build_metric_extractor``
- ``hydromodpy.calibration.optim.objective.{Objective,
  build_objective_from_config}``
- ``hydromodpy.calibration.optim.diagnostics.{convergence_rate,
  parameter_correlation}``

Recommended reading path
------------------------

1. ``hydromodpy/calibration/README.md`` for the package map.
2. ``hydromodpy/calibration/__init__.py`` for the public surface.
3. ``hydromodpy/calibration/runners/cli_runner.py``
4. ``hydromodpy/calibration/optim/engine.py``
5. ``hydromodpy/calibration/runners/trial.py``
6. one adapter (``hydromodpy/calibration/optim/adapters/optuna_adapter.py``
   is the most generic).
7. one case (``hydromodpy/calibration/cases/recession_brutsaert.py``).

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``physics``, ``data``,
  ``spatial``, ``solver``, ``simulation``, ``calibration``, ``results``.
- Allowed sources: ``config``, ``workflow``, ``project`` and ``cli``.

See also
--------

- :doc:`/architecture/calibration/calibration-architecture` -- package map
  plus every UML view.
- :doc:`/architecture/calibration/calibration-guide` -- full operational
  reference.
- :doc:`/architecture/how-to/add-a-calibration-method` -- step-by-step
  recipe.
- :doc:`/user_guide/workflows/calibration` -- user-facing hub.
