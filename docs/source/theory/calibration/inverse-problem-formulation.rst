Calibration Inverse Problem Formulation
=======================================

Scope
-----

This page explains how HydroModPy turns a calibration problem into one scalar
objective that its optimizers can minimize. The goal here is practical rather
than textbook-like: what enters the calibration engine, how several
observations are combined, and what a returned result should mean to a modeller.

A Practical Reading Of The Inverse Problem
------------------------------------------

HydroModPy calibration always starts from the same three ingredients:

- a parameter vector to test;
- a forward model that turns those parameters into simulated outputs;
- observed data used to score the simulation.

In plain language, calibration is a repeated question:

  "If the model used these parameter values, would it reproduce the observed
  behavior better or worse than the previous try?"

For example, suppose a user calibrates hydraulic conductivity ``K`` and
specific yield ``Sy`` against:

- a piezometric time series,
- and an outlet discharge time series.

One candidate parameter vector is first sent to the simulator. The simulator
returns raw model outputs. HydroModPy then extracts the observation blocks of
interest, compares each block to observations with a chosen metric, combines
those scores into one scalar cost, and gives that cost to the calibration
method.

Parameter Vector And Feasible Domain
------------------------------------

Internally, optimizers work on an ordered numeric vector. The simulator, on the
other hand, usually expects named parameters. ``CalibrationParameterSet`` is
the object that keeps those two views aligned.

This detail matters scientifically because parameter order is not cosmetic. The
same vector value means something different if the parameter order changes.

Each parameter is also bounded. Those bounds define the physically admissible
search box:

- they prevent obviously impossible values from being explored;
- they encode prior expert knowledge;
- they strongly influence which calibration methods are efficient.

Wide bounds describe an exploratory problem. Narrow bounds describe a more
local refinement problem.

From Simulation To One Cost
---------------------------

HydroModPy supports two close variants of the same idea.

Single-series calibration
^^^^^^^^^^^^^^^^^^^^^^^^^

The simulator returns one series, for example one discharge or one head
chronicle. That series is compared directly to the observed series.

Multi-observable calibration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The simulator returns a richer payload. HydroModPy then extracts several
observable blocks from it, for example:

- heads at a monitoring location,
- outlet discharge,
- seepage along a support,
- or any other block selected by the calibration TOML.

Each block gets its own metric and weight before everything is merged into one
final scalar objective.

Built-In Metrics And When They Help
-----------------------------------

HydroModPy currently exposes five main metrics. The important point is not the
formula itself, but what kind of mismatch each metric emphasizes.

.. list-table::
   :header-rows: 1
   :widths: 14 28 30 28

   * - Metric
     - What it emphasizes
     - Typical good fit
     - Cost minimized by the engine
   * - ``RMSE``
     - Large deviations are penalized strongly.
     - Use when big misses matter more than many small ones.
     - The engine minimizes ``RMSE`` directly.
   * - ``MAE``
     - Typical absolute mismatch, less dominated by outliers.
     - Use when observations are noisy or spikes should not dominate.
     - The engine minimizes ``MAE`` directly.
   * - ``NSE``
     - Reproduction of time-series dynamics relative to the observed mean.
     - Use for hydrograph or head-series shape matching.
     - The engine minimizes ``1 - NSE``.
   * - ``NSElog``
     - Same idea as ``NSE``, but with more sensitivity to lower values.
     - Use for low-flow or recession behavior when data stay positive.
     - The engine minimizes ``1 - NSElog``.
   * - ``KGE``
     - Balance between correlation, variability, and bias.
     - Use when overall behavior matters more than one single error mode.
     - The engine minimizes ``1 - KGE``.

Two practical reminders are worth keeping in mind:

- ``NSElog`` only makes sense when the compared values are strictly positive;
- an apparently "good" score can still hide parameter non-identifiability if
  several parameter sets obtain similar values.

Combining Several Observation Blocks
------------------------------------

In the calibration workflow, HydroModPy can combine several
observation blocks into one weighted objective:

.. math::

   J(\theta) = \sum_{b=1}^{B} \tilde{w}_b \, \tilde{J}_b(\theta)

The operational reading is simple:

- each block produces its own raw mismatch;
- that mismatch can be normalized so blocks with different units are
  comparable;
- the normalized blocks are weighted and summed.

This is useful when one calibration should satisfy several kinds of evidence at
once.

Illustrative example
^^^^^^^^^^^^^^^^^^^^

Suppose a calibration uses:

- heads with weight ``0.7``,
- outlet discharge with weight ``0.3``.

If cost normalization is enabled, HydroModPy first rescales the two blocks so
that one block is not dominant only because it is measured in larger numerical
units. The final objective then expresses a scientific compromise:

  "Find parameter values that explain heads well, while still preserving a
  reasonable match to outlet discharge."

For error metrics such as ``RMSE`` and ``MAE``, HydroModPy uses an observed-data
scale for normalization when possible. For efficiency metrics such as ``NSE``,
``NSElog`` and ``KGE``, the natural scale is already of order one, so no extra
rescaling is needed.

What Bounds Mean In Practice
----------------------------

At the engine level, any candidate outside the allowed bounds is rejected with
an infinite cost. This is the generic safety rule.

The two local simplex-based methods behave slightly differently internally:

- they clip the candidate back into the feasible box before calling the model;
- they add a quadratic penalty when the optimizer tries to move outside bounds.

This distinction is numerical rather than scientific. In both cases, the model
is evaluated only for admissible parameter values.

Best Fit Versus Distribution-Valued Results
-------------------------------------------

All calibration methods return at least:

- a best parameter vector;
- a best objective value;
- a number of expensive model evaluations.

Some methods return more than a single optimum.

Best-fit methods
^^^^^^^^^^^^^^^^

- ``grid_search``
- ``random_search``
- ``cma_es``
- ``nelder_mead``
- ``simplex``

These methods answer:

  "Which tested parameter set looked best under the chosen objective?"

Distribution-valued methods
^^^^^^^^^^^^^^^^^^^^^^^^^^^

- ``gp_mapping`` returns an approximate posterior-like cloud built from a
  surrogate model;
- ``da_mh_gp`` returns MCMC samples from an explicit posterior target defined
  by its prior and RMSE-based likelihood.

These methods answer a richer question:

  "Which ranges of parameter values remain plausible, and how strongly are
  they constrained?"

Interpretation Checklist
------------------------

- A low cost is not enough on its own; always ask whether several different
  parameter combinations achieve similar scores.
- The chosen weights in a multi-observable objective define the scientific
  question being asked. Changing them changes the meaning of the "best" model.
- A sample cloud is often more informative than a single optimum when the goal
  is uncertainty analysis or identifiability assessment.
- ``da_mh_gp`` should only be interpreted as a Bayesian posterior sampler when
  its RMSE likelihood and ``sigma_noise`` setting are scientifically coherent
  for the data at hand. The delayed-acceptance MCMC scheme follows
  :cite:`christen2005`.

Further Reading
---------------

- :doc:`calibration-methods` for the per-method scientific and algorithmic
  references.
- :cite:`abherve2023` for a HydroModPy-related calibration of catchment
  hydraulic properties against the spatial distribution of stream networks.
- :doc:`../bibliography` for the full list of cited references.
