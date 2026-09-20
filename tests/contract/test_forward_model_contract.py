"""Conformance suite for the forward-model port, run against every model installed.

The port is worth its name only if independent implementations answer the same
way, so every assertion here takes the ``model_id`` fixture, and that fixture is
parametrized over what
:mod:`hydromodpy.calibration.evaluation.forward_registry` resolves rather than
over a list this file keeps. A model installed beside this build is therefore
run by this suite without a line of ``tests/`` naming it, which is how a third
party finds out whether its model is usable: ``register()`` certifies a class on
the members it **declares**, and the real contract is behavioural -- what comes
back from a call, and what comes out of it as an exception instead.

Two layers, and they do not answer the same question.

**Layer A** is read off the class: that the id a class declares is the id it was
resolved under, that ``simulate`` can be called with one request, and that every
constructor parameter without a default is one
:data:`~hydromodpy.calibration.evaluation.forward_registry.CONSTRUCTION_OPTIONS`
supplies -- a model demanding an option nothing binds is unbuildable at the
first calibration naming it, and nothing else in the tree says so.

**Layer B** runs the thing, and it runs it on the one sample every model owes an
answer to: the empty one. A document may declare no parameter, every optimizer
then asks with ``{}``, and the port states that what a sample does not name is
the model's own reference value. That is also the only sample this suite can
hand *any* model: parameter names belong to the model, not to the port, and a
suite imposing ``k`` and ``porosity`` would be a suite refusing every model that
does not use those two words. What a search over a real space proves is proved
where the space comes from the document -- ``tests/contract/test_a_document_
scores_a_forward_model.py`` in tree, and the installed-wheel proof beside it.

What layer B asserts is the port's own text:

- a model answers every id it was asked for, under the key it was asked under,
  and answers nothing else -- the helper the scoring evaluator uses in
  production is what checks it here, so the suite and the route cannot drift;
- the same sample answers the same twice, because the trial cache answers a
  repeated sample from its record instead of calling the model again;
- a parameter it cannot place is refused rather than ignored: a model that
  quietly drops a name turns the knob the document declared into no knob at all,
  and the search reports a best that means nothing;
- a variable it does not serve is refused rather than invented.

Refusal is a raised exception on this port and not a returned outcome, unlike
the evaluator one: the evaluator composing a model with the document's criteria
is what turns a refusal into a failed trial carrying ``nan``.
"""

from __future__ import annotations

import ast
import inspect
import math
import os
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.calibration.evaluation import forward_registry
from hydromodpy.calibration.evaluation.forward import (
    ForwardOutcome,
    ForwardRequest,
    refuse_answers_nobody_asked_for,
)
from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.exceptions import CalibrationError

REPO_ROOT = Path(__file__).resolve().parents[2]
"""Anchored on this file. A tree scan that reads the cwd scans nothing from tests/."""

PROBE_BATCH: tuple[ObservableRequest, ...] = (
    ObservableRequest(id="outlet_flow", name="discharge", support="boundary", key="outlet"),
)
"""What every model of this suite is asked for.

One output, in the vocabulary a document writes and a solver adapter already
speaks: a discharge at a named boundary. It is a convention of the suite and not
of the port, stated here the way the evaluator suite states its search space --
a model that serves nothing at an outlet is outside what this repository knows
how to score from a document.
"""


@pytest.fixture(params=forward_registry.list_model_ids())
def model_id(request) -> str:
    """One model id, once per implementation this installation serves."""
    return request.param


@pytest.fixture
def model_class(model_id: str) -> type:
    """The class the registry answers with, or a skip when this build cannot load it.

    An id declared by this build that fails to import is a broken environment,
    not a broken model, and it is the only skip this suite allows itself. An
    installed plugin that fails is not skipped: ``load_plugins`` already dropped
    the ones that cannot load, so an id that survived to here and then fails is a
    defect in the model and the suite is what has to say so.
    """
    try:
        return forward_registry.get(model_id)
    except CalibrationError:
        if model_id in forward_registry.builtin_model_ids():
            pytest.skip(f"{model_id!r} is declared by this build and cannot be loaded here")
        raise


@pytest.fixture
def model(model_id: str, model_class: type, tmp_path):
    """One built model, through the registry and not by calling the class.

    What is under test includes whether the production route can build it at
    all: ``create`` binds only the options a constructor names, out of the four
    the scoring evaluator offers.

    ``model_class`` is requested for its skip and not for its value.
    """
    return forward_registry.create(
        model_id,
        cfg=None,
        cfg_path=None,
        space=None,
        workspace=tmp_path,
    )


def _answer(model, values: dict[str, float], *, trial_id: int = 1) -> ForwardOutcome:
    """Ask one model for the probe batch, and hold the answer to its shape."""
    outcome = model.simulate(
        ForwardRequest(trial_id=trial_id, values=values, observables=PROBE_BATCH)
    )
    assert isinstance(outcome, ForwardOutcome), f"{type(outcome).__name__} is not an outcome"
    return outcome


ACCIDENTAL: tuple[type[BaseException], ...] = (KeyError, AttributeError, IndexError, NameError)
"""What an unguarded lookup raises when a guard is deleted rather than kept.

The distinction is the whole value of the two refusal nodes below. A model whose
check is removed still raises -- ``VARIABLES[name]`` two lines later raises
``KeyError`` -- so a node accepting any exception stays green while the rule it
claims to enforce is gone. Measured on this repository's own model: deleting its
placement guard leaves every node of this file passing.
"""


@contextmanager
def _refuses(names: str):
    """Assert the block refuses deliberately, and says what it refused.

    ``names`` is the token a refusal has to carry -- the output id or the
    variable asked for. The port says a refusal says which name was not
    understood, which is what separates it from a lookup that happened to fail.
    """
    with pytest.raises(Exception) as caught:  # noqa: B017 - the port says raise, not which class
        yield
    exception = caught.value
    assert not isinstance(exception, ACCIDENTAL), (
        f"{type(exception).__name__}: {exception} is what an unguarded lookup raises, not a "
        "refusal. A model that only fails by accident has no rule left to state."
    )
    assert names in str(exception), (
        f"the refusal does not name {names!r}: {type(exception).__name__}: {exception}"
    )


# --------------------------------------------------------------------------- #
# Layer A -- what is read off the class, for every model
# --------------------------------------------------------------------------- #


class TestWhatTheClassDeclares:
    def test_the_id_it_declares_is_the_id_it_was_resolved_under(
        self, model_id: str, model_class: type
    ) -> None:
        """A key and a declaration that disagree make a session record a lie.

        Not a tautology: an id resolves through a declaration in
        ``_BUILTIN_PATHS`` or an entry-point name, and either can point at a
        class that calls itself something else. ``resolve_id`` is what the
        scoring evaluator reports as ``forward_model_id`` and what a session
        stores, so the two spellings would describe different runs.
        """
        declared = getattr(model_class, "model_id", None)

        assert isinstance(declared, str) and declared.strip(), (
            f"{model_class!r} declares model_id={declared!r}"
        )
        assert declared == model_id
        assert forward_registry.resolve_id(model_id) == model_id

    def test_the_evaluator_can_call_simulate_with_one_request(self, model_class: type) -> None:
        """``register`` only checks the member is not ``None``; a string passes that."""
        simulate = getattr(model_class, "simulate", None)

        assert callable(simulate)
        parameters = list(inspect.signature(simulate).parameters.values())[1:]
        required = [
            parameter
            for parameter in parameters
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert len(required) == 1, (
            f"simulate{inspect.signature(simulate)} cannot be called with one request"
        )

    def test_every_option_it_demands_is_one_the_route_supplies(self, model_class: type) -> None:
        """A model asking for what nothing binds is unbuildable, and nothing else says so.

        ``create`` binds only the parameters a class names, and only from
        :data:`CONSTRUCTION_OPTIONS`. A required parameter outside that
        vocabulary is never filled, and the first calibration naming the model
        fails after the document was read and the session was opened.
        """
        parameters = inspect.signature(model_class).parameters
        unfillable = sorted(
            name
            for name, parameter in parameters.items()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            and name not in forward_registry.CONSTRUCTION_OPTIONS
        )

        assert unfillable == [], (
            f"{model_class.__qualname__} requires {unfillable}, and the route offers "
            f"{list(forward_registry.CONSTRUCTION_OPTIONS)}"
        )

    def test_no_constructor_parameter_is_positional_only(self, model_class: type) -> None:
        """A model is built from named options, so a positional slot is unreachable."""
        positional_only = sorted(
            name
            for name, parameter in inspect.signature(model_class).parameters.items()
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
            and parameter.default is inspect.Parameter.empty
        )

        assert positional_only == []


# --------------------------------------------------------------------------- #
# Layer B -- what only running reveals
# --------------------------------------------------------------------------- #


class TestWhatOnlyRunningReveals:
    def test_it_answers_the_batch_for_a_sample_that_names_nothing(self, model) -> None:
        """A document declaring no parameter makes every optimizer ask with ``{}``.

        The answer is held to what the scorer will read: one result per id, a
        one-dimensional run of finite floats, and at least one value -- an empty
        series pairs with no record and fails every trial of a search.
        """
        outcome = _answer(model, {})

        assert set(outcome.observables) == {request.id for request in PROBE_BATCH}
        for request in PROBE_BATCH:
            result = outcome.observables[request.id]
            assert isinstance(result, ObservableResult), (
                f"{request.id!r} is a {type(result).__name__}"
            )
            values = np.asarray(result.values, dtype=float)
            assert values.ndim == 1, f"{request.id!r} answered a {values.ndim}-d array"
            assert values.size >= 1, f"{request.id!r} answered nothing to score"
            assert np.all(np.isfinite(values)), f"{request.id!r} answered a non-finite value"

    def test_its_answer_is_keyed_the_way_the_route_requires(self, model, model_id: str) -> None:
        """The production helper, on the production answer.

        Checked with what :class:`ScoredForwardEvaluator` calls rather than with
        assertions written again here, so a rule added to the route is a rule
        this suite starts enforcing on every installed model.
        """
        outcome = _answer(model, {})

        refuse_answers_nobody_asked_for(
            [request.id for request in PROBE_BATCH],
            outcome.observables,
            model_id=model_id,
        )

    def test_its_diagnostics_travel_as_named_numbers(self, model) -> None:
        """They are merged into the trial components beside the cost, under their own names.

        A model reporting none is conformant, so what is held here is the shape
        of the mapping rather than its size: the scoring evaluator prefixes and
        merges whatever is in it, and a key that is not a name or a value that is
        not a number reaches the trial components as one.
        """
        outcome = _answer(model, {})

        assert isinstance(outcome.diagnostics, Mapping), (
            f"diagnostics is a {type(outcome.diagnostics).__name__}"
        )
        for name, value in outcome.diagnostics.items():
            assert isinstance(name, str) and name.strip(), f"diagnostic key {name!r}"
            assert isinstance(value, float | int) and math.isfinite(float(value)), (
                f"diagnostic {name} is {value!r}"
            )

    def test_the_same_sample_answers_the_same_twice(self, model) -> None:
        """The trial cache keys on the values alone and never calls twice.

        ``CalibrationEngine._evaluate_with_cache`` answers a repeated sample from
        its record, so a model whose answer moves makes a search read a stale
        number as the truth about the sample it just asked for. The trial id
        differs here on purpose: it is not part of the key.
        """
        first = _answer(model, {}, trial_id=2)
        second = _answer(model, {}, trial_id=3)

        for request in PROBE_BATCH:
            np.testing.assert_array_equal(
                np.asarray(first.observables[request.id].values, dtype=float),
                np.asarray(second.observables[request.id].values, dtype=float),
            )

    def test_a_parameter_it_cannot_place_is_refused_and_not_ignored(self, model) -> None:
        """A dropped name turns a declared knob into no knob at all.

        The search would then walk a space whose dimensions change nothing, every
        trial would cost the same, and the report would name a best that is the
        first point visited. Refusing is what lets the evaluator fail the trial
        and say which name was not understood.
        """
        stranger = "a_name_no_model_of_this_suite_declares"

        with _refuses(stranger):
            _answer(model, {stranger: 1.0}, trial_id=4)

    def test_a_variable_it_does_not_serve_is_refused_and_not_invented(self, model) -> None:
        """An answer under a variable the model has no equation for would be scored anyway."""
        unserved = "a_variable_no_model_of_this_suite_serves"
        stranger = ObservableRequest(
            id="outlet_flow", name=unserved, support="boundary", key="outlet"
        )

        with _refuses(unserved):
            model.simulate(ForwardRequest(trial_id=5, values={}, observables=(stranger,)))


# --------------------------------------------------------------------------- #
# The vocabulary the suite holds a model to is the one the route speaks
# --------------------------------------------------------------------------- #


def test_this_installation_serves_a_forward_model() -> None:
    """Anti-vacuity, and it has two halves because the suite is run in two places.

    Beside this checkout the registry always answers ``linear_reservoir``, so the
    first assertion is cheap and only guards a build that lost its own model.

    The second is the one that matters. This file is also run inside the isolated
    environment of the installed-wheel proof, where ``HMP_WHEEL_SITE`` is set and
    the whole point is that a model nothing in the tree names was discovered
    through its entry point. A suite parametrized by a registry stays green when
    no plugin arrives -- it simply collects fewer nodes -- so there the absence of
    a non-built-in id is a failed proof and not a smaller run.
    """
    served = forward_registry.list_model_ids()

    assert served, (
        "this installation resolves no forward model, so every layer of this suite "
        "collected nothing and proved nothing"
    )
    if os.environ.get("HMP_WHEEL_SITE"):
        installed = sorted(set(served) - set(forward_registry.builtin_model_ids()))
        assert installed, (
            f"this run is the installed-wheel proof and the registry serves only {served}: "
            "no model arrived through the entry-point group, so every node ran on what this "
            "build ships and proved nothing about substitution"
        )


def test_the_scoring_evaluator_binds_exactly_the_options_the_registry_publishes() -> None:
    """One vocabulary, read from the call rather than kept in step by hand.

    Layer A refuses a model whose constructor demands something outside
    :data:`CONSTRUCTION_OPTIONS`. That refusal is only true while the evaluator
    passes exactly those, so the tuple is compared with the call itself.
    """
    source = (REPO_ROOT / "hydromodpy/calibration/evaluation/scored_forward.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "forward_registry"
    ]

    assert len(calls) == 1, f"{len(calls)} model constructions in the evaluator, expected one"
    bound = sorted(keyword.arg for keyword in calls[0].keywords if keyword.arg is not None)
    assert bound == sorted(forward_registry.CONSTRUCTION_OPTIONS)
