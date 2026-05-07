Calibration Workflow
====================

``[workflow].mode = "calibration"`` runs a parameter-estimation campaign. Instead of
executing one fixed simulation, HydroModPy repeatedly proposes parameter
values, runs candidate simulations, scores them, and records the calibration
history.

Use it when the question is:
"Which parameter values best explain the observations or synthetic targets?"

Functional Role
---------------

The calibration workflow sits on top of the simulation workflow:

.. code-block:: text

   base configuration
       -> prepare reusable context
       -> ask optimizer for parameters
       -> inject parameter values
       -> run candidate simulation
       -> extract observable(s)
       -> compute objective
       -> tell optimizer result
       -> persist calibration history
       -> optionally promote best runs

It is appropriate for:

- estimating hydraulic conductivity, storage, boundary conductance, or other
  exposed model parameters;
- comparing optimization methods;
- twin experiments with synthetic observations;
- calibration diagnostics and reporting.

Typical Command
---------------

.. code-block:: bash

   hmp run examples/projects/02_nancon_watershed/run_calibration_k.toml

Reference examples:

- ``examples/projects/01_calibration/project.toml``
- ``examples/projects/02_nancon_watershed/run_calibration_k.toml``
- calibration pages under :doc:`../../capability_gallery/calibration`

Representative Results
----------------------

.. gallery-figure:: /_static/capability_gallery/calibration/calibration_twin_dupuit_fixed_head_posterior_modflow6__configuration.png
   :alt: Calibration configuration figure
   :width: 100%

   The configuration figure makes the inverse problem explicit: calibrated
   parameters, outputs, objective blocks, methods, and noise assumptions all
   stay visible in one panel.

.. gallery-figure:: /_static/capability_gallery/calibration/calibration_twin_dupuit_fixed_head_posterior_modflow6__da_mh_gp_landscape.png
   :alt: Calibration objective landscape for a distribution-valued method
   :width: 100%

   The objective landscape or pairwise projection shows where the evaluated
   candidates concentrate relative to the truth and the selected solution.

.. gallery-figure:: /_static/capability_gallery/calibration/calibration_twin_dupuit_fixed_head_posterior_modflow6__da_mh_gp_posterior.png
   :alt: Calibration posterior distribution for a distribution-valued method
   :width: 100%

   ``da_mh_gp`` is currently the built-in method whose result is a parameter
   distribution. Its posterior figure shows the complete retained sample, not
   only the posterior mode or the best-fit candidate.

Minimal Shape
-------------

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
   batch_size = 1
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

Important Parameters
--------------------

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Section / field
     - Role
     - Practical guidance
   * - ``workflow``
     - Selects the calibration launcher.
     - Must be ``"calibration"``.
   * - ``base_config``
     - Holds the fixed model configuration.
     - Keep geometry, solver family, and non-calibrated parameters in the base
       file.
   * - ``[simulation]``
     - Defines each candidate run window and process.
     - Calibration still needs a valid forward simulation definition.
   * - ``[calibration].method``
     - Selects optimizer or sampler.
     - ``optuna`` is the general default; grid/random/simplex/CMA-ES variants
       are useful for controlled benchmarks.
   * - ``max_iter``
     - Number of candidate evaluations.
     - Keep small for smoke tests; increase for production calibration.
   * - ``batch_size``
     - Number of suggestions per ask.
     - Current examples usually use ``1`` for sequential campaigns.
   * - ``save_runs``
     - Controls persistence cost.
     - ``none`` keeps history only, ``best_n`` promotes best candidates,
       ``all`` stores every candidate as a full simulation.
   * - ``objective``
     - Metric optimized by the default objective.
     - Use ``kge`` or ``nse`` for discharge-style calibration, ``rmse`` or
       ``mae`` for scale-dependent errors.
   * - ``[calibration.parameters.*]``
     - Declares bounds, transform, prior, and target config path.
     - The ``path`` must match the runtime configuration field that should be
       overwritten.
   * - ``[calibration.outputs.*]``
     - Optional explicit observable declarations.
     - Use for point, cell, or boundary outputs in richer calibration cases.
   * - ``[[calibration.objective_blocks]]``
     - Optional composite objective blocks.
     - Use when several observables or weighted metrics must be combined.

Parameter Declaration Example
-----------------------------

.. code-block:: toml

   [calibration.parameters.K]
   bounds = [1e-6, 1e-3]
   transform = "log"
   prior = "log_uniform"
   path = "flow.param.K.field.value"
   units = "m/s"

Use ``transform = "log"`` for strictly positive parameters spanning several
orders of magnitude. Use ``mode = "scale"`` only when the sampled value should
multiply an existing baseline rather than replace it.

Persistence Strategy
--------------------

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - ``save_runs``
     - What is stored
     - When to use it
   * - ``none``
     - Calibration history, no full candidate stores.
     - Fast exploratory search.
   * - ``best_n``
     - History plus full outputs for the top ``save_best_n`` candidates.
     - Recommended default for practical calibration.
   * - ``all``
     - Every candidate becomes a full persisted simulation.
     - Debugging, small synthetic benchmarks, or audit-heavy studies.

Outputs To Inspect
------------------

After a calibration run, inspect:

1. configuration figure, so the inverse setup is explicit before reading scores;
2. objective history or trace, to see convergence and failed regions;
3. best parameter values;
4. posterior or distribution figure when the method is distribution-valued;
5. objective landscape or pairwise projection, to understand where candidates concentrate;
6. promoted best-run outputs if ``save_runs = "best_n"`` or ``"all"``.

Next Pages
----------

- :doc:`../calibration`
- :doc:`../../theory/calibration/index`
- :doc:`../../architecture/calibration/index`
- :doc:`../../capability_gallery/calibration`
