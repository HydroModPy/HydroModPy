Calibration Inverse Problem Formulation
=======================================

Scope
-----

HydroModPy calibration solves a bounded inverse problem. A parameter vector
:math:`\theta` is mapped by a forward model to simulated observables, and the
calibration machinery searches for parameter values that minimize a scalar cost.

Two closely related modes exist in the current code base:

- a generic single-series mode driven by ``CalibrationEngine`` with
  ``observed`` and ``simulator``;
- a multi-observable mode driven by a composite objective, notably used by
  ``ModelCalibrationLauncher``.

The mathematical conventions below are shared by both.

Parameter Vector And Bounds
---------------------------

The calibration parameter set is an ordered collection of parameters

.. math::

   \theta = (\theta_1, \theta_2, \dots, \theta_d)

with finite box bounds

.. math::

   \theta_i \in [l_i, u_i], \qquad l_i < u_i.

HydroModPy treats parameter order as a first-class contract. Optimizers work on
unnamed vectors, whereas the simulator works on named parameters. The
``CalibrationParameterSet`` object therefore provides a deterministic mapping
between the vector space and the named model parameter dictionary.

Forward Map
-----------

In the generic single-series setting, the forward model is

.. math::

   y^{\mathrm{sim}}(\theta) = \mathcal{M}(\theta)

and must return one simulated series compatible with the observed series
:math:`y^{\mathrm{obs}}`.

In the multi-observable setting, the forward model returns a richer raw payload
from which several observable blocks are selected:

.. math::

   \mathcal{P}(\theta) = \text{raw model payload},

followed by one selector per block

.. math::

   y_b^{\mathrm{sim}}(\theta) = \mathcal{S}_b(\mathcal{P}(\theta)).

Single-Series Metrics
---------------------

The built-in scalar metrics are:

- RMSE,
- MAE,
- NSE,
- NSElog,
- KGE.

For one block or one single-series problem with :math:`n` valid data pairs:

.. math::

   \mathrm{RMSE}
   =
   \sqrt{\frac{1}{n}\sum_{t=1}^{n}
   \left(y_t^{\mathrm{sim}} - y_t^{\mathrm{obs}}\right)^2}

.. math::

   \mathrm{MAE}
   =
   \frac{1}{n}\sum_{t=1}^{n}
   \left|y_t^{\mathrm{sim}} - y_t^{\mathrm{obs}}\right|

.. math::

   \mathrm{NSE}
   =
   1
   -
   \frac{\sum_{t=1}^{n}
   \left(y_t^{\mathrm{sim}} - y_t^{\mathrm{obs}}\right)^2}
   {\sum_{t=1}^{n}
   \left(y_t^{\mathrm{obs}} - \bar y^{\mathrm{obs}}\right)^2}

.. math::

   \mathrm{NSE}_{\log}
   =
   \mathrm{NSE}\!\left(\log y^{\mathrm{obs}}, \log y^{\mathrm{sim}}\right)

provided both series are strictly positive.

The implemented Kling-Gupta efficiency is the 2009 form:

.. math::

   \mathrm{KGE}
   =
   1 - \sqrt{(r-1)^2 + (\alpha-1)^2 + (\beta-1)^2}

with:

.. math::

   r = \mathrm{corr}(y^{\mathrm{obs}}, y^{\mathrm{sim}}), \qquad
   \alpha = \frac{\sigma_{\mathrm{sim}}}{\sigma_{\mathrm{obs}}}, \qquad
   \beta = \frac{\mu_{\mathrm{sim}}}{\mu_{\mathrm{obs}}}.

Metric-To-Cost Conversion
-------------------------

Optimizers minimize a cost. HydroModPy therefore converts the chosen metric into
one scalar minimization target.

For metrics where lower is better:

- RMSE,
- MAE,

the cost is the metric itself:

.. math::

   J(\theta) = \mathrm{metric}(\theta).

For metrics where higher is better:

- NSE,
- NSElog,
- KGE,

the cost is

.. math::

   J(\theta) = 1 - \mathrm{metric}(\theta).

This means that all built-in methods ultimately minimize one scalar quantity,
regardless of whether the reported score is an error metric or an efficiency
metric.

Composite Multi-Observable Objective
------------------------------------

The launcher-based calibration path can combine several observable blocks into
one weighted composite objective. Each block :math:`b` has:

- one observed vector :math:`y_b^{\mathrm{obs}}`,
- one selector :math:`\mathcal{S}_b`,
- one metric,
- one raw weight :math:`w_b > 0`.

The block score is first converted to one raw cost:

.. math::

   J_b(\theta).

When cost normalization is enabled, HydroModPy computes

.. math::

   \tilde J_b(\theta) = \frac{J_b(\theta)}{s_b}

where :math:`s_b` is the reference scale of the block.

The default reference-scale rule is:

- for metrics already expressed as efficiencies (`NSE`, `NSElog`, `KGE`):
  :math:`s_b = 1`;
- for error metrics (`RMSE`, `MAE`):
  use the interquartile range of the observed block when available,
  otherwise its standard deviation,
  otherwise a small positive fallback scale.

When weight normalization is enabled, the effective weights are

.. math::

   \tilde w_b = \frac{w_b}{\sum_k w_k}.

The total composite objective is then

.. math::

   J(\theta)
   =
   \sum_{b=1}^{B} \tilde w_b\,\tilde J_b(\theta).

This is the current scientific contract behind multi-observable calibration in
``launchers/model_calibration``.

Bound Handling
--------------

At engine level, any candidate outside bounds is immediately assigned

.. math::

   J(\theta) = +\infty.

This is the generic rule used by the calibration engine.

The two local direct-search methods, ``simplex`` and ``nelder_mead``, go one
step further internally. They evaluate a penalized cost:

.. math::

   J_{\mathrm{pen}}(\theta)
   =
   J\!\left(\Pi_{[l,u]}(\theta)\right)
   + \lambda \sum_i
   \left[
     \max(l_i - \theta_i, 0)^2
     +
     \max(\theta_i - u_i, 0)^2
   \right]

with:

- :math:`\Pi_{[l,u]}` the clipping operator back to the feasible box,
- :math:`\lambda = 10^4` in the current implementation.

So the optimizer can move outside the box numerically, but the scientific model
is always evaluated on clipped, physically admissible parameter values.

Best-Fit Versus Distribution-Valued Results
-------------------------------------------

All methods return a best parameter vector :math:`\theta^\star`, a best cost,
and a number of expensive model evaluations.

Some methods also return a sample cloud in parameter space:

- ``gp_mapping`` returns an approximate posterior-like sample produced by
  surrogate importance resampling;
- ``da_mh_gp`` returns MCMC samples and therefore a genuine distribution-valued
  result relative to its chosen likelihood and prior.

This distinction matters scientifically:

- a best-fit result summarizes one optimum;
- a sample distribution encodes uncertainty, multimodality, and
  practical identifiability.

Interpretation Notes
--------------------

- The generic single-series path and the launcher composite path share the same
  minimization philosophy, but not the same payload shape.
- The scientific meaning of a distribution depends on the method:
  ``gp_mapping`` is approximate and surrogate-based,
  whereas ``da_mh_gp`` is a delayed-acceptance MCMC scheme with an explicit
  posterior target.
- For stochastic methods, one calibrated optimum is often less informative than
  the geometry of the retained sample cloud.
