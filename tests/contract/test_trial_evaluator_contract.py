"""Conformance suite for the trial-evaluator port, run against every evaluator.

The port is worth its name only if independent implementations answer the same
way, so every assertion here takes the ``evaluator_id`` fixture, and that fixture
is parametrized over what
:mod:`hydromodpy.calibration.evaluation.registry` resolves rather than over a
list this file keeps. An evaluator installed beside this build is therefore run
by this suite without a line of ``tests/`` naming it, which is the only way a
third party can find out whether its evaluator is usable: ``register()``
certifies a class on the members it **declares**, and the real contract of this
port is behavioural -- what comes back from a call, and what does not come out of
it as an exception.

Two layers, and they do not answer the same question.

**Layer A** is read off the class and applies to every evaluator this
installation serves, the pipeline included. It covers what the registry cannot
see even though it holds the class: that the id a class declares is the id it
was resolved under, that ``needs_prepared_model`` is a real boolean rather than
something truthy, that ``evaluate`` can be called with one request, and that
every constructor parameter without a default is one the production path
actually binds -- an evaluator asking for an option nothing supplies is
unbuildable at the first calibration that names it, and nothing else in the tree
says so.

**Layer B** runs the thing. It can only run an evaluator that declares it needs
no prepared model: making ``hydromodpy_pipeline`` answer means a DEM, a mesh and
a solver, which is the e2e tier and not a contract suite. That is why this
repository ships ``analytic_bowl`` -- without an in-tree model-free evaluator
this layer would collect nothing and be green having proved nothing, which is the
hollow green this campaign has already paid for twice.

What layer B asserts is the port's own text, nothing added:

- an evaluator is built with the ``space`` the search runs over, so it can score
  a sample drawn from that space -- one that cannot score anything it is handed
  is one no search can use, and a suite that called that conformant would be
  saying nothing;
- an outcome is a real :class:`TrialOutcome` whose status is one of the three the
  port names, whose cost is finite when the trial completed and ``nan`` when it
  did not, and which says why when it did not;
- the same sample costs the same twice, because the trial cache answers a
  repeated sample from its record instead of calling the evaluator again --
  ``CalibrationEngine._evaluate_with_cache`` keys on the values alone, so an
  evaluator that answers differently makes a search read its own cache as truth;
- a sample it cannot score comes back as a failed outcome and not as an
  exception, because an exception stops the search on a region of the space
  rather than walking out of it.
"""

from __future__ import annotations

import ast
import inspect
import math
from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest, TrialStatus
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.core.exceptions import CalibrationError

REPO_ROOT = Path(__file__).resolve().parents[2]
"""Anchored on this file. A tree scan that reads the cwd scans nothing from tests/."""

LEGAL_STATUSES = frozenset(TrialStatus.__args__)
"""Read off the port's own Literal, so a fourth status is refused here by itself."""


# --------------------------------------------------------------------------- #
# The evaluators under test, and the space they are searched over
# --------------------------------------------------------------------------- #


@pytest.fixture(params=evaluation_registry.list_evaluator_ids())
def evaluator_id(request) -> str:
    """One evaluator id, once per implementation this installation serves."""
    return request.param


@pytest.fixture
def evaluator_class(evaluator_id: str) -> type:
    """The class the registry answers with, or a skip when this build cannot load it.

    An id declared by this build that fails to import is a broken environment,
    not a broken evaluator, and it is the only skip this suite allows itself. An
    installed plugin that fails is not skipped: ``load_plugins`` already dropped
    the ones that cannot load, so an id that survived to here and then fails is a
    defect in the evaluator and the suite is what has to say so.
    """
    try:
        return evaluation_registry.get(evaluator_id)
    except CalibrationError:
        if evaluator_id in evaluation_registry.builtin_evaluator_ids():
            pytest.skip(f"{evaluator_id!r} is declared by this build and cannot be loaded here")
        raise


def _space() -> ParameterSpace:
    """The space every model-free evaluator is built with and searched over.

    Two dimensions and two transforms, because the second is where a naive
    implementation goes wrong: a log-scaled conductivity is positioned on its
    interval geometrically, and one that reads it arithmetically puts the middle
    of ``[1e-6, 1e-2]`` at ``5e-3`` instead of ``1e-4``.
    """
    return ParameterSpace(
        [
            CalibParameter(
                name="k",
                lower=1e-6,
                upper=1e-2,
                transform="log",
                path="flow.properties.k_aquifer",
            ),
            CalibParameter(
                name="porosity",
                lower=0.01,
                upper=0.3,
                transform="identity",
                path="flow.properties.porosity",
            ),
        ]
    )


def _midpoint(space: ParameterSpace) -> dict[str, float]:
    """The sample at the middle of every interval, in each parameter's own scale."""
    return {
        parameter.name: parameter.to_physical(
            0.5 * (parameter.lower_transformed + parameter.upper_transformed)
        )
        for parameter in space
    }


def _corner(space: ParameterSpace) -> dict[str, float]:
    """The sample at the low bound of every interval. Legal, and as far out as legal goes."""
    return {parameter.name: parameter.lower for parameter in space}


def _config(**overrides: object) -> CalibrationConfig:
    """The document every evaluator of this suite is built from.

    It declares criteria as well as a space, because an evaluator that scores
    through the document -- the one composing a forward model with the blocks of
    F6 -- has nothing to ask for and nothing to weigh without them. Written in
    the document's own vocabulary and naming no implementation: an output on a
    boundary, compared to a value typed into the file. The evaluators that bring
    their own cost bind ``cfg`` for nothing and are unaffected.
    """
    payload: dict[str, object] = {
        "method": "grid",
        "max_iter": 9,
        "optimizer_kwargs": {"points_per_dim": 3},
        "parameters": {
            "k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2], "transform": "log"},
            "porosity": {"path": "flow.properties.porosity", "bounds": [0.01, 0.3]},
        },
        "outputs": {
            "outlet_flow": {
                "support": "boundary",
                "variable": "discharge",
                "boundary_id": "outlet",
                "time": "last",
                "observed_values": [99.7104200938112],
            }
        },
        "objective_blocks": [{"name": "flow", "metric": "rmse", "uses_outputs": ["outlet_flow"]}],
    }
    payload.update(overrides)
    return CalibrationConfig.model_validate(payload)


@pytest.fixture
def model_free_evaluator(evaluator_id: str, evaluator_class: type, tmp_path):
    """One built evaluator, or a skip when it declares it needs the model.

    Built through :func:`~hydromodpy.calibration.evaluation.registry.create` with
    the options the production path offers, and not by calling the class: what is
    under test includes whether the registry can build it at all.

    ``evaluator_class`` is requested for its skip and not for its value: a
    built-in this environment cannot import has to leave here as a skip rather
    than as the ``CalibrationError`` the next line would raise.
    """
    if evaluation_registry.needs_prepared_model(evaluator_id):
        pytest.skip(
            f"{evaluator_id!r} declares it needs a prepared model, so running it means a DEM, "
            "a mesh and a solver. That is the e2e tier; this layer runs what answers without one."
        )
    return evaluation_registry.create(
        evaluator_id,
        cfg=_config(evaluator=evaluator_id),
        trial_ctx=None,
        space=_space(),
        workspace=tmp_path,
        cfg_path=None,
        metric_fn=None,
    )


def _assert_well_formed(outcome: object, *, context: str) -> TrialOutcome:
    """Every rule the port states about one outcome, checked on one outcome."""
    assert isinstance(outcome, TrialOutcome), (
        f"{context}: {type(outcome).__name__} is not an outcome"
    )
    assert outcome.status in LEGAL_STATUSES, f"{context}: status {outcome.status!r}"
    assert isinstance(outcome.cost, float), f"{context}: cost {outcome.cost!r} is not a float"
    assert isinstance(outcome.duration_s, float) and outcome.duration_s >= 0.0, (
        f"{context}: duration_s {outcome.duration_s!r}"
    )
    for name, value in outcome.components.items():
        assert isinstance(name, str), f"{context}: component key {name!r}"
        assert isinstance(value, float), f"{context}: component {name} is {value!r}"
    if outcome.status == "completed":
        assert math.isfinite(outcome.cost), f"{context}: a completed trial costs {outcome.cost!r}"
    else:
        # The rule that matters most: a failed trial carrying a large finite
        # number wins a search whose other trials were worse.
        assert math.isnan(outcome.cost), (
            f"{context}: a {outcome.status} trial carries {outcome.cost!r} instead of nan"
        )
        assert outcome.error, f"{context}: a {outcome.status} trial says nothing about why"
    return outcome


# --------------------------------------------------------------------------- #
# Layer A -- what is read off the class, for every evaluator
# --------------------------------------------------------------------------- #


class TestWhatTheClassDeclares:
    def test_the_id_it_declares_is_the_id_it_was_resolved_under(
        self, evaluator_id: str, evaluator_class: type
    ) -> None:
        """A key and a declaration that disagree make a session record a lie.

        Not a tautology: an id resolves through a declaration in
        ``_BUILTIN_PATHS`` or an entry-point name, and either can point at a class
        that calls itself something else. ``resolve_id`` is what stamps a session
        and keys a cache, so the two spellings would describe different things.
        """
        declared = getattr(evaluator_class, "evaluator_id", None)

        assert isinstance(declared, str) and declared.strip(), (
            f"{evaluator_class!r} declares evaluator_id={declared!r}"
        )
        assert declared == evaluator_id
        assert evaluation_registry.resolve_id(evaluator_id) == evaluator_id

    def test_whether_it_needs_the_model_is_a_boolean_and_not_something_truthy(
        self, evaluator_id: str, evaluator_class: type
    ) -> None:
        """The answer decides whether minutes of setup are paid for; ``"no"`` is true."""
        assert type(evaluator_class.needs_prepared_model) is bool
        assert evaluation_registry.needs_prepared_model(evaluator_id) is (
            evaluator_class.needs_prepared_model
        )

    def test_the_loop_can_call_evaluate_with_one_request(self, evaluator_class: type) -> None:
        """``register`` only checks the member is not ``None``; a string passes that."""
        evaluate = getattr(evaluator_class, "evaluate", None)

        assert callable(evaluate)
        parameters = list(inspect.signature(evaluate).parameters.values())[1:]
        required = [
            parameter
            for parameter in parameters
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert len(required) == 1, (
            f"evaluate{inspect.signature(evaluate)} cannot be called with one request"
        )

    def test_every_option_it_demands_is_one_the_production_path_supplies(
        self, evaluator_class: type
    ) -> None:
        """An evaluator asking for what nothing binds is unbuildable, and nothing else says so.

        :func:`~hydromodpy.calibration.evaluation.registry.create` binds only the
        parameters a class names, and only from
        :data:`~hydromodpy.calibration.evaluation.registry.CONSTRUCTION_OPTIONS`.
        A parameter outside that vocabulary and without a default is never filled,
        and the evaluator raises ``TypeError`` at the first calibration naming it
        -- after the document was read and the session was opened.
        """
        parameters = inspect.signature(evaluator_class).parameters
        unfillable = sorted(
            name
            for name, parameter in parameters.items()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            and name not in evaluation_registry.CONSTRUCTION_OPTIONS
        )

        assert unfillable == [], (
            f"{evaluator_class.__qualname__} requires {unfillable}, and the production path "
            f"offers {list(evaluation_registry.CONSTRUCTION_OPTIONS)}"
        )

    def test_no_constructor_parameter_is_positional_only(self, evaluator_class: type) -> None:
        """An evaluator is built from named options, so a positional slot is unreachable."""
        positional_only = sorted(
            name
            for name, parameter in inspect.signature(evaluator_class).parameters.items()
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
            and parameter.default is inspect.Parameter.empty
        )

        assert positional_only == []


# --------------------------------------------------------------------------- #
# Layer B -- what only running reveals, for an evaluator that needs no model
# --------------------------------------------------------------------------- #


class TestWhatOnlyRunningReveals:
    def test_it_scores_a_sample_from_the_space_it_was_built_with(
        self, model_free_evaluator
    ) -> None:
        """Built with the space, so there is no excuse for not knowing the names.

        An evaluator that fails every sample of its own space is one no search can
        use, and a suite that accepted it would be green on an evaluator that can
        never produce a best candidate.
        """
        outcome = _assert_well_formed(
            model_free_evaluator.evaluate(TrialRequest(trial_id=1, values=_midpoint(_space()))),
            context="midpoint of the space",
        )

        assert outcome.status == "completed"

    def test_the_bounds_of_the_space_are_inside_what_it_can_score(
        self, model_free_evaluator
    ) -> None:
        """An optimizer proposes the corners, so the corners have to be scorable."""
        outcome = _assert_well_formed(
            model_free_evaluator.evaluate(TrialRequest(trial_id=2, values=_corner(_space()))),
            context="low corner of the space",
        )

        assert outcome.status == "completed"

    def test_the_same_sample_costs_the_same_twice(self, model_free_evaluator) -> None:
        """The trial cache keys on the values alone and never calls twice.

        ``CalibrationEngine._evaluate_with_cache`` answers a repeated sample from
        its record, so an evaluator whose answer moves makes a search read a stale
        number as the truth about the sample it just asked for. The trial id
        differs here on purpose: it is not part of the key.
        """
        values = _midpoint(_space())

        first = model_free_evaluator.evaluate(TrialRequest(trial_id=3, values=values))
        second = model_free_evaluator.evaluate(TrialRequest(trial_id=4, values=dict(values)))

        assert first.status == second.status
        assert first.cost == second.cost

    def test_an_empty_sample_is_answered_and_not_refused(self, model_free_evaluator) -> None:
        """A document declaring no parameter makes every optimizer ask with ``{}``.

        The port states it, because refusing it turns a degenerate calibration
        that used to run one unmodified trial into a crash.
        """
        _assert_well_formed(
            model_free_evaluator.evaluate(TrialRequest(trial_id=5, values={})),
            context="empty sample",
        )

    def test_a_sample_it_cannot_score_comes_back_and_is_not_raised(
        self, model_free_evaluator
    ) -> None:
        """An exception stops the search on a region instead of walking out of it.

        Two samples no evaluator can honestly score: a value that is not a number,
        and a name the space it was built with does not declare. Either one may
        come back ``failed`` or ``crashed``; neither may come back as a traceback,
        and neither may come back with a finite cost -- which ``_assert_well_formed``
        is what checks.
        """
        space = _space()

        not_a_number = dict.fromkeys(space.names, math.nan)
        _assert_well_formed(
            model_free_evaluator.evaluate(TrialRequest(trial_id=6, values=not_a_number)),
            context="a sample of nan",
        )

        stranger = dict(_midpoint(space))
        stranger["a_name_the_space_never_declared"] = 1.0
        _assert_well_formed(
            model_free_evaluator.evaluate(TrialRequest(trial_id=7, values=stranger)),
            context="a name the space never declared",
        )


class TestAWholeSearchRunsOnIt:
    def test_the_production_path_reports_a_best_the_evaluator_agrees_with(
        self, evaluator_id: str, model_free_evaluator, tmp_path
    ) -> None:
        """The loop, the persistence and the report, over an evaluator this file does not name.

        The assertion is the round trip: the best parameters the report names,
        handed back to the evaluator, cost what the report says they cost. It
        fails for an evaluator whose outcome the loop cannot consume, for one that
        is not deterministic, and for a report that loses the candidate it scored
        -- and it needs no knowledge of what the evaluator computes.
        """
        from hydromodpy.calibration.runners.cli_runner import run_calibration_core

        report = run_calibration_core(
            _config(evaluator=evaluator_id),
            None,
            workspace=tmp_path,
            space=_space(),
        ).to_dict()

        assert report["n_iterations"] == 9
        best_values = {name: float(value) for name, value in report["best_parameters"].items()}
        replayed = model_free_evaluator.evaluate(TrialRequest(trial_id=99, values=best_values))

        assert replayed.status == "completed"
        assert replayed.cost == pytest.approx(float(report["best_objective"]), rel=1e-12, abs=1e-15)

    def test_no_trial_of_that_search_broke_the_shape_of_an_outcome(
        self, model_free_evaluator
    ) -> None:
        """Every sample a real optimizer proposes, not only the ones this file writes.

        The grid is the same one the search above walks, rebuilt here rather than
        collected from it: the loop hands the evaluator only what the space
        produces, so walking the space is walking what the loop asks.
        """
        space = _space()
        corners_and_middles = [
            {
                name: parameter.to_physical(
                    parameter.lower_transformed
                    + fraction * (parameter.upper_transformed - parameter.lower_transformed)
                )
                for name, parameter in ((p.name, p) for p in space)
            }
            for fraction in (0.0, 0.5, 1.0)
        ]

        for index, values in enumerate(corners_and_middles):
            outcome = _assert_well_formed(
                model_free_evaluator.evaluate(TrialRequest(trial_id=100 + index, values=values)),
                context=f"grid node {index}",
            )
            assert outcome.status == "completed", f"grid node {index} of its own space failed"


# --------------------------------------------------------------------------- #
# The vocabulary the suite holds an evaluator to is the one the runner speaks
# --------------------------------------------------------------------------- #


def test_this_installation_serves_an_evaluator_that_answers_without_a_model() -> None:
    """Anti-vacuity, and the reason ``analytic_bowl`` is shipped rather than mocked.

    Every node of layer B skips an evaluator that needs a prepared model, so with
    none but the pipeline installed the layer would collect its nodes, skip all of
    them, and report green having exercised nothing. The suite says so itself
    rather than leaving it to whoever reads the skip count.
    """
    model_free = [
        candidate
        for candidate in evaluation_registry.list_evaluator_ids()
        if not evaluation_registry.needs_prepared_model(candidate)
    ]

    assert model_free, (
        "every evaluator this installation serves needs a prepared model, so the layer that "
        "runs one exercised nothing"
    )


def test_the_runner_binds_exactly_the_options_the_registry_publishes() -> None:
    """One vocabulary, read from the call rather than kept in step by hand.

    Layer A refuses an evaluator whose constructor demands something outside
    :data:`CONSTRUCTION_OPTIONS`. That refusal is only true while the runner
    passes exactly those, so the tuple is compared with the call itself.
    """
    source = (REPO_ROOT / "hydromodpy/calibration/runners/cli_runner.py").read_text(
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
        and node.func.value.id == "evaluation_registry"
    ]

    assert len(calls) == 1, f"{len(calls)} evaluator constructions in the runner, expected one"
    bound = sorted(keyword.arg for keyword in calls[0].keywords if keyword.arg is not None)
    assert bound == sorted(evaluation_registry.CONSTRUCTION_OPTIONS)
