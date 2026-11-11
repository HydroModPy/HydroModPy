Add a calibration method
========================

Calibration in HydroModPy runs an ask/tell loop: an optimizer
proposes a parameter point, the engine evaluates it, the optimizer
ingests the result. Optimizers are plugged through *adapters* under
``hydromodpy/calibration/optim/adapters/``.

Each module of the folder registers one method under a name: ``grid``, ``lhs``,
``random_search``, ``scipy_nelder_mead``, ``scipy_de``, ``optuna``, ``cma_es``,
``bisection`` and ``gp_mapping`` at the time of writing, and ``da_mh_gp``, which still runs
when a file names it but is left out of the list the docs and the refusals print.
``announced_optimizers()`` in ``optim/optimizer.py`` prints the live list, and
``optimizers.names()`` adds the methods that declare ``announced=False``.

Contract
--------

A calibration adapter exposes an ``ask`` / ``tell`` pair plus a small
configuration surface. The Protocol, ``Optimizer``, lives in
``hydromodpy/calibration/optim/optimizer.py``.

.. code-block:: python

   class Optimizer(Protocol):
       name: str

       def ask(self, n: int = 1) -> list[ParamSuggestion]: ...

       def tell(self, results: list[EvaluationResult]) -> None: ...

       def suggest_next(self) -> ParamSuggestion: ...

       def best(self) -> EvaluationResult | None: ...

       def converged(self) -> bool: ...

``ParameterSpace`` aggregates the ``[calibration.parameters.*]``
declarations (bounds, search space, sampling, dotted path).
``ParamSuggestion`` carries one parameter point;
``EvaluationResult`` carries the matching scalar objective plus
metadata. ``ask`` proposes one or more points at once; ``tell`` feeds back
the matching batch of results.

The session journal sees what ``ask`` returns. Each point becomes a ``proposed``
line in the order of the list, with the rank of the call (``batch``), before any
of them is evaluated. So the order of the list is a part of the contract, and an
adapter that reorders its points between two calls of ``ask`` changes the
trial numbers.

Files to create
---------------

A new method called ``mymethod``:

.. code-block:: text

   hydromodpy/calibration/optim/adapters/mymethod.py

Skeleton:

.. code-block:: python

   from typing import ClassVar
   from pydantic import BaseModel
   from hydromodpy.calibration.optim.optimizer import (
       EngineTraits,
       EvaluationResult,
       ParamSuggestion,
   )
   from hydromodpy.calibration.optim.parameters import ParameterSpace


   class MyMethodConfig(BaseModel):
       max_trials: int = 100


   class MyMethodOptimizer:
       name: ClassVar[str] = "mymethod"
       options: ClassVar[type[BaseModel] | None] = MyMethodConfig
       traits = EngineTraits(takes_max_trials=True)

       def __init__(self, space: ParameterSpace, *, max_trials: int = 100) -> None:
           self._space = space
           self._max_trials = max_trials
           self._iter = 0
           self._best: EvaluationResult | None = None

       def ask(self, n: int = 1) -> list[ParamSuggestion]:
           # propose n points in the internal search space
           ...

       def tell(self, results: list[EvaluationResult]) -> None:
           self._iter += len(results)
           for result in results:
               if self._best is None or result.cost < self._best.cost:
                   self._best = result

       def suggest_next(self) -> ParamSuggestion:
           return self.ask(1)[0]

       def best(self) -> EvaluationResult | None:
           return self._best

       def converged(self) -> bool:
           return self._iter >= self._max_trials

Registration
------------

There is no registry dict to edit. A method is published under the id its
``name`` attribute declares, the name accepted by ``CalibrationConfig.method``
and by ``build_optimizer``.

An in-tree class is declared in ``hydromodpy/calibration/optim/optimizer.py``, under
:data:`_BUILTIN_PATHS`. A third-party method is published through one entry point
of the ``hydromodpy.calibration.optimizer`` group, pointing to the class.

Declaring the options
----------------------

Registering the class is not enough: ``method_options`` is validated
against a typed model before it ever reaches the adapter constructor.
The class declares its options model on its ``options`` class attribute:
``options: ClassVar[type[BaseModel] | None] = MyMethodConfig``. The model carries
one field per accepted constructor keyword (and no ``method`` field).
A phase, ``[calibration]`` and the protocol's
``steady_method_options`` / ``transient_method_options`` are checked against
it when the file loads, by ``method_options_problem``: an unknown key or a
wrong type is refused there, naming the phase, instead of inside the adapter
when that phase starts. ``hmp check`` runs the same check.

Search methods ship with HydroModPy and are not plugged from outside. A
search of your own does not go through this registry: write an object
that satisfies ``Optimizer`` (``ask``, ``tell``, ``suggest_next``,
``best``, ``converged``, ``name``) and hand it to
``CalibrationEngine(optimizer=...)`` (``optim/engine.py``), with no
registration.

``converged`` says whether the engine met a rule of its own. The engine loop
turns it into the stop state of the session (``stop_state`` in
``optim/stopping.py``): an engine that declares no stopping option and uses
its whole budget spent it, whatever ``converged`` says, since its own end
then only coincides with the budget.

Saying what the engine can be handed
------------------------------------

An engine refuses an impossible pairing in its constructor, which is right but
late: a staged calibration builds phase two's optimizer only when phase two
starts, after phase one has spent its whole solve budget. A class attribute
``traits = EngineTraits(...)`` states the same facts where a check can read them
before anything solves.

.. code-block:: python

   from hydromodpy.calibration.optim.optimizer import EngineTraits


   class MyMethodOptimizer:
       name = "mymethod"
       traits = EngineTraits(
           max_parameters=1,            # None means any number
           required_search_space="log",  # the variable the stopping rule is written in
           needs_signed_residual=True,  # the criterion has to publish one
           supports_parallel=False,
           reach=lambda options, dim: 4,  # solves it can use at once, None for no limit
           takes_max_trials=True,       # built knowing the budget of the search
           takes_width=True,            # built knowing how many trials run side by side
           fixed_plan=False,            # True when it can be asked for all that is left
           precision_option="rel_tol",       # this engine's own stopping option
           precision_reads="relative_value",  # how that option reads its number
           announced=False,             # runs when named, but not in the printed list
           libraries=("scipy",),        # distributions whose versions session.json records
       )

The last two are what lets a file state its precision once. :toml:`calibration.precision`
is a relative precision on the parameter, and it is translated into whichever
option the engine names:

``precision_reads="relative_value"``
   the option is already a relative width on the parameter's own value, so the
   number passes through unconverted. Declare it only on an engine that also
   declares ``required_search_space="log"``, where a ratio and a width in the search
   variable are the same statement.

``precision_reads="search_width"``
   the option is an absolute width in the variable the search walks, so the
   precision is converted into that variable: ``log10(1 + precision)`` decades on
   a parameter searched in log space, a fraction of the declared interval on any other,
   and the strictest of them when the search moves several.

An engine that stops on its evaluation budget, or on the spread of its own
population, declares neither and leaves them ``None``. A precision handed to it
is then refused with a message naming what does bound it, rather than accepted
and dropped: a run reporting that it honored a request it never read is worse
than a run refusing the request.

The budget is the same kind of statement. :toml:`calibration.max_trials` is the one
number that bounds a search, and no engine option counts evaluations of its own:
an engine that sizes its plan on the budget (an initial design, a restart
schedule) declares ``takes_max_trials=True`` and receives it as its
``max_trials`` constructor argument, ``"auto"`` resolved. An option that counts
something else, such as the length of a chain, keeps its own name.

Everything a stopping rule needs beyond that precision stays in
``method_options``, in the engine's own units, which is how a published call is
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
   search space. Only ``scipy_nelder_mead`` and ``cma_es`` do, and they are
   exactly the engines a new seed cannot move: the simplex is built around
   ``search_space_center(space)`` and would otherwise return the same answer
   every time. Accept the keyword and begin there instead of at your own default.

The first restart is left with the engine's own start and the file's own seed, so
it is the single search it replaces: the answer a file already published stays in
the set and the others are added around it. The remaining starts are drawn from the
declared sampling with a seeded generator, so a rerun draws the same set.

The constraint the method obeys is stated by the project: a calibration always
reports one manipulable value, and an interval sits beside it, never in its place.
So the best restart IS the answer, unchanged in kind from a single search, and the
spread is reported next to it, with a parameter whose optima span more than a
factor ten flagged as not identified by that calibration.

The linearized width beside it
------------------------------

``method = "linearized"`` reads derivatives around the answer instead of searching
again: one model run per parameter, and it is the only declared method that also
says which parameters trade off against which. Two parameters correlated at 0.99
were not identified separately, whatever their individual widths look like, and a
spread of optima cannot tell you that.

It asks nothing of an engine. What it needs is the simulated value *at each
observation*, and it reads that through ``build_paired_vector_capture``, a second
reader over the same two public steps the scoring path uses,
``extract_outputs`` and ``pair_outputs_with_observations``. The metric function's
return stays ``(float, dict[str, float])``: nothing widened to make room for a
vector.

Three refusals carry the method's honesty, and a new one should follow the same
rule of saying which:

- an output that names no station: there are no residuals, refused in the
  preflight before the search runs;
- fewer observations than parameters: no degrees of freedom, so no residual
  variance to give the covariance its scale;
- a singular ``J'J``: the data cannot separate the parameters, so the value is
  reported and no width is.

The first-order caveat is stated rather than buried. The covariance is exact where
the model is linear about the optimum and approximate in proportion to the
curvature, and it is not a posterior: it carries no prior. The unit test holds it
against the closed form on a linear model, which is the only place the two must
agree exactly.

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

Search-space coordinates
------------------------

The engine asks the optimizer in the **search space** declared by
``[calibration.parameters.*].search_space`` (``identity``, ``log``,
``logit``). Samples are converted back to physical units before
injection. Implementations should sample uniformly in
``[0, 1]^n`` or in the configured sampling distribution; the engine
takes care of the inverse mapping.

Distribution-valued methods
---------------------------

Methods that keep a chain of visited states (``da_mh_gp``, ``gp_mapping``)
expose the samples through the ``calibration_trial_distribution`` figure, a histogram
of the trials the search ran, not a posterior. Make sure
your adapter writes the per-iteration trace through ``tell`` so the
post-loop figure registry can plot it.

Add a new figure if your method has unusual diagnostics; see
:doc:`add-a-figure`.

Tests to add
------------

- **Unit** under ``tests/unit/calibration/`` for
  ``__init__`` (option parsing), ``ask`` (point generation),
  ``tell`` (state update), ``best`` (post-loop selection).
- **Synthetic benchmark** under
  ``validation_cases/calibration/`` reusing
  ``recession_hillslope_aquifer`` or ``unconfined_interface_1d``: assert the method
  recovers the truth within a method-specific
  ``METHOD_ABS_TOL`` tolerance.
- **Integration** under ``tests/integration/`` for a
  short ``hmp run`` calibration on a tiny case.

Pitfalls flagged by the layer matrix
------------------------------------

- ``calibration`` imports only the layers that ``layer_matrix.yaml`` grants it,
  and inside the package a part imports only what its row of
  ``calibration_layout.yaml`` allows (``optim`` may import ``criteria`` and
  nothing else). Do not add an edge into ``display`` or ``project`` from an
  adapter. :doc:`fix-an-architecture-gate` says what to do when the gate
  refuses an import.
- Adapters keep their ask/tell state in the adapter instance and never write it
  to disk. The engine owns persistence and resume: the session journal and the
  ``calibration_iterations`` table (``calibration/persistence.py``).
- Methods that read from ``simulation/results/`` must do it through
  the engine API, not by reaching into the Run store directly.

See also
--------

- :doc:`../packages/calibration` for the calibration package map.
- :doc:`/contribute/architecture/calibration/calibration-guide` for the full
  operational reference (TOML, optimizer catalog, storage rules,
  pitfalls, Python API).
