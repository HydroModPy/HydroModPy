Calibration Workflows
=====================

.. note::

   Use this page when the question is:
   "Which parameter values best explain the observations, and which method
   should I trust to find them?"

Calibration in HydroModPy is an ask/tell loop on top of the standard
``simulation`` workflow. An optimizer proposes parameter values, the engine
runs a candidate simulation, scores it against observations, and tells the
optimizer the result. The base configuration declares the fixed model; the
``[calibration]`` section declares which parameters move, the bounds, and
the method.

Two practical levers shape every calibration session:

- ``method`` selects the optimizer (``grid``, ``optuna``, ``scipy_de``,
  ``scipy_nelder_mead``, etc.). The right pick depends on parameter
  dimensionality and budget.
- ``save_runs`` controls disk cost. ``best_n`` is the recommended default:
  every trial stays in the DuckDB calibration trace, but only the top trials
  are promoted to full Zarr / Parquet stores.

Decision matrix
---------------

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Question
     - Best entry point
   * - What inverse problem is being solved?
     - :doc:`../theory/calibration/inverse-problem-formulation`
   * - Which calibration methods are implemented?
     - :doc:`../theory/calibration/calibration-methods`
   * - Where can I inspect calibration benchmark outputs?
     - :doc:`../capability_gallery/calibration`
   * - How does the calibration engine run, step by step?
     - :doc:`../architecture/calibration/calibration-execution-flows`
   * - Which classes hold calibration configuration and runtime state?
     - :doc:`../architecture/calibration/calibration-core-classes`
   * - Which method should I pick for my parameter count?
     - See "Pick a method" below

Pick a method
-------------

.. list-table::
   :header-rows: 1
   :widths: 22 16 16 46

   * - Method
     - Typical budget
     - Determinism
     - When to pick it
   * - ``grid``
     - product of ``n_points``
     - yes
     - 1-2 parameters, exhaustive sweep
   * - ``optuna`` (TPE default)
     - 50-200
     - seed-dependent
     - General default, adapts as it explores
   * - ``optuna`` (CMA-ES sampler)
     - 100-500
     - seed-dependent
     - 3+ continuous parameters
   * - ``scipy_de``
     - 100-500
     - seed-dependent
     - Robust evolutionary alternative
   * - ``scipy_nelder_mead``
     - 50-100
     - partial
     - Local refinement near a known optimum

Minimal calibration shape
-------------------------

.. code-block:: toml

   [workflow]
   mode = "calibration"
   base_config = "project.toml"

   [simulation]
   name = "nancon_calibration_k"

   [simulation.time]
   start_datetime = "2000-01-01"
   end_datetime = "2002-12-31"
   step_value = "1 month"

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflownwt"]

   [calibration]
   method = "optuna"
   max_iter = 40
   save_runs = "best_n"
   save_best_n = 3
   seed = 42
   objective = "kge"
   variable = "discharge"

   [calibration.parameters.K]
   bounds = [1e-6, 1e-3]
   transform = "log"
   prior = "log_uniform"
   path = "flow.param.K.field.value"
   units = "m/s"

.. code-block:: bash

   hmp run run_calibration_k.toml

Read more
---------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Theory
      :link: ../theory/calibration/index
      :link-type: doc

      Inverse-problem formulation and the calibration methods implemented
      in HydroModPy.

   .. grid-item-card:: Gallery
      :link: ../capability_gallery/calibration
      :link-type: doc

      Stable calibration benchmark pages with posteriors, traces, and
      objective landscapes.

   .. grid-item-card:: Architecture
      :link: ../architecture/calibration/index
      :link-type: doc

      Package layout, runtime classes, and execution flows of the
      calibration engine.

   .. grid-item-card:: API
      :link: ../api/index
      :link-type: doc

      Generated Python reference for the calibration helpers.

See also
--------

- :doc:`../theory/foundations/index` for the physical scope and
  modelling assumptions behind every calibration.
- :doc:`concepts/reading-results-pages` for reading the generated result
  pages.
- :doc:`comparison` when the goal is to compare optimizers on the same
  physical case rather than calibrate parameters.
