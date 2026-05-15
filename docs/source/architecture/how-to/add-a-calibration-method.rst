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

   from typing import ClassVar

   from hydromodpy.calibration.adapters.base import (
       CalibrationMethodAdapter, EvaluationResult, ParamSuggestion, ParameterSpace,
   )


   class MyMethodAdapter:
       method_name: ClassVar[str] = "mymethod"

       def configure(self, params: ParameterSpace, options: dict) -> None:
           self._params = params
           self._max_iter = int(options.get("max_iter", 100))
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

Register in the engine
----------------------

The engine resolves adapters through a name-keyed registry in
``hydromodpy/calibration/adapters/__init__.py``. Add the entry:

.. code-block:: python

   from hydromodpy.calibration.adapters.mymethod import MyMethodAdapter

   _ADAPTERS = {
       ...,
       MyMethodAdapter.method_name: MyMethodAdapter,
   }

Optional dependencies
---------------------

If your method depends on a heavy or optional package
(``cma``, ``cmaes``, ``scikit-learn``, ``torch``), import it
inside ``configure`` and raise a clear ``ImportError`` when it is
missing:

.. code-block:: python

   def configure(self, params, options):
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

- **Unit** under ``tests/unit/calibration/adapters/`` for
  ``configure`` (option parsing), ``ask`` (point generation),
  ``tell`` (state update), ``best`` (post-loop selection).
- **Synthetic benchmark** under
  ``hydromodpy/calibration/cases/`` reusing
  ``recession_brutsaert`` or ``groundwater_1d``: assert the method
  recovers the truth within a method-specific
  ``METHOD_ABS_TOL`` tolerance.
- **Integration** under ``tests/integration/calibration/`` for a
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
