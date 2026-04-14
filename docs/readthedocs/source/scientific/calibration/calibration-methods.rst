Calibration Methods Implemented In HydroModPy
=============================================

Scope
-----

This page documents the methods currently registered in
``hydromodpy.analysis.calibration.core.methods_dispatcher``:

- ``grid_search``
- ``random_search``
- ``cma_es``
- ``nelder_mead``
- ``simplex``
- ``gp_mapping``
- ``da_mh_gp``

The intent is deliberately practical. The question is not "what does the
method look like in an optimization textbook?" but rather:

- what HydroModPy actually does with it;
- what kind of result the method returns;
- and in which calibration situation the method is a reasonable choice.

Method Selection At A Glance
----------------------------

.. list-table::
   :header-rows: 1
   :widths: 14 34 28 24

   * - Method
     - What it does in practice
     - Good fit for
     - Poor fit for
   * - ``grid_search``
     - Evaluates every point on a regular parameter grid.
     - One or two parameters, teaching cases, objective-landscape mapping.
     - More than a few parameters or tight evaluation budgets.
   * - ``random_search``
     - Draws many independent candidates inside bounds and keeps the best one.
     - Wide search boxes, rough first pass, simple global baseline.
     - Fine local refinement or strong uncertainty analysis.
   * - ``cma_es``
     - Adapts a multivariate Gaussian search distribution around promising regions.
     - Expensive non-smooth objectives with moderate parameter dimension.
     - Exact posterior inference or highly constrained/discrete parameter spaces.
   * - ``nelder_mead``
     - Moves a local simplex from one starting point until improvement stalls.
     - Fast local refinement once a plausible basin is already known.
     - Multimodal problems with poor initialization.
   * - ``simplex``
     - Same local simplex family, through another SciPy entry point.
     - Compatibility and local refinement in low dimension.
     - Problems where the start point dominates the outcome.
   * - ``gp_mapping``
     - Learns a surrogate of the objective and refines promising regions.
     - Expensive simulators and approximate uncertainty mapping.
     - Exact posterior inference or non-positive parameter bounds.
   * - ``da_mh_gp``
     - Runs a delayed-acceptance MCMC chain with exact second-stage correction.
     - Posterior sampling, uncertainty, identifiability, parameter trade-offs.
     - Fast point estimation only, or objectives that are not RMSE-based.

Grid Search
-----------

What HydroModPy Does
^^^^^^^^^^^^^^^^^^^^

``grid_search`` builds one axis per parameter, then evaluates the full
Cartesian product of those axes with the true objective.

In HydroModPy:

- axes are linear by default;
- axes become logarithmic for indices listed in ``log_scale_indices``;
- the returned best point is always a point that was truly simulated, not an
  interpolated estimate.

When It Fits
^^^^^^^^^^^^

Use ``grid_search`` when the point is to understand the problem before trying
to solve it efficiently.

Typical situations:

- one-parameter or two-parameter synthetic cases;
- generating objective-surface figures;
- verifying that a new metric or observation mapping behaves as expected;
- establishing a deterministic reference baseline.

What To Expect
^^^^^^^^^^^^^^

``grid_search`` is slow on purpose. Its value is transparency:

- every part of the explored box is visited;
- repeated runs are identical;
- parameter trade-offs are easy to visualize in low dimension.

The main limitation is combinatorial growth. A method that is perfectly
reasonable in 1D or 2D can become unusable as soon as the parameter count grows.

Random Search
-------------

What HydroModPy Does
^^^^^^^^^^^^^^^^^^^^

``random_search`` draws independent samples inside the parameter bounds and
keeps the best one it sees.

In HydroModPy:

- sampling is uniform by default;
- it becomes log-uniform for indices listed in ``log_scale_indices``;
- the method does not adapt to what it has learned so far.

When It Fits
^^^^^^^^^^^^

Use ``random_search`` when a cheap global baseline is more important than
algorithmic sophistication.

Typical situations:

- you have wide bounds and no trustworthy initial guess;
- you want a first scan before switching to a local method;
- you want a stochastic baseline against which more elaborate methods can be
  judged.

What To Expect
^^^^^^^^^^^^^^

``random_search`` is often more informative than a local method at the
beginning of a project because it is not tied to one starting point. It is
still a blunt instrument:

- precision improves slowly;
- samples are spent everywhere, including bad regions;
- the method does not return a native uncertainty estimate.

CMA-ES
------

What HydroModPy Does
^^^^^^^^^^^^^^^^^^^^

``cma_es`` runs a Covariance Matrix Adaptation Evolution Strategy through the
`cma <https://cma-es.github.io/apidocs-pycma/>`_ library.

In HydroModPy:

- the method works inside a bounded search box;
- parameters are normalized to the unit hypercube by default before CMA-ES is
  launched;
- ``sigma0`` is therefore interpreted in normalized coordinates unless
  ``normalize = false`` is requested;
- the returned best point always comes from true objective evaluations.

When It Fits
^^^^^^^^^^^^

Use ``cma_es`` when the objective is too irregular for local simplex methods
but you still want a more adaptive global search than pure random sampling.

Typical situations:

- multimodal or anisotropic inverse problems;
- two to maybe ten hydraulic parameters with expensive forward runs;
- cases where parameter scaling matters and a covariance-adapting search is
  useful.

What To Expect
^^^^^^^^^^^^^^

Compared with ``random_search``, CMA-ES spends evaluations more intelligently
because it learns both a center and a covariance structure. Compared with local
simplex methods, it is less sensitive to one initial point.

Its limits are also clear:

- it remains an optimizer, not a posterior sampler;
- it can still be expensive when each forward run is costly;
- good performance depends on sensible bounds and an initial ``sigma0``.

Nelder-Mead And Simplex
-----------------------

Why HydroModPy Keeps Two Names
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

HydroModPy exposes two wrappers around the same local derivative-free family:

- ``nelder_mead`` calls ``scipy.optimize.minimize(..., method="Nelder-Mead")``;
- ``simplex`` calls ``scipy.optimize.fmin``.

Scientifically, both are local simplex methods. They are kept separately mainly
for compatibility, benchmarking, and control over the exact SciPy entry point
used in legacy and current workflows.

What HydroModPy Does
^^^^^^^^^^^^^^^^^^^^

Both methods:

- start from ``x0`` when provided;
- otherwise start from the midpoint of each parameter interval;
- use a bound-aware penalized objective internally.

That last point matters. The optimizer is allowed to move numerically outside
the admissible box, but HydroModPy clips the candidate back to admissible
values before running the model and adds a penalty for leaving the box.

When They Fit
^^^^^^^^^^^^^

Use ``simplex`` or ``nelder_mead`` when the inverse problem has already become
mostly local.

Typical situations:

- a previous global scan has identified one plausible basin;
- expert knowledge already narrows the physically reasonable range;
- the calibration has only a few parameters and the objective is reasonably
  smooth near the solution.

Illustrative examples:

- refining one or two reservoir parameters after a coarse search;
- refining ``K`` and ``Sy`` once an earlier method has already bracketed the
  right order of magnitude.

What To Expect
^^^^^^^^^^^^^^

These methods are often efficient in low dimension, but they do not solve the
global-search problem for you.

Their main risks are:

- convergence to a local basin near the start point;
- sensitivity to parameter scaling;
- no uncertainty quantification in the returned result.

GP Mapping
----------

What HydroModPy Does
^^^^^^^^^^^^^^^^^^^^

``gp_mapping`` is HydroModPy's approximate surrogate-based method. In practice,
it follows this sequence:

1. draw an initial Latin-hypercube design;
2. evaluate the true objective on that design;
3. fit a surrogate to the negative objective;
4. score candidate pools with an upper-confidence-bound style criterion;
5. evaluate the most promising candidates with the true model;
6. build a posterior-like sample cloud by importance resampling on the
   surrogate.

The returned best parameters always come from true model evaluations, not from
the surrogate alone.

When It Fits
^^^^^^^^^^^^

Use ``gp_mapping`` when each forward run is expensive and you want more than a
single point estimate, but you do not need an exact Bayesian posterior.

Typical situations:

- a simulator such as MODFLOW 6 is costly enough that blind sampling is wasteful;
- the parameter count is still modest;
- you want both a best-fit model and a quick reading of plausible parameter
  regions.

What To Expect
^^^^^^^^^^^^^^

The method is usually more sample-efficient than brute-force global search when
the surrogate is informative. It remains approximate:

- the sample cloud is posterior-like, not an exact posterior sample;
- the quality of the answer depends on surrogate quality;
- the current implementation requires strictly positive parameter bounds.

Platform And Backend Note
^^^^^^^^^^^^^^^^^^^^^^^^^

HydroModPy prefers a scikit-learn Gaussian process backend with an anisotropic
RBF kernel. On Windows, or when the native optimizer is explicitly disabled,
the code falls back to an internal inverse-distance-weighted surrogate.

The method name stays the same, but the surrogate backend can therefore differ
across environments.

Delayed-Acceptance GP Metropolis-Hastings
-----------------------------------------

What HydroModPy Does
^^^^^^^^^^^^^^^^^^^^

``da_mh_gp`` is the most statistical method in the built-in portfolio. It is a
two-stage MCMC workflow:

1. build an initial design in the bounded parameter box;
2. evaluate an exact log-posterior on that design;
3. fit an internal lightweight Gaussian-process surrogate;
4. propose new candidates with a random-walk Metropolis-Hastings step;
5. filter weak proposals with the surrogate;
6. apply an exact second-stage correction with the true posterior;
7. retrain the surrogate periodically as new exact evaluations accumulate.

This is why the method can be both cheaper than a full exact chain and more
trustworthy than a purely surrogate-only workflow.

When It Fits
^^^^^^^^^^^^

Use ``da_mh_gp`` when uncertainty quantification is the main scientific output.

Typical situations:

- you need posterior samples, not only one optimum;
- you want to inspect parameter correlations or practical identifiability;
- you want to know whether several parameter regions remain plausible after
  calibration.

What To Expect
^^^^^^^^^^^^^^

Compared with direct-search methods, ``da_mh_gp`` takes more care to configure
and interpret:

- it assumes the objective passed to it is an ``RMSE``;
- it needs a meaningful ``sigma_noise`` to define its likelihood scale;
- proposal scale, burn-in, and thinning directly affect chain behavior.

The reward for that extra work is that the result is genuinely
distribution-valued: accepted samples, acceptance rates, and posterior traces
are part of the scientific output.

Choosing A Method As A Workflow
-------------------------------

In practice, the methods are often most useful as a sequence rather than as
competing one-shot choices.

1. Use ``grid_search`` or ``random_search`` to understand scale, rough
   parameter ranges, and basic multimodality.
2. Use ``simplex`` or ``nelder_mead`` when the problem already looks local and
   a best-fit point estimate is the main target.
3. Use ``gp_mapping`` when the simulator is expensive and you want a practical,
   approximate uncertainty picture.
4. Use ``da_mh_gp`` when the final deliverable is a posterior sample and an
   uncertainty statement, not only one calibrated optimum.

Implementation Provenance And References
----------------------------------------

- ``grid_search`` is implemented directly in
  ``hydromodpy.analysis.calibration.core.methods.grid_search`` using NumPy and
  ``itertools.product``. It does not wrap a dedicated external optimization
  library.
- ``random_search`` is implemented directly in
  ``hydromodpy.analysis.calibration.core.methods.random_search`` using NumPy's
  random generator. It is intentionally kept as a pragmatic Monte Carlo
  baseline. For the practical argument that random search is a strong baseline
  for bounded search spaces, see `Bergstra and Bengio (2012)
  <https://www.jmlr.org/papers/v13/bergstra12a.html>`_.
- ``simplex`` and ``nelder_mead`` are thin wrappers around SciPy optimizers:
  ``scipy.optimize.fmin`` and
  ``scipy.optimize.minimize(..., method="Nelder-Mead")``. References:
  `Virtanen et al. (2020), SciPy 1.0
  <https://www.nature.com/articles/s41592-019-0686-2>`_;
  `Nelder and Mead (1965)
  <https://doi.org/10.1093/comjnl/7.4.308>`_.
- ``gp_mapping`` is a HydroModPy-specific orchestration implemented in
  ``hydromodpy.analysis.calibration.core.methods.gp_mapping``. It uses
  ``sklearn.gaussian_process.GaussianProcessRegressor`` when available and
  otherwise falls back to an internal inverse-distance-weighted surrogate.
  References: `Pedregosa et al. (2011), scikit-learn
  <https://www.jmlr.org/papers/v12/pedregosa11a.html>`_;
  `Rasmussen and Williams (2006), Gaussian Processes for Machine Learning
  <https://gaussianprocess.org/gpml/>`_.
- ``da_mh_gp`` is reimplemented in HydroModPy in
  ``hydromodpy.analysis.calibration.core.methods.da_mh_gp`` as a
  delayed-acceptance random-walk Metropolis-Hastings workflow with an internal
  lightweight Gaussian-process surrogate. Its initial design uses
  ``scipy.stats.qmc.Sobol`` when SciPy is available. References:
  `Christen and Fox (2005)
  <https://www.tandfonline.com/doi/abs/10.1198/106186005X76983>`_;
  `SciPy QMC documentation
  <https://docs.scipy.org/doc/scipy/reference/stats.qmc.html>`_.
