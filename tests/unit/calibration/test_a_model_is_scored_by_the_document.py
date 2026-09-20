"""What a forward model is asked, what it may answer, and what is refused early.

The composed route has two frontiers and this file holds both. Upstream, the
document: a declaration that cannot be placed without a mesh or a project is
refused when the evaluator is built, never at the first trial and never by
quietly dropping what it could not honour. Downstream, the model: an answer that
does not match the batch it answers is a failed trial with a reason, and a model
that raises never reaches the ask/tell loop as an exception.

The end-to-end proof that the document and not the model decides the cost is
``tests/contract/test_a_document_scores_a_forward_model.py``. This file is the
frontier itself, one refusal at a time.
"""

from __future__ import annotations

import math
from importlib.metadata import EntryPoint
from typing import ClassVar

import numpy as np
import pytest
from pydantic import ValidationError

import hydromodpy.calibration.evaluation.forward_registry as forward_registry
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.forward import (
    ForwardModel,
    ForwardOutcome,
    ForwardRequest,
    forward_model_members,
)
from hydromodpy.calibration.evaluation.port import TrialRequest
from hydromodpy.calibration.evaluation.scored_forward import (
    ScoredForwardEvaluator,
    requests_for_outputs,
)
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.exceptions import CalibrationError

pytestmark = pytest.mark.fast


class _Answers:
    """A model that answers every request with one constant value."""

    model_id: ClassVar[str] = "test_constant"

    def __init__(self, *, value: float = 1.0) -> None:
        self.value = value
        self.seen: list[ForwardRequest] = []

    def simulate(self, request: ForwardRequest) -> ForwardOutcome:
        self.seen.append(request)
        return ForwardOutcome(
            observables={
                observable.id: ObservableResult(
                    request_id=observable.id,
                    values=np.asarray([self.value], dtype=float),
                    units="m3/s",
                )
                for observable in request.observables
            },
            diagnostics={"test_constant.calls": float(len(self.seen))},
        )


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch):
    """Give one test its own registry state, restored afterwards.

    The registry is process-global by design -- a name resolves to one class for
    everything in that interpreter -- so a test that registers a plugin has to
    put both mappings and the scan flag back.
    """
    monkeypatch.setattr(forward_registry, "_REGISTRY", dict(forward_registry._REGISTRY))
    monkeypatch.setattr(forward_registry, "_BUILTIN_PATHS", dict(forward_registry._BUILTIN_PATHS))
    monkeypatch.setattr(forward_registry, "_PLUGINS_LOADED", False)
    return forward_registry


def _entry_points_returning(*points: EntryPoint):
    def fake_entry_points(*, group: str):
        assert group == forward_registry.ENTRY_POINT_GROUP
        return tuple(points)

    return fake_entry_points


def _stub_entry_point(name: str, target: object) -> EntryPoint:
    """An entry point that loads *target* without a distribution on disk."""
    point = EntryPoint(
        name=name, value="tests.stub:Model", group=forward_registry.ENTRY_POINT_GROUP
    )
    object.__setattr__(point, "load", lambda: target)
    return point


def _output(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "support": "boundary",
        "variable": "discharge",
        "boundary_id": "outlet",
        "time": "last",
        "observed_values": [2.0],
    }
    payload.update(overrides)
    return payload


def _config(**overrides: object) -> CalibrationConfig:
    """A valid document, with one block per declared output unless one is given.

    A block has to name a declared output, so a test that changes the outputs
    without saying anything about the blocks gets the blocks its outputs imply.
    """
    payload: dict[str, object] = {
        "method": "grid",
        "max_iter": 4,
        "evaluator": "scored_forward_model",
        "parameters": {"k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2]}},
        "outputs": {"outlet_flow": _output()},
    }
    payload.update(overrides)
    if "objective_blocks" not in payload:
        payload["objective_blocks"] = [
            {
                "name": name,
                "metric": "distance_gap"
                if dict(declaration).get("support") == "network"
                else "rmse",
                "uses_outputs": [name],
            }
            for name, declaration in dict(payload["outputs"]).items()  # type: ignore[arg-type]
        ]
    return CalibrationConfig.model_validate(payload)


def _evaluator(model: object, **overrides: object) -> ScoredForwardEvaluator:
    """Build the composed evaluator over *model*, bypassing the registry lookup."""
    evaluator = ScoredForwardEvaluator(cfg=_config(**overrides))
    evaluator._model = model  # noqa: SLF001 - the substitution this test is about
    evaluator._model_id = str(getattr(model, "model_id", "test"))  # noqa: SLF001
    return evaluator


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------


class TestTheRegistryResolves:
    def test_a_document_that_names_none_gets_the_reference_model(self) -> None:
        assert forward_registry.resolve_id(None) == "linear_reservoir"
        assert forward_registry.DEFAULT_FORWARD_MODEL_ID == "linear_reservoir"

    def test_a_name_nobody_serves_says_what_is_served_and_how_to_join(self) -> None:
        with pytest.raises(CalibrationError) as refusal:
            forward_registry.get("a_model_nobody_installed")

        assert "linear_reservoir" in str(refusal.value)
        assert forward_registry.ENTRY_POINT_GROUP in str(refusal.value)

    def test_a_class_missing_a_port_member_cannot_be_registered(self) -> None:
        class _NoSimulate:
            model_id = "test_incomplete"

        with pytest.raises(TypeError) as refusal:
            forward_registry.register(_NoSimulate)

        assert "simulate" in str(refusal.value)
        assert "test_incomplete" in str(refusal.value)

    def test_a_class_without_an_id_cannot_be_registered(self) -> None:
        class _Nameless:
            def simulate(self, request: ForwardRequest) -> ForwardOutcome:
                return ForwardOutcome(observables={})

        with pytest.raises(TypeError):
            forward_registry.register(_Nameless)

    def test_an_id_already_served_is_not_taken_by_accident(self) -> None:
        forward_registry.register(_Answers)
        try:
            with pytest.raises(ValueError, match="already registered"):
                forward_registry.register(_Answers)
        finally:
            forward_registry.unregister(_Answers.model_id)

    def test_only_the_options_a_constructor_names_are_bound(self) -> None:
        forward_registry.register(_Answers, replace=True)
        try:
            built = forward_registry.create(
                _Answers.model_id, cfg=_config(), space=None, workspace=None, cfg_path=None
            )
        finally:
            forward_registry.unregister(_Answers.model_id)

        assert isinstance(built, _Answers)
        assert built.value == 1.0

    def test_what_a_constructor_does_name_arrives(self) -> None:
        """The other half: a class naming two options receives those two, and no more."""

        class _Wants(_Answers):
            model_id: ClassVar[str] = "test_wants"

            def __init__(self, *, cfg: object = None, workspace: object = None) -> None:
                super().__init__()
                self.cfg = cfg
                self.workspace = workspace

        cfg = _config()
        forward_registry.register(_Wants, replace=True)
        try:
            built = forward_registry.create(
                _Wants.model_id, cfg=cfg, space="a space", workspace="a workspace", cfg_path=None
            )
        finally:
            forward_registry.unregister(_Wants.model_id)

        assert built.cfg is cfg
        assert built.workspace == "a workspace"
        assert not hasattr(built, "space")

    def test_a_model_demanding_what_no_option_serves_is_refused_by_name(self) -> None:
        """A required parameter outside the four options, named here and not by TypeError."""

        class _WantsMesh(_Answers):
            model_id: ClassVar[str] = "test_wants_mesh"

            def __init__(self, mesh: object) -> None:
                super().__init__()
                self.mesh = mesh

        forward_registry.register(_WantsMesh, replace=True)
        try:
            with pytest.raises(CalibrationError, match="mesh"):
                forward_registry.create(
                    _WantsMesh.model_id, cfg=_config(), space=None, workspace=None, cfg_path=None
                )
        finally:
            forward_registry.unregister(_WantsMesh.model_id)

    def test_the_members_it_holds_a_class_to_come_from_the_port(self) -> None:
        assert forward_model_members() == ("model_id", "simulate")
        assert isinstance(_Answers(), ForwardModel)


class TestThePluginGroup:
    """The surface a third party joins by, and everything it refuses to serve."""

    def test_a_model_nothing_in_the_tree_names_is_reached_through_the_group(
        self, isolated_registry: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Foreign(_Answers):
            model_id: ClassVar[str] = "acme_reservoir"

        monkeypatch.setattr(
            forward_registry,
            "entry_points",
            _entry_points_returning(_stub_entry_point("acme_reservoir", _Foreign)),
        )

        assert forward_registry.load_plugins() == 1
        assert forward_registry.get("acme_reservoir") is _Foreign
        assert forward_registry.is_registered("acme_reservoir")
        assert "acme_reservoir" in forward_registry.list_model_ids()
        assert "acme_reservoir" not in forward_registry.builtin_model_ids()

    def test_a_plugin_claiming_a_name_this_build_ships_does_not_answer_in_its_place(
        self, isolated_registry: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Impostor(_Answers):
            model_id: ClassVar[str] = "linear_reservoir"

        monkeypatch.setattr(
            forward_registry,
            "entry_points",
            _entry_points_returning(_stub_entry_point("linear_reservoir", _Impostor)),
        )

        assert forward_registry.load_plugins() == 0
        assert forward_registry.get("linear_reservoir") is not _Impostor

    def test_an_entry_point_name_and_a_declared_id_that_disagree_are_refused(
        self, isolated_registry: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The document writes the name and the session records the id: one model, one word."""

        class _Renamed(_Answers):
            model_id: ClassVar[str] = "what_it_calls_itself"

        monkeypatch.setattr(
            forward_registry,
            "entry_points",
            _entry_points_returning(_stub_entry_point("what_the_wheel_declares", _Renamed)),
        )

        assert forward_registry.load_plugins() == 0
        assert not forward_registry.is_registered("what_the_wheel_declares")
        assert not forward_registry.is_registered("what_it_calls_itself")

    def test_an_empty_entry_point_name_is_refused(
        self, isolated_registry: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Nameless(_Answers):
            model_id: ClassVar[str] = ""

        monkeypatch.setattr(
            forward_registry,
            "entry_points",
            _entry_points_returning(_stub_entry_point("  ", _Nameless)),
        )

        assert forward_registry.load_plugins() == 0

    def test_a_wheel_that_will_not_import_does_not_take_its_neighbour_down(
        self, isolated_registry: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Good(_Answers):
            model_id: ClassVar[str] = "acme_good"

        broken = _stub_entry_point("acme_broken", _Good)

        def explode() -> object:
            raise ImportError("no module named acme")

        object.__setattr__(broken, "load", explode)
        monkeypatch.setattr(
            forward_registry,
            "entry_points",
            _entry_points_returning(broken, _stub_entry_point("acme_good", _Good)),
        )

        assert forward_registry.load_plugins() == 1
        assert forward_registry.is_registered("acme_good")

    def test_unreadable_metadata_leaves_the_built_in_resolvable(
        self, isolated_registry: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole scan fails, and a document naming the built-in still runs."""

        def explode(*, group: str) -> tuple[EntryPoint, ...]:
            raise RuntimeError("distribution metadata is unreadable")

        monkeypatch.setattr(forward_registry, "entry_points", explode)

        assert forward_registry.load_plugins() == 0
        assert forward_registry.resolve_id(None) == "linear_reservoir"

    def test_a_plugin_that_does_not_hold_the_port_is_refused(
        self, isolated_registry: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Half:
            model_id: ClassVar[str] = "acme_half"

        monkeypatch.setattr(
            forward_registry,
            "entry_points",
            _entry_points_returning(_stub_entry_point("acme_half", _Half)),
        )

        assert forward_registry.load_plugins() == 0
        assert not forward_registry.is_registered("acme_half")


class TestTheDocumentNamesTheModel:
    def test_a_model_this_installation_cannot_serve_is_refused_while_reading(self) -> None:
        with pytest.raises(ValidationError) as refusal:
            _config(forward_model="a_model_nobody_installed")

        assert "a_model_nobody_installed" in str(refusal.value)
        assert forward_registry.ENTRY_POINT_GROUP in str(refusal.value)

    def test_the_document_reaches_the_registry_through_the_evaluator(self) -> None:
        evaluator = evaluation_registry.create(
            "scored_forward_model",
            cfg=_config(forward_model="linear_reservoir"),
            trial_ctx=None,
            space=None,
            workspace=None,
            cfg_path=None,
            metric_fn=None,
        )

        assert evaluator.forward_model_id == "linear_reservoir"
        assert evaluator.needs_prepared_model is False


# --------------------------------------------------------------------------
# What the document may declare on this route
# --------------------------------------------------------------------------


class TestWhatTheRouteRefuses:
    def test_a_document_without_criteria_has_nothing_to_ask_for(self) -> None:
        with pytest.raises(CalibrationError, match="objective_blocks"):
            ScoredForwardEvaluator(cfg=_config(objective_blocks=[]))

    def test_an_output_naming_a_station_is_refused_by_name(self) -> None:
        with pytest.raises(CalibrationError) as refusal:
            ScoredForwardEvaluator(
                cfg=_config(
                    outputs={"outlet_flow": _output(observes="J7000610", observed_values=None)}
                )
            )

        assert "J7000610" in str(refusal.value)
        assert "observed_values" in str(refusal.value)

    def test_a_stream_network_output_belongs_to_the_pipeline_producer(self) -> None:
        with pytest.raises(CalibrationError, match="stream network"):
            requests_for_outputs(
                _config(
                    outputs={
                        "network": {
                            "support": "network",
                            "observed_network": "data.hydrography",
                        }
                    },
                ).outputs
            )

    def test_a_planar_point_has_no_mesh_to_be_placed_on(self) -> None:
        outputs = _config(
            outputs={
                "piezo": {
                    "support": "point",
                    "variable": "head",
                    "x": 1.0,
                    "y": 2.0,
                    "observed_values": [1.0],
                }
            }
        ).outputs

        with pytest.raises(CalibrationError, match="planar point"):
            requests_for_outputs(outputs)

    def test_a_flat_cell_index_has_no_mesh_to_be_resolved_against(self) -> None:
        outputs = _config(
            outputs={
                "cell": {
                    "support": "cell",
                    "variable": "head",
                    "cell_id": 17,
                    "observed_values": [1.0],
                }
            }
        ).outputs

        with pytest.raises(CalibrationError, match="cell_id"):
            requests_for_outputs(outputs)

    def test_a_window_has_no_date_to_cut_on_and_is_refused_like_the_others(self) -> None:
        """The fifth refusal, and the one that used to leave a generic exit code."""
        with pytest.raises(CalibrationError, match="scoring_window"):
            ScoredForwardEvaluator(
                cfg=_config(scoring_window={"start": "2020-01-01", "end": "2020-12-31"})
            )

    def test_a_record_no_answer_could_ever_match_is_refused_before_the_search(self) -> None:
        """One value is scored and three are declared: every sample fails, so none is run."""
        with pytest.raises(CalibrationError, match="No sample can pair"):
            ScoredForwardEvaluator(
                cfg=_config(
                    outputs={"outlet_flow": _output(time="last", observed_values=[1.0, 2.0, 3.0])}
                )
            )

    def test_an_aggregating_reducer_is_held_to_its_single_value_too(self) -> None:
        with pytest.raises(CalibrationError, match="No sample can pair"):
            ScoredForwardEvaluator(
                cfg=_config(
                    outputs={
                        "outlet_flow": _output(
                            time="all", reducer="mean", observed_values=[1.0, 2.0]
                        )
                    }
                )
            )

    def test_a_series_scored_on_all_of_itself_is_not_refused(self) -> None:
        """The control: a length this route cannot know is left to the trial."""
        evaluator = ScoredForwardEvaluator(
            cfg=_config(
                outputs={
                    "outlet_flow": _output(
                        time="all", reducer="none", observed_values=[1.0, 2.0, 3.0]
                    )
                }
            )
        )

        assert evaluator.forward_model_id == "linear_reservoir"


class TestWhatTheModelIsAsked:
    def test_a_request_carries_the_name_the_document_gave_the_output(self) -> None:
        requests = requests_for_outputs(_config().outputs)

        assert [request.id for request in requests] == ["outlet_flow"]
        assert requests[0].name == "discharge"
        assert requests[0].support == "boundary"
        assert requests[0].key == "outlet"
        assert requests[0].times == "last"

    def test_a_cell_output_is_asked_for_at_its_own_layer_row_and_column(self) -> None:
        outputs = _config(
            outputs={
                "cell_head": {
                    "support": "cell",
                    "variable": "head",
                    "row": 2,
                    "col": 3,
                    "layer": 1,
                    "observed_values": [1.0],
                }
            }
        ).outputs

        (request,) = requests_for_outputs(outputs)

        assert request.cell == (1, 2, 3)

    def test_a_lake_output_is_keyed_on_the_lake_the_document_names(self) -> None:
        outputs = _config(
            outputs={
                "stage": {
                    "support": "lake",
                    "variable": "stage",
                    "lake_id": "cheze",
                    "observed_values": [1.0],
                }
            }
        ).outputs

        (request,) = requests_for_outputs(outputs)

        assert request.support == "lake"
        assert request.key == "cheze"

    def test_every_trial_asks_for_the_same_batch(self) -> None:
        model = _Answers()
        evaluator = _evaluator(model)

        evaluator.evaluate(TrialRequest(trial_id=1, values={"k": 1e-4}))
        evaluator.evaluate(TrialRequest(trial_id=2, values={"k": 1e-3}))

        assert [request.trial_id for request in model.seen] == [1, 2]
        assert model.seen[0].observables == model.seen[1].observables
        assert model.seen[0].wanted_ids() == ("outlet_flow",)


# --------------------------------------------------------------------------
# What the model may answer
# --------------------------------------------------------------------------


class TestWhatTheModelMayAnswer:
    def test_an_answer_is_scored_by_the_block_the_document_declares(self) -> None:
        outcome = _evaluator(_Answers(value=5.0)).evaluate(
            TrialRequest(trial_id=1, values={"k": 1e-4})
        )

        assert outcome.status == "completed"
        # rmse between the single simulated 5.0 and the declared observation 2.0
        assert outcome.cost == pytest.approx(3.0)
        assert outcome.components["diagnostic.test_constant.calls"] == 1.0

    def test_a_missing_output_fails_the_trial_and_names_it(self) -> None:
        class _Silent(_Answers):
            model_id: ClassVar[str] = "test_silent"

            def simulate(self, request: ForwardRequest) -> ForwardOutcome:
                return ForwardOutcome(observables={})

        outcome = _evaluator(_Silent()).evaluate(TrialRequest(trial_id=1, values={}))

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)
        # The guard's own wording and not just the output name: the scorer one
        # layer down also names a missing output, so asserting the name alone
        # stays green when the guard is removed.
        assert "no value for outlet_flow" in (outcome.error or "")

    def test_an_answer_nobody_asked_for_fails_the_trial(self) -> None:
        class _Generous(_Answers):
            model_id: ClassVar[str] = "test_generous"

            def simulate(self, request: ForwardRequest) -> ForwardOutcome:
                answered = dict(super().simulate(request).observables)
                answered["unasked"] = ObservableResult(
                    request_id="unasked", values=np.asarray([1.0]), units="m"
                )
                return ForwardOutcome(observables=answered)

        outcome = _evaluator(_Generous()).evaluate(TrialRequest(trial_id=1, values={}))

        assert outcome.status == "failed"
        assert "unasked" in (outcome.error or "")

    def test_a_result_keyed_under_one_id_and_labelled_another_fails_the_trial(self) -> None:
        class _Mislabelled(_Answers):
            model_id: ClassVar[str] = "test_mislabelled"

            def simulate(self, request: ForwardRequest) -> ForwardOutcome:
                return ForwardOutcome(
                    observables={
                        observable.id: ObservableResult(
                            request_id="something_else",
                            values=np.asarray([1.0]),
                            units="m3/s",
                        )
                        for observable in request.observables
                    }
                )

        outcome = _evaluator(_Mislabelled()).evaluate(TrialRequest(trial_id=1, values={}))

        assert outcome.status == "failed"
        assert "something_else" in (outcome.error or "")

    def test_a_model_that_raises_comes_back_as_a_failed_trial(self) -> None:
        class _Refuses(_Answers):
            model_id: ClassVar[str] = "test_refuses"

            def simulate(self, request: ForwardRequest) -> ForwardOutcome:
                raise RuntimeError("the solve diverged")

        outcome = _evaluator(_Refuses()).evaluate(TrialRequest(trial_id=1, values={}))

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)
        assert "the solve diverged" in (outcome.error or "")

    def test_a_cost_that_is_not_finite_is_not_reported_as_completed(self) -> None:
        outcome = _evaluator(_Answers(value=float("inf"))).evaluate(
            TrialRequest(trial_id=1, values={})
        )

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)


class TestHowAnAnswerIsHeldToTheDocument:
    def test_an_answer_of_the_wrong_length_fails_the_trial_and_names_the_output(self) -> None:
        outcome = _evaluator(
            _Answers(value=5.0),
            outputs={"outlet_flow": _output(time="all", observed_values=[1.0, 2.0])},
        ).evaluate(TrialRequest(trial_id=1, values={}))

        assert outcome.status == "failed"
        assert "outlet_flow" in (outcome.error or "")
        assert "served 1" in (outcome.error or "")

    def test_two_wrong_lengths_adding_up_to_the_right_total_are_not_scored(self) -> None:
        """A block concatenates before it compares, so the total is not the check."""

        class _TwoSeries(_Answers):
            model_id: ClassVar[str] = "test_two_series"

            def simulate(self, request: ForwardRequest) -> ForwardOutcome:
                return ForwardOutcome(
                    observables={
                        observable.id: ObservableResult(
                            request_id=observable.id,
                            values=np.full(3, 5.0),
                            units="m3/s",
                        )
                        for observable in request.observables
                    }
                )

        outputs = {
            "upstream": _output(time="all", observed_values=[1.0, 2.0]),
            "downstream": _output(
                time="all", boundary_id="downstream", observed_values=[1.0, 2.0, 3.0, 4.0]
            ),
        }
        blocks = [{"name": "both", "metric": "rmse", "uses_outputs": ["upstream", "downstream"]}]
        outcome = _evaluator(_TwoSeries(), outputs=outputs, objective_blocks=blocks).evaluate(
            TrialRequest(trial_id=1, values={})
        )

        assert outcome.status == "failed"
        assert "upstream" in (outcome.error or "")

    def test_a_diagnostic_cannot_overwrite_what_the_criterion_says_of_itself(self) -> None:
        """The model reports beside the cost, never over it."""

        class _Loud(_Answers):
            model_id: ClassVar[str] = "test_loud"

            def simulate(self, request: ForwardRequest) -> ForwardOutcome:
                answered = super().simulate(request)
                return ForwardOutcome(
                    observables=answered.observables,
                    diagnostics={"outlet_flow.raw_cost": -999.0},
                )

        outcome = _evaluator(_Loud(value=5.0)).evaluate(TrialRequest(trial_id=1, values={}))

        assert outcome.status == "completed"
        assert outcome.cost == pytest.approx(3.0)
        assert outcome.components["outlet_flow.raw_cost"] == pytest.approx(3.0)
        assert outcome.components["diagnostic.outlet_flow.raw_cost"] == -999.0


class TestTheReferenceModel:
    def test_it_serves_the_two_variables_it_declares_and_refuses_the_others(self) -> None:
        model = forward_registry.create("linear_reservoir")
        requests = requests_for_outputs(
            _config(
                outputs={"outlet_flow": _output(), "level": _output(variable="stage")},
                objective_blocks=[
                    {
                        "name": name,
                        "metric": "rmse",
                        "uses_outputs": [name],
                        "normalize_cost": True,
                    }
                    for name in ("outlet_flow", "level")
                ],
            ).outputs
        )

        with pytest.raises(ValueError, match="stage"):
            model.simulate(ForwardRequest(trial_id=1, values={}, observables=requests))

    def test_one_variable_asked_for_at_two_places_is_refused(self) -> None:
        model = forward_registry.create("linear_reservoir")
        requests = requests_for_outputs(
            _config(
                outputs={
                    "upstream": _output(boundary_id="upstream"),
                    "downstream": _output(boundary_id="downstream"),
                }
            ).outputs
        )

        with pytest.raises(ValueError, match="cannot tell them apart"):
            model.simulate(ForwardRequest(trial_id=1, values={}, observables=requests))

    def test_its_recession_is_the_closed_form_it_documents(self) -> None:
        model = forward_registry.create("linear_reservoir")
        (request,) = requests_for_outputs(_config(outputs={"outlet_flow": _output()}).outputs)

        outcome = model.simulate(
            ForwardRequest(trial_id=1, values={"k": 1e-4}, observables=(request,))
        )

        expected = 1_000_000.0 * math.exp(-1e-4 * 29) * 1e-4
        assert outcome.observables["outlet_flow"].values[-1] == pytest.approx(expected)
        assert outcome.observables["outlet_flow"].units == "m3/d"
