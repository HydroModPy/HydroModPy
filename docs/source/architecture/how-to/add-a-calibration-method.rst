Add a Calibration Method
========================

Calibration in HydroModPy runs an ask/tell loop: an optimizer
proposes a parameter point, the engine evaluates it, the optimizer
ingests the result. Optimizers are plugged through *adapters* under
``hydromodpy/calibration/adapters/``.

Today nine adapters ship: ``Grid``, ``RandomSearch``,
``ScipyNelderMead``, ``ScipyDE``, ``Optuna`` (TPE / CMA-ES samplers),
``CmaEs``, ``GpMapping``, ``DaMhGp``, plus the prior-sampling helper.

Contract
--------

A calibration adapter exposes an ``ask`` / ``tell`` pair plus a small
configuration surface. The Protocol lives in
``hydromodpy/calibration/adapters/__init__.py`` (or the matching
contracts module).

.. code-block:: python

   class CalibrationMethodAdapter(Protocol):
       method_name: ClassVar[str]

       def configure(self, params: ParameterSpace, options: dict) -> None: ...

       def ask(self) -> ParamSuggestion: ...

       def tell(self, result: EvaluationResult) -> None: ...

       def best(self) -> EvaluationResult | None: ...

``ParameterSpace`` aggregates the ``[calibration.parameters.*]``
declarations (bounds, transform, prior, dotted path).
``ParamSuggestion`` carries one parameter point;
``EvaluationResult`` carries the matching scalar objective plus
metadata.

Files to create
---------------

A new method called ``mymethod``:

.. code-block:: text

   hydromodpy/calibration/adapters/mymethod.py

Skeleton:

.. code-block:: python

   from hydromodpy.calibration.optim.optimizer import (
       EvaluationResult,
       ParamSuggestion,
       register_optimizer,
   )
   from hydromodpy.calibration.optim.parameters import ParameterSpace


   @register_optimizer("mymethod")
   class MyMethodOptimizer:
       def __init__(self, space: ParameterSpace, *, max_iter: int = 100) -> None:
           self._space = space
           self._max_iter = max_iter
           self._iter = 0
           self._best: EvaluationResult | None = None

       def ask(self) -> ParamSuggestion:
           # propose the next point in the internal sampling space
           ...

       def tell(self, result: EvaluationResult) -> None:
           self._iter += 1
           if self._best is None or result.objective < self._best.objective:
               self._best = result

       def best(self) -> EvaluationResult | None:
           return self._best

       def converged(self) -> bool:
           return self._iter >= self._max_iter

Registration
------------

There is no registry dict to edit. ``@register_optimizer("mymethod")``
publishes the class under the name accepted by
``CalibrationConfig.method`` and by ``build_optimizer``. The registry
(``hydromodpy/calibration/optim/optimizer.py``) auto-discovers every
module under ``hydromodpy/calibration/adapters/`` on the first
``build_optimizer`` call, so dropping the file in that package is all
the wiring required.

Third-party methods shipped outside the repository register through the
``hydromodpy.optimizer`` entry-point group instead.

Saying what the engine can be handed
------------------------------------

An engine refuses an impossible pairing in its constructor, which is right but
late: a staged calibration builds phase two's optimizer only when phase two
starts, after phase one has spent its whole solve budget. A class attribute
``traits = EngineTraits(...)`` states the same facts where a check can read them
before anything solves.

.. code-block:: python

   from hydromodpy.calibration.optim.optimizer import EngineTraits


   @register_optimizer("mymethod")
   class MyMethodOptimizer:
       traits = EngineTraits(
           max_parameters=1,            # None means any number
           required_transform="log",    # the variable the stopping rule is written in
           needs_signed_residual=True,  # the criterion has to publish one
           supports_parallel=False,
           tolerance_option="rel_tol",       # this engine's own stopping option
           tolerance_reads="relative_value",  # how that option reads its number
       )

The last two are what lets a file state its precision once. ``calibration.tolerance``
is a relative precision on the parameter, and it is translated into whichever
option the engine names:

``tolerance_reads="relative_value"``
   the option is already a relative width on the parameter's own value, so the
   number passes through unconverted. Declare it only on an engine that also
   declares ``required_transform="log"``, where a ratio and a width in the search
   variable are the same statement.

``tolerance_reads="search_width"``
   the option is an absolute width in the variable the search walks, so the
   precision is converted into that variable: ``log10(1 + tolerance)`` decades on
   a log-transformed parameter, a fraction of the declared interval on any other,
   and the strictest of them when the search moves several.

An engine that stops on its evaluation budget, or on the spread of its own
population, declares neither and leaves them ``None``. A precision handed to it
is then refused with a message naming what does bound it, rather than accepted
and dropped: a run reporting that it honoured a request it never read is worse
than a run refusing the request.

Everything a stopping rule needs beyond that precision stays in
``optimizer_kwargs``, in the engine's own units, which is how a published call is
reproduced verbatim. Stating both the precision and the option it writes is
refused, before the first solve.

What a restart-based uncertainty asks of an engine
--------------------------------------------------

``[calibration.uncertainty] method = "multistart"`` runs the whole search several
times and reports the spread of the optima it reaches. Two traits decide what an
engine may be handed.

``restarts_explore_differently``
   whether repeating this engine can land anywhere else. Permissive by default: a
   stochastic sampler explores differently on a new seed and declares nothing.
   ``grid`` and ``bisection`` declare ``False``, because an exhaustive sweep and a
   root search are the same computation twice, and reporting the spread of
   identical runs as an uncertainty states a certainty nothing established. A file
   asking for restarts on one of them is refused, in the preflight, before the
   first solve.

``accepts_a_start_point``
   whether the engine takes ``start_at``, a coordinate per calibrated parameter in
   transformed space. Only ``scipy_nelder_mead`` and ``cma_es`` do, and they are
   exactly the engines a new seed cannot move: the simplex is built around
   ``transformed_prior_center(space)`` and would otherwise return the same answer
   every time. Accept the keyword and begin there instead of at your own default.

The first restart is left with the engine's own start and the file's own seed, so
it is the single search it replaces: the answer a file already published stays in
the set and the others are added around it. The remaining starts are drawn from the
declared priors with a seeded generator, so a rerun draws the same set.

The constraint the method obeys is stated by the project: a calibration always
reports one manipulable value, and an interval sits beside it, never in its place.
So the best restart IS the answer, unchanged in kind from a single search, and the
spread is reported next to it, with a parameter whose optima span more than a
factor ten flagged as not identified by that calibration.

Why a linearized covariance is not declared beside it
-----------------------------------------------------

FOSM would give standard deviations *and* correlations for the price of one run
per parameter, which is cheaper than restarting the whole search. It is not
declared, and the obstacle is one line of the contract rather than the arithmetic:
:class:`EvaluationResult` carries ``objective_value``, a scalar, and ``components``,
a mapping of scalar diagnostics. A Jacobian is built from the simulated value *at
each observation*, and no trial returns that vector.

So the first change is to the objective's return contract and its callers, which is
the same axis the ``observes`` bridge cost, and only then the perturbation loop and
its validation. Two shortcuts look tempting and are not honest ones. Approximating
the cost's Hessian instead of the observation Jacobian is a coarser method and must
not be published under the same name. And a residual variance only exists where the
cost is built from residuals: ``cost_is_dimensionless`` on the criterion contract
already marks the scores where it does not, and a linearized method has to refuse
those the way ``weighting = "error"`` already does.

Optional dependencies
---------------------

If your method depends on a heavy or optional package
(``cma``, ``cmaes``, ``scikit-learn``, ``torch``), import it at module
level and let the ``ImportError`` propagate: auto-discovery treats an
adapter that fails to import as simply unregistered, so a missing
optional never breaks the other methods.

.. code-block:: python

   try:
       import cma  # noqa: F401
   except ImportError as exc:
       raise ImportError(
           "method 'mymethod' requires the 'calibration' extra "
           "(pip install -e \".[calibration]\")"
       ) from exc

Sampling-space coordinates
--------------------------

The engine asks the optimizer in the **sampling space** declared by
``[calibration.parameters.*].transform`` (``identity``, ``log``,
``logit``). Samples are converted back to physical units before
injection. Implementations should sample uniformly in
``[0, 1]^n`` or in the configured prior distribution; the engine
takes care of the inverse transform.

Distribution-valued methods
---------------------------

Methods that produce a posterior (``DaMhGp``, ``GpMapping``) expose
the samples through the ``calibration_posterior`` figure. Make sure
your adapter writes the per-iteration trace through ``tell`` so the
post-loop figure registry can plot it.

Add a new figure if your method has unusual diagnostics; see
:doc:`add-a-figure`.

Tests to add
------------

- **Unit** under ``tests/unit/calibration/`` for
  ``configure`` (option parsing), ``ask`` (point generation),
  ``tell`` (state update), ``best`` (post-loop selection).
- **Synthetic benchmark** under
  ``hydromodpy/calibration/cases/`` reusing
  ``recession_brutsaert`` or ``groundwater_1d``: assert the method
  recovers the truth within a method-specific
  ``METHOD_ABS_TOL`` tolerance.
- **Integration** under ``tests/integration/`` for a
  short ``hmp run`` calibration on a tiny case.

Pitfalls flagged by the layer matrix
------------------------------------

- ``calibration`` may import ``physics``, ``data``, ``spatial``,
  ``solver``, ``simulation``. The
  ``calibration -> results`` and
  ``calibration -> <root>`` edges are documented tolerances; do
  not introduce new cross-edges into ``display`` or ``analysis``
  from inside an adapter.
- Adapters must remain stateless across runs. Persist ask/tell state
  inside the adapter instance, never on disk: the engine handles
  persistence and resume through ``CheckpointStore`` and the
  DuckDB ``calibration_iterations`` table.
- Methods that read from ``simulation/results/`` must do it through
  the engine API, not by reaching into the Run store directly.

See also
--------

- :doc:`../packages/calibration` for the calibration package map.
- :doc:`/user_guide/workflows/calibration` for the user-facing hub.
- :doc:`/architecture/calibration/calibration-guide` for the full
  operational reference (TOML, optimizer catalogue, storage rules,
  pitfalls, Python API).
