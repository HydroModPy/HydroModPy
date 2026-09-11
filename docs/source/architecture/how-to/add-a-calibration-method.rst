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

What a restart-based uncertainty would need from an engine
---------------------------------------------------------

``[calibration.uncertainty]`` declares ``cost_profile`` only. A restart-based
method, running the search several times and reporting the spread of the optima it
reaches, is the obvious next one and it is not implemented, for a reason that
belongs here rather than in a changelog: **no engine lets a caller say where the
search starts**.

- ``scipy_nelder_mead`` builds its simplex around ``transformed_prior_center(space)``,
  a constant. Its seed is accepted and discarded, so repeating the search returns
  the same answer however the seed moves.
- ``bisection`` and ``grid`` are deterministic by construction: a root search and
  an exhaustive sweep have nothing to restart.
- ``cma_es`` does perturb its ``x0`` between its own ``restarts``, but those serve
  its convergence and it still reports one best, not a distribution.

So a seed-only implementation would refuse on ``scipy_nelder_mead``, which is the
engine the ``matching_hydrographic_network`` protocol uses for its second stage:
it would decline exactly the calibration it exists for. Doing it properly means
one more axis, an initial point an engine may be given, declared in
:class:`EngineTraits` alongside the stopping rule and honoured by every engine
that has a start. Two mechanisms, a varied seed and a varied start, are what a
half-version ends up carrying; one explicit start is what makes it uniform.

The constraint the method has to respect is stated by the project: a calibration
always reports one manipulable value, and an interval sits beside it, never in its
place. So the best of the restarts stays the answer, and the spread is reported
next to it.

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
