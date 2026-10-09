# The inverse problem of a calibration

A calibration turns a question about the site, such as "which conductivity makes the model
reproduce the gauge and the mapped streams?", into the search for the minimum, or the root,
of one number computed from the model. This page writes that number down: the space the
search walks, the cost each objective block adds, the metrics, the root a network
criterion has instead of a minimum, the likelihood of the one sampler, and what the width
printed beside a value means. Every option of every method is in the reference
{doc}`../../reference/calibration-methods`.

The tables of metrics and methods on this page are generated from the code at each build,
so they cannot name a metric or a method the code does not have.

## What the search walks

The file declares the parameters $\theta = (\theta_1, \dots, \theta_p)$, each with a box
$[a_i, b_i]$ under {toml}`calibration.parameters.<name>.bounds`. The search does not walk
$\theta_i$ itself. It walks $y_i = g(\theta_i)$, with the transform
{toml}`calibration.parameters.<name>.transform`:

$$
g(\theta) = \theta \ \ \text{(identity)}, \qquad
g(\theta) = \log_{10}\theta \ \ \text{(log)}, \qquad
g(\theta) = \ln\frac{\theta}{1 - \theta} \ \ \text{(logit)}.
$$

A conductivity spans several decades, so it is walked in $\log_{10}$: a step of the search
is then a factor on $K$, not an increment. A logit needs $0 < a_i < b_i < 1$. The calibrated
problem is

$$
\theta^\ast = \arg\min_{\theta \in [a, b]} J(\theta),
$$

where $J$ is the cost defined below. Every evaluation of $J$ is one run of the model, with
the values of $\theta$ written in place of the configuration they name. A parameter not
listed keeps the value of the file. A method that samples instead of stepping draws from
the prior {toml}`calibration.parameters.<name>.prior`: uniform on $[a_i, b_i]$, uniform on
$[\log_{10} a_i, \log_{10} b_i]$, or normal.

## From outputs to one cost

An output pairs a simulated quantity with what it is compared to: a station of a loaded
record, or a mapped stream network. An objective block $b$ scores one or more outputs with
one metric, which gives a raw cost $c_b(\theta)$, always to be minimised. The blocks add up
as

$$
J(\theta) = \sum_b \tilde w_b \; T_b\!\left(\frac{c_b(\theta)}{s_b}\right),
\qquad \tilde w_b = \frac{w_b}{\sum_k w_k}.
$$

- $w_b$ is {toml}`calibration.objective_blocks.weight`. The weights are divided by their sum,
  so only their ratios matter. A phase that writes a share table in
  {toml}`calibration.phases.objective_blocks` replaces them for that phase.
- $s_b$ is 1 unless {toml}`calibration.objective_blocks.normalize_cost` is true. Then, for an
  error ($\mathrm{RMSE}$, $\mathrm{MAE}$), $s_b$ is the standard deviation of the
  observations, or their mean absolute value when that is zero. For a network distance,
  each distance is divided by the validity length $L$ of its output, two mesh cells under
  `"auto"`, so a gap of one validity length costs 1. An efficiency score is already a pure
  number, and the key is refused on it.
- $T_b$ is {toml}`calibration.objective_blocks.transform`: the identity,
  $\log_{10}(c + 10^{-6})$, or $-1/(c + 10^{-6})$. It reshapes a cost before the weighting.
  It is not the log of the series, which is what the metric `nse_log` takes.

Without normalisation, a cost in metres and a cost without unit add up, and the unit sets
the balance instead of the weight. A file with no block scores one series with
{toml}`calibration.objective` and {toml}`calibration.variable`: one block of weight one.

Only the dated pairs inside the scoring window enter $c_b$.
{toml}`calibration.scoring_window` names the first and last dates that count, so the
spin-up of the model stays out of the cost at any time step.

## The metrics

Each metric declares its family, the unit of its cost, whether it reads a series or a
network output, and whether its cost is the absolute value of a signed residual. In the
formulas, $s_t$ is the simulated value and $o_t$ the observed one at the same date, over
the $n$ dated pairs the scoring window keeps.

```{hmp-calibration-metrics}
```

## A root, not a minimum

The two network metrics compare the simulated network with a mapped one through two mean
downslope distances: $D_{so}$ from the simulated network to the map, and $D_{os}$ back
({doc}`../downslope-distance`). Too low a conductivity leaves too much simulated stream and
$D_{so}$ large. Too high a conductivity leaves too little, and $D_{os}$ large. The balance
is where the signed residual

$$
J_s(\theta) = D_{so}(\theta) - D_{os}(\theta)
$$

changes sign. `distance_gap` scores $\lvert J_s \rvert$, but its zero is a crossing, not
the minimum of a smooth cost: the simulated network changes cell by cell, so $J_s$ steps
over zero instead of reaching it. The method `bisection` uses that. It sweeps the box in
log space, keeps the two neighbours where the sign changes, and halves that bracket until
its relative width falls under the precision {toml}`calibration.tolerance`. It never stops
on the size of $\lvert J_s \rvert$, which may never get small. The value it returns is the
completed trial of lowest cost inside the final bracket.

With a minimal and a maximal map, each bound has its own root, $K^\ast_{\min}$ and
$K^\ast_{\max}$. The value returned is their weighted geometric mean,

$$
\log_{10} K^\ast = w_{\min} \log_{10} K^\ast_{\min} + w_{\max} \log_{10} K^\ast_{\max},
\qquad w_{\min} + w_{\max} = 1,
$$

with the weights {toml}`calibration.outputs.<name>.extent.weights.minimal` and
{toml}`calibration.outputs.<name>.extent.weights.maximal`.

What the root identifies is the ratio of the conductivity to the recharge, not $K$ alone,
as long as the drains take their conductance from $K$. The argument is in
{doc}`../downslope-distance`.

## The methods

A method proposes the next values of $\theta$ from the costs it has seen. It changes how the
minimum is found, never what is minimised. A search that names none gets `bisection` when it
moves one parameter in log space on signed criteria only, and `scipy_nelder_mead`
otherwise.

```{hmp-calibration-methods}
:summary:
```

## The likelihood of `da_mh_gp`

`da_mh_gp` is the only method that samples a distribution instead of returning one optimum.
It reads the cost of each trial as an $\mathrm{RMSE}$ and builds the log-posterior

$$
\ln \pi(y) = -\frac{1}{2}\left(\frac{\mathrm{RMSE}(\theta)}{\sigma_n}\right)^2 + \ln p(y) + \text{const},
$$

where $\sigma_n$ is its option `sigma_noise` and $y = g(\theta)$ is the point in the space the
search walks. The prior $p$ is flat on the box, unless the options `prior_mean` $\mu$ and
`prior_std` $\sigma_p$ are set:

$$
\ln p(y) = -\frac{1}{2}\sum_i \left(\frac{y_i - \mu_i}{\sigma_{p,i}}\right)^2 .
$$

A proposal $y' = y + \varepsilon$, with $\varepsilon \sim \mathcal{N}(0, \sigma_q^2)$ and
$\sigma_q$ the option `proposal_sigma`, is dropped when it leaves the box. A Gaussian process
$\tilde\pi$, fitted to the log-posteriors already computed, screens it first. One run of the
model then corrects the acceptance, following {cite:t}`christen2005`:

$$
\alpha_1 = \min\!\left(1,\ e^{\tilde\pi(y') - \tilde\pi(y)}\right), \qquad
\alpha_2 = \min\!\left(1,\ e^{[\ln\pi(y') - \ln\pi(y)] - [\tilde\pi(y') - \tilde\pi(y)]}\right).
$$

A proposal is solved only when it passes the first stage, which is what saves runs. The
second stage makes the chain target $\pi$ and not its surrogate. The candidate the
calibration returns is the state of highest log-posterior.

Read this likelihood for what it is. A Gaussian likelihood of $n$ independent residuals of
standard deviation $\sigma$ is $-\tfrac{n}{2}(\mathrm{RMSE}/\sigma)^2$. The one above has no
$n$: it scores the whole record as one residual of size $\mathrm{RMSE}$. The width of the
sample therefore follows $\sigma_n$, a number of the file, and not the length of the record.
It is a posterior on the parameters only when $\sigma_n$ is the error of that one aggregate,
which nothing in the run establishes. On any metric other than `rmse`, the number squared is
not a residual at all. Report the chain as the spread of the values that score within a few
$\sigma_n$ of the best, and state $\sigma_n$ beside it.

## The width beside a value

Every calibrated value is printed with an interval, and the interval never moves the value.
Three methods, set by {toml}`calibration.uncertainty.method`, produce it. None of them is a
posterior.

- `cost_profile`, the default, reads the trials already run. With $J^\ast$ the best cost and
  $\tau$ the tolerance {toml}`calibration.uncertainty.tolerance`, a trial is kept when
  $J \leq J^\ast(1 + \tau)$ in relative mode, or $J \leq J^\ast + \tau$ in absolute mode. The
  interval of $\theta_i$ is the range of $\theta_i$ over the kept trials. The default is
  $\tau = 0.05$, relative. A phase scored on network distances only takes one mesh cell,
  absolute, because a fraction of a cost solved at zero is zero.
- `multistart` runs the whole search again from other starting points and reports the spread
  of the optima. A parameter whose optima span more than a factor ten is flagged as not
  identified.
- `linearized` differentiates the simulated values $f_k$ at the answer, one run per
  parameter with a forward step of {toml}`calibration.uncertainty.perturbation` times the
  value, and reports the first-order covariance

  $$
  C = s^2 \left(\mathbf{J}^\top \mathbf{J}\right)^{-1}, \qquad
  \mathbf{J}_{ki} = \frac{\partial f_k}{\partial \theta_i}, \qquad
  s^2 = \frac{\mathbf{r}^\top \mathbf{r}}{n - p},
  $$

  with $\mathbf{r}$ the residuals and $n - p \ge 1$. It prints $\sigma_i = \sqrt{C_{ii}}$ and
  the correlation $C_{ij} / (\sigma_i \sigma_j)$ that names the parameter each one trades
  off against.

A narrow `cost_profile` interval means either that the cost rises fast around the value, or
that the search never tried far from it. A high correlation means two parameters were not
told apart: they are one number and a ratio.
{doc}`../../understand/how-sure` says how to read each case.

## Limits

- A low cost does not identify a parameter on its own. Several parameter sets can reach the
  same cost, and a calibration on one criterion returns one of them.
- The weights of a multi-target cost are a modelling decision. Changing them changes which
  model is called the best.
- In a staged calibration, each phase is conditional on the values the earlier phases froze.
  Its width does not carry their uncertainty.
- The observed data enter the cost only. A mapped network or a gauged record is never an
  input of the model it scores.

## See also

- {doc}`../downslope-distance`: the network criterion, its equations and its biases.
- {doc}`../../reference/calibration-methods`: every method with its options, every metric.
- {cite:t}`abherve2023`: a calibration of catchment hydraulic properties on the stream
  network.
- {doc}`../bibliography`: the full list of cited references.
