Calibration Methods Implemented In HydroModPy
=============================================

Scope
-----

This page documents the methods currently registered in
``hydromodpy.analysis.calibration.core.methods_dispatcher``:

- ``grid_search``
- ``random_search``
- ``nelder_mead``
- ``simplex``
- ``gp_mapping``
- ``da_mh_gp``

The goal is not to present a generic textbook overview of calibration methods.
It is to describe what the HydroModPy implementations actually do, what they
return, and how they should be interpreted.

Method Families
---------------

.. list-table::
   :header-rows: 1
   :widths: 18 16 14 16 36

   * - Method
     - Family
     - Nature
     - Distribution
     - Main role
   * - ``grid_search``
     - global search
     - deterministic
     - no
     - exhaustive low-dimensional baseline
   * - ``random_search``
     - global search
     - stochastic
     - no
     - simple bounded exploration baseline
   * - ``nelder_mead``
     - local search
     - deterministic
     - no
     - local refinement without derivatives
   * - ``simplex``
     - local search
     - deterministic
     - no
     - local refinement through ``scipy.optimize.fmin``
   * - ``gp_mapping``
     - surrogate search
     - stochastic
     - approximate
     - best fit plus approximate posterior-like map
   * - ``da_mh_gp``
     - Bayesian MCMC
     - stochastic
     - yes
     - posterior sampling with delayed-acceptance correction

Grid Search
-----------

Principle
^^^^^^^^^

``grid_search`` evaluates the Cartesian product of one grid per parameter.

If parameter :math:`i` uses :math:`n_i` grid nodes, the total number of model
evaluations is

.. math::

   N_{\mathrm{eval}} = \prod_{i=1}^{d} n_i.

Each candidate is evaluated with the true objective. The method is therefore
globally robust but grows exponentially with parameter dimension.

Sampling Rule
^^^^^^^^^^^^^

For parameter :math:`i`, HydroModPy uses:

- a linear grid when the parameter is not flagged as log-scale;
- a log-spaced grid when ``log_scale_indices`` contains that parameter index.

So the method can represent multiplicative uncertainty more naturally for
strictly positive parameters such as hydraulic conductivity.

Strengths
^^^^^^^^^

- deterministic and reproducible;
- useful to map the objective landscape in one or two dimensions;
- excellent as a reference method for small synthetic inverse problems.

Limitations
^^^^^^^^^^^

- not scalable beyond a small number of parameters;
- no uncertainty distribution is returned;
- no adaptive refinement.

Random Search
-------------

Principle
^^^^^^^^^

``random_search`` draws independent bounded samples and keeps the best one:

.. math::

   \theta^{(k)} \sim \mathcal{U}([l_1,u_1]\times\dots\times[l_d,u_d]).

The scientific meaning is simple: it is a global Monte Carlo baseline over the
parameter box.

Sampling Rule
^^^^^^^^^^^^^

For each parameter:

- uniform sampling in physical space by default;
- log-uniform sampling when the parameter index is listed in
  ``log_scale_indices``.

The method returns only the best candidate, not the full sample cloud, even
though the calibration launcher can later persist empirical distributions from
evaluated candidates.

Strengths
^^^^^^^^^

- trivial to configure;
- insensitive to local minima in the early exploration stage;
- easy benchmark baseline for synthetic tests.

Limitations
^^^^^^^^^^^

- statistically inefficient in moderate or high dimension;
- no local refinement;
- no native posterior correction.

Nelder-Mead And Simplex
-----------------------

Why Two Methods?
^^^^^^^^^^^^^^^^

HydroModPy exposes two wrappers over the same local derivative-free family:

- ``nelder_mead`` uses ``scipy.optimize.minimize(method="Nelder-Mead")``;
- ``simplex`` uses ``scipy.optimize.fmin``.

Scientifically, both are local simplex methods. They are kept separately mainly
for compatibility, benchmarking, and control over SciPy entry points.

Current Objective Handling
^^^^^^^^^^^^^^^^^^^^^^^^^^

Both implementations optimize a penalized, bound-aware objective. Out-of-bounds
candidates are clipped back to the feasible box for forward evaluation, and a
quadratic penalty is added outside bounds.

This means the methods remain local and unconstrained in their internal simplex
geometry, while the scientific model is evaluated only on admissible parameter
sets.

Initialization
^^^^^^^^^^^^^^

When no starting point ``x0`` is provided, both methods start from the midpoint
of each parameter interval:

.. math::

   \theta_{0,i} = \frac{l_i + u_i}{2}.

This makes them easy to launch, but it also means they can converge to
midpoint-dependent local minima when the search domain is wide or multimodal.

Strengths
^^^^^^^^^

- useful once the parameter region is already narrowed down;
- no gradient required;
- often efficient for low-dimensional smooth inverse problems.

Limitations
^^^^^^^^^^^

- purely local;
- sensitive to starting point and parameter scaling;
- no uncertainty quantification;
- not designed for strongly multimodal objectives.

Practical Interpretation
^^^^^^^^^^^^^^^^^^^^^^^^

When ``simplex`` or ``nelder_mead`` works well, it is usually because the
problem has already been made almost local by:

- narrow physical bounds,
- good initial parameter guesses,
- an objective surface that is smooth enough near the solution.

GP Mapping
----------

Scientific Role
^^^^^^^^^^^^^^^

``gp_mapping`` is an approximate surrogate-based method that combines:

1. an initial design,
2. one surrogate fit,
3. adaptive refinement with an upper-confidence-bound criterion,
4. a posterior-like sample cloud obtained by importance resampling on the
   surrogate mean.

It should be interpreted as an *approximate posterior mapping* method, not as
an exact Bayesian posterior sampler.

Current Algorithm
^^^^^^^^^^^^^^^^^

The implemented sequence is:

1. draw an initial Latin-hypercube design;
2. evaluate the true objective on that design;
3. fit a surrogate to :math:`-J(\theta)`;
4. iteratively sample a candidate pool, compute

   .. math::

      \mathrm{UCB}(\theta) = \mu(\theta) + \kappa\,\sigma(\theta),

   and evaluate the best-scoring candidates under the true model;
5. build an approximate posterior-like cloud by importance resampling from the
   surrogate mean.

Returned best parameters always come from true model evaluations, not from the
surrogate optimum alone.

Surrogate Used In Practice
^^^^^^^^^^^^^^^^^^^^^^^^^^

The implementation prefers a scikit-learn Gaussian process with an anisotropic
RBF kernel. However, on Windows or when the native GP optimizer is disabled,
the current code falls back to a deterministic inverse-distance-weighted
surrogate.

So the method name is stable, but the surrogate backend can differ across
platforms or runtime settings.

Parameter-Space Assumptions
^^^^^^^^^^^^^^^^^^^^^^^^^^^

The current implementation requires strictly positive bounds for all calibrated
parameters. This is because the method is built around a transformed parameter
space and is primarily intended for positive hydraulic parameters.

Strengths
^^^^^^^^^

- useful when each model evaluation is expensive;
- produces both a best-fit solution and an approximate distribution;
- adaptive refinement is more efficient than blind global sampling.

Limitations
^^^^^^^^^^^

- the returned sample cloud is not an exact posterior;
- surrogate quality controls result quality;
- currently restricted to strictly positive bounded parameters.

Delayed-Acceptance GP Metropolis-Hastings
------------------------------------------------

Scientific Role
^^^^^^^^^^^^^^^

``da_mh_gp`` is the most explicitly statistical method in the current core. It
implements a delayed-acceptance Metropolis-Hastings sampler with a Gaussian
process surrogate.

The delayed-acceptance logic is:

1. use a cheap surrogate for a first acceptance stage;
2. apply an exact correction with the true model at a second stage;
3. keep a Markov chain that targets the chosen posterior, up to finite-chain
   approximation and the negligible cache-rounding used to avoid repeated exact
   evaluations.

Likelihood And Prior
^^^^^^^^^^^^^^^^^^^^

This method assumes that the calibrated cost passed to it is an RMSE. The
implemented likelihood is

.. math::

   \log p(y \mid \theta)
   =
   -\frac{1}{2}
   \left(\frac{\mathrm{RMSE}(\theta)}{\sigma_{\mathrm{noise}}}\right)^2.

The posterior is then

.. math::

   \log p(\theta \mid y)
   =
   \log p(y \mid \theta) + \log p(\theta).

Current prior options are:

- uniform prior on the bounded domain when no explicit prior is given;
- diagonal Gaussian prior through ``prior_mean`` and ``prior_std``;
- custom ``logprior_fn`` when the user supplies one.

Because of this likelihood definition, the method currently requires
``objective_metric = "rmse"`` at configuration level.

Current Algorithm
^^^^^^^^^^^^^^^^^

The implemented sequence is:

1. draw an initial Sobol design in the parameter box;
2. evaluate the exact log-posterior on that design;
3. fit an internal lightweight Gaussian process to the log-posterior;
4. run a random-walk Metropolis-Hastings chain;
5. at each proposal:

   - perform a stage-1 accept/reject test with the surrogate,
   - if accepted, perform a stage-2 correction with the true posterior;

6. periodically retrain the surrogate using newly accumulated exact
   evaluations.

The implementation also supports:

- a full proposal covariance matrix,
- scalar or per-parameter proposal scales,
- an optional probability ``full_mh_prob`` to bypass delayed acceptance and do
  a full exact MH step.

Returned Outputs
^^^^^^^^^^^^^^^^

The method returns:

- ``x_best`` equal to the MAP sample found along the chain;
- ``samples`` equal to the post-burn-in, thinned posterior samples;
- chain diagnostics such as stage-1 and stage-2 acceptance rates;
- the full chain and log-posterior trace in metadata.

Strengths
^^^^^^^^^

- provides a genuine distribution-valued result rather than only one optimum;
- corrects surrogate bias through the second-stage exact evaluation;
- naturally exposes posterior uncertainty and identifiability structure.

Limitations
^^^^^^^^^^^

- slower to configure and interpret than direct-search methods;
- requires a meaningful ``sigma_noise`` and an RMSE-based observation model;
- chain quality still depends on proposal scaling, burn-in, and mixing.

Choosing A Method
-----------------

Use ``grid_search`` when:

- the dimension is very small,
- you want an explicit landscape baseline,
- robustness matters more than efficiency.

Use ``random_search`` when:

- you want a cheap global baseline,
- you need a stochastic method without strong assumptions,
- you want a reference against which local methods can be compared.

Use ``simplex`` or ``nelder_mead`` when:

- the feasible region is already narrow,
- you expect one dominant basin,
- you want a quick local refinement.

Use ``gp_mapping`` when:

- the forward model is expensive,
- you want both a best-fit point and an approximate uncertainty cloud,
- exact Bayesian correction is not required.

Use ``da_mh_gp`` when:

- uncertainty quantification is central,
- you want a posterior sample rather than only one optimum,
- the problem can be expressed coherently through an RMSE likelihood.

Current Limits Of The Built-In Portfolio
----------------------------------------

The current scientific portfolio does not yet include:

- gradient-based local optimization,
- Hamiltonian or affine-invariant MCMC samplers,
- parallel tempering,
- adaptive ensemble smoothers,
- exact multi-objective Pareto optimization.

So the present HydroModPy calibration stack is best read as:

- one solid bounded direct-search core,
- one approximate surrogate-posterior mapper,
- one delayed-acceptance Bayesian MCMC method,
- and a launcher layer able to expose multi-observable objectives on top of the
  same numerical engine.
