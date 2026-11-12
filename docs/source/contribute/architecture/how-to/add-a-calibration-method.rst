Add a calibration method
========================

Calibration runs an ask/tell loop. An optimizer proposes a parameter point, the engine
evaluates it, and the optimizer ingests the result. The methods that ship are listed in
:doc:`/reference/calibration-methods`. Each one is an adapter under
``hydromodpy/calibration/optim/adapters/``. :doc:`../engines/calibration-internals` describes
the loop around it.

Files to create
---------------

One module for a method called ``mymethod``:
``hydromodpy/calibration/optim/adapters/<method>_adapter.py``.

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
       tolerance: float = 1e-3


   class MyMethodAdapter:
       name: ClassVar[str] = "mymethod"
       options: ClassVar[type[BaseModel] | None] = MyMethodConfig
       traits = EngineTraits(takes_max_trials=True)

       def __init__(self, space: ParameterSpace, *, max_trials: int = 100, tolerance=1e-3):
           self._space, self._max_trials = space, max_trials
           self._seen = 0
           self._best: EvaluationResult | None = None

       def ask(self, n: int = 1) -> list[ParamSuggestion]: ...

       def tell(self, results: list[EvaluationResult]) -> None:
           self._seen += len(results)
           for result in results:
               if self._best is None or result.cost < self._best.cost:
                   self._best = result

       def best(self) -> EvaluationResult | None:
           return self._best

       def converged(self) -> bool:
           return self._seen >= self._max_trials

An optional dependency is imported at module level. A missing package raises an
``ImportError`` that names the extra to install, and the other methods stay available.

Contract
--------

An adapter implements the ``Optimizer`` Protocol. The registry reads the id from the
``name`` attribute, and a class may carry more members than the Protocol lists.

.. literalinclude:: /../../hydromodpy/calibration/optim/optimizer.py
   :pyobject: Optimizer

``ask`` proposes points in the search space of each parameter (``identity``, ``log`` or
``logit``, set in ``[calibration.parameters.*]``). The engine converts them back to
physical units. ``tell`` feeds back the matching batch of results. The session journal
writes each point that ``ask`` returns as a ``proposed`` line, in list order and before any
evaluation, so the order is part of the contract. An adapter that reorders its points
between two calls changes the trial numbers. The adapter keeps its state in its own
instance and never writes it to disk, because the engine owns persistence and resume.

``converged`` says whether the engine met a rule of its own. ``stop_state`` in
``optim/stopping.py`` turns it into the stop state of the session. An engine that declares
no stopping option and spends its whole budget is reported as having spent it, whatever
``converged`` says.

A search of your own needs no registration. Hand an object that satisfies ``Optimizer`` to
``CalibrationEngine(optimizer=...)`` in ``optim/engine.py``.

Declaring the options
---------------------

``options`` is the Pydantic class of the settings the adapter accepts, with one field per
constructor keyword and no ``method`` field. ``method_options_problem`` checks a phase,
``[calibration]`` and the protocol's ``steady_method_options`` and
``transient_method_options`` against it when the file loads. A wrong key or type is refused
there, with the phase named, and ``hmp check`` runs the same check.

Declaring the traits
--------------------

An engine refuses an impossible pairing in its constructor. That is late, because a staged
calibration builds the optimizer of phase two after phase one has spent its budget. The
class attribute ``traits`` states the same facts where a check reads them before anything
solves. Each field says what it means in its own docstring.

.. literalinclude:: /../../hydromodpy/calibration/optim/optimizer.py
   :pyobject: EngineTraits

Two traits decide how the engine meets a precision. :toml:`calibration.precision` is a
relative precision on the parameter, and it is translated into the option that
``precision_option`` names. With ``precision_reads="relative_value"`` the number passes
through, and it needs ``required_search_space="log"``. With ``"search_width"`` it is
converted into the variable the search walks, ``log10(1 + precision)`` decades in log space
and a fraction of the interval otherwise. An engine that stops on its budget declares
neither, and a precision handed to it is refused with a message that names what bounds it.

The budget is one number, :toml:`calibration.max_trials`. An engine that sizes its plan on
it declares ``takes_max_trials=True`` and receives it as the ``max_trials`` argument, with
``"auto"`` resolved. No method option counts evaluations.

``[calibration.uncertainty] method = "multistart"`` repeats the search. An engine whose
repeats cannot differ, such as ``grid`` and ``bisection``, declares
``restarts_explore_differently=False`` and a file that asks for restarts on it is refused
before the first solve. An engine that takes ``start_at`` declares
``accepts_a_start_point=True``, and it begins there instead of at its own default.

Register
--------

There is no dict of methods to edit beyond the path table. An in-tree class is one line in
``_BUILTIN_PATHS`` of ``hydromodpy/calibration/optim/optimizer.py``, under the id its
``name`` declares. A method outside the tree publishes one entry point in the group
``hydromodpy.calibration.optimizer``. :doc:`plug-into-a-port` explains how both ways
resolve a name. The id is the name that ``CalibrationConfig.method`` accepts.

Test
----

- Unit tests under ``tests/unit/calibration/`` for the constructor options, ``ask``,
  ``tell`` and ``best``.
- ``tests/ports/test_optimizer.py`` runs over ``optimizers.names()``, so the new method
  meets the port test with no line added.
- A recovery test on a synthetic case, with a method-specific tolerance, in the style of
  ``METHOD_ABS_TOL`` in ``tests/regression/fast/calibration/test_brutsaert_methods.py``.
  The cases themselves are under ``validation_cases/calibration/``.
- One short ``hmp run`` calibration on a tiny case under ``tests/integration/calibration/``.

The imports the layer matrix allows are in :doc:`../generated/layers`, and
``optim`` may import ``criteria`` and nothing else inside the package.
A method that reads simulation results does it through the engine API, never through the
run store.

See also
--------

- :doc:`../packages/calibration` for the calibration package map.
- :doc:`../engines/calibration-internals` for the loop, the storage rules and the Python API.
- :doc:`add-a-figure` if the method has diagnostics of its own.
