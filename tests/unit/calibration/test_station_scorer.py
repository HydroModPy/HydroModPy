"""The single-metric route is scored without a trial context.

``variable`` + ``objective`` used to be one function that resolved the flow
adapter, placed every gauge on the mesh, read its series and scored it. The
second half is :class:`StationScorer`, and these hold what that separation is
worth: the same observables score to the same cost whoever produced them, a
model that is not the pipeline included.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.metrics.composite import PRODUCERS, build_metric_extractor
from hydromodpy.calibration.metrics.observable_scoring import StationScorer
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.core.contracts.observables import ObservableResult

_INDEX = pd.date_range("2020-01-01", periods=3, freq="D")


def _observed(station_id: str, values, variable: str = "head") -> ObservedSeries:
    return ObservedSeries(
        station_id=station_id,
        variable=variable,
        series=pd.Series(np.asarray(values, dtype=float), index=_INDEX[: len(values)]),
    )


def _answer(station_id: str, values, *, dated: bool = True) -> ObservableResult:
    array = np.asarray(values, dtype=float)
    return ObservableResult(
        request_id=station_id,
        values=array,
        units="m",
        times=_INDEX[: array.size] if dated else None,
    )


class TestTheProducersAndTheScorerNameTheSameVariables:
    def test_every_produced_variable_is_a_scored_one(self) -> None:
        """A route one half serves and the other does not is a KeyError at trial time."""
        assert set(PRODUCERS) == set(StationScorer.SUPPORTED)

    def test_a_variable_nothing_observes_is_refused_at_construction(self) -> None:
        with pytest.raises(NotImplementedError, match="is not supported"):
            StationScorer("salinity", "rmse", [_observed("A", [1.0, 2.0, 3.0])])


class TestScoringWithoutAContext:
    def test_a_head_answer_is_scored_with_no_trial_context_in_sight(self) -> None:
        scorer = StationScorer("head", "rmse", [_observed("PZ1", [10.0, 11.0, 12.0])])

        cost, components = scorer.score({"PZ1": _answer("PZ1", [10.5, 11.5, 12.5])})

        assert cost == pytest.approx(0.5)
        assert components == {"cost:rmse@PZ1": pytest.approx(0.5)}

    def test_the_criterion_named_by_the_document_is_the_one_applied(self) -> None:
        """Changing the metric alone moves the number; the answer is untouched."""
        observed = [_observed("PZ1", [10.0, 11.0, 12.0])]
        answer = {"PZ1": _answer("PZ1", [10.5, 12.5, 12.5])}

        rmse, _ = StationScorer("head", "rmse", observed).score(answer)
        mae, _ = StationScorer("head", "mae", observed).score(answer)

        assert rmse != pytest.approx(mae)

    def test_several_heads_are_averaged(self) -> None:
        scorer = StationScorer(
            "head",
            "rmse",
            [_observed("PZ1", [10.0, 11.0, 12.0]), _observed("PZ2", [10.0, 11.0, 12.0])],
        )

        cost, components = scorer.score(
            {
                "PZ1": _answer("PZ1", [10.5, 11.5, 12.5]),
                "PZ2": _answer("PZ2", [11.5, 12.5, 13.5]),
            }
        )

        assert components["cost:rmse@PZ1"] == pytest.approx(0.5)
        assert components["cost:rmse@PZ2"] == pytest.approx(1.5)
        assert cost == pytest.approx(1.0)

    def test_a_burn_in_reaches_the_criterion(self) -> None:
        plain = StationScorer("head", "rmse", [_observed("PZ1", [10.0, 11.0, 12.0])])
        burnt = StationScorer(
            "head", "rmse", [_observed("PZ1", [10.0, 11.0, 12.0])], warmup_periods=2
        )
        answer = {"PZ1": _answer("PZ1", [13.0, 11.0, 12.0])}

        assert plain.score(answer)[0] > 0.0
        assert burnt.score(answer)[0] == pytest.approx(0.0)


class TestWhichStationDrivesTheSearch:
    def test_the_declared_gauge_is_the_cost_and_the_others_stay_reported(self) -> None:
        scorer = StationScorer(
            "discharge",
            "rmse",
            [
                _observed("OUTLET", [1.0, 1.0, 1.0], variable="discharge"),
                _observed("UP", [1.0, 1.0, 1.0], variable="discharge"),
            ],
            observed_station_id="UP",
        )

        cost, components = scorer.score(
            {
                "OUTLET": _answer("OUTLET", [9.0, 9.0, 9.0]),
                "UP": _answer("UP", [2.0, 2.0, 2.0]),
            }
        )

        assert scorer.target_station_id == "UP"
        assert cost == pytest.approx(1.0)
        assert components["cost:rmse@OUTLET"] == pytest.approx(8.0)

    def test_a_head_route_follows_no_single_station(self) -> None:
        assert StationScorer("head", "rmse", [_observed("PZ1", [1.0])]).target_station_id is None

    def test_a_missing_answer_for_the_followed_gauge_is_refused_by_name(self) -> None:
        scorer = StationScorer(
            "discharge",
            "rmse",
            [
                _observed("OUTLET", [1.0, 1.0, 1.0], variable="discharge"),
                _observed("UP", [1.0, 1.0, 1.0], variable="discharge"),
            ],
            observed_station_id="UP",
        )

        with pytest.raises(NotImplementedError, match="'UP'"):
            scorer.score({"OUTLET": _answer("OUTLET", [9.0, 9.0, 9.0])})

    def test_a_gauge_the_producer_could_not_place_stays_unscored(self) -> None:
        """A piezometer outside the mesh has no counterpart; it is not invented."""
        scorer = StationScorer(
            "head",
            "rmse",
            [_observed("PZ1", [10.0, 11.0, 12.0]), _observed("NOWHERE", [10.0, 11.0, 12.0])],
        )

        cost, components = scorer.score({"PZ1": _answer("PZ1", [10.5, 11.5, 12.5])})

        assert cost == pytest.approx(0.5)
        assert "cost:rmse@NOWHERE" not in components

    def test_a_gauge_left_out_is_said_out_loud_once(self, caplog) -> None:
        """A station that vanishes from a report has to leave a line somewhere."""
        scorer = StationScorer(
            "head",
            "rmse",
            [_observed("PZ1", [10.0, 11.0, 12.0]), _observed("NOWHERE", [10.0, 11.0, 12.0])],
        )
        answer = {"PZ1": _answer("PZ1", [10.5, 11.5, 12.5])}

        with caplog.at_level("WARNING"):
            scorer.score(answer, source="Solver 'modflow6'")
            scorer.score(answer, source="Solver 'modflow6'")

        said = [record for record in caplog.records if "NOWHERE" in record.getMessage()]
        assert len(said) == 1
        assert "head" in said[0].getMessage()

    def test_an_answer_nobody_could_score_says_so(self) -> None:
        scorer = StationScorer("head", "rmse", [_observed("PZ1", [10.0, 11.0, 12.0])])

        with pytest.raises(ValueError, match="No finite head calibration costs"):
            scorer.score({})

    def test_an_empty_series_is_refused_and_names_its_source(self) -> None:
        scorer = StationScorer("lake_level", "rmse", [_observed("lac0", [10.0, 11.0, 12.0])])

        with pytest.raises(NotImplementedError, match="fake_solver"):
            scorer.score({"lac0": _answer("lac0", [], dated=False)}, source="fake_solver")


class TestThePipelineTakesTheSameRoute:
    """The extractor scores through the scorer, not beside it."""

    @staticmethod
    def _ctx():
        """A project loading one gauge, and no runoff to add to the budget."""
        frame = pd.DataFrame({"datetime": _INDEX, "value": [1.0, 1.0, 1.0]})
        record = SimpleNamespace(station_id="OUTLET", variable="discharge", data=frame)
        return SimpleNamespace(
            setup=SimpleNamespace(mesh_planar=None, domain=None, geographic=None, time_grid=None),
            loaded_data=SimpleNamespace(
                hydrometry=SimpleNamespace(points=[record]),
                piezometry=None,
                runoff=None,
            ),
        )

    @staticmethod
    def _adapter(served):
        class _Adapter:
            def extract_observables(self, ctx, store, requests, *, time_index=None):
                del ctx, store, time_index
                return {request.id: served[request.id] for request in requests}

        return _Adapter()

    def test_the_extractor_reports_what_a_bare_scorer_reports(self, monkeypatch) -> None:
        """The discharge route is the one whose producer rewrites its values."""
        served = {"_catchment": _answer("_catchment", [2.0, 2.0, 2.0])}
        monkeypatch.setattr(
            "hydromodpy.calibration.metrics.composite.resolve_flow_adapter",
            lambda ctx: (
                self._adapter(served),
                SimpleNamespace(run=SimpleNamespace(solver="modflow6")),
            ),
        )
        ctx = self._ctx()
        metric_fn = build_metric_extractor("discharge", "rmse", ctx)

        through_pipeline = metric_fn(ctx, objective="rmse", variable="discharge")
        bare = StationScorer(
            "discharge", "rmse", [_observed("OUTLET", [1.0, 1.0, 1.0], "discharge")]
        ).score({"OUTLET": _answer("OUTLET", [2.0, 2.0, 2.0])})

        assert through_pipeline == bare
        assert through_pipeline[0] == pytest.approx(1.0)

    def test_a_trial_may_not_rename_the_criterion_it_is_scored_on(self, monkeypatch) -> None:
        """The records, the producer and the followed gauge were all chosen here."""
        served = {"_catchment": _answer("_catchment", [2.0, 2.0, 2.0])}
        monkeypatch.setattr(
            "hydromodpy.calibration.metrics.composite.resolve_flow_adapter",
            lambda ctx: (
                self._adapter(served),
                SimpleNamespace(run=SimpleNamespace(solver="modflow6")),
            ),
        )
        ctx = self._ctx()
        metric_fn = build_metric_extractor("discharge", "rmse", ctx)

        with pytest.raises(ValueError, match="Build a second extractor"):
            metric_fn(ctx, objective="nse", variable="discharge")

    def test_a_trial_may_not_rename_the_variable_either(self, monkeypatch) -> None:
        served = {"_catchment": _answer("_catchment", [2.0, 2.0, 2.0])}
        monkeypatch.setattr(
            "hydromodpy.calibration.metrics.composite.resolve_flow_adapter",
            lambda ctx: (
                self._adapter(served),
                SimpleNamespace(run=SimpleNamespace(solver="modflow6")),
            ),
        )
        ctx = self._ctx()
        metric_fn = build_metric_extractor("discharge", "rmse", ctx)

        with pytest.raises(ValueError, match="variable='head'"):
            metric_fn(ctx, objective="rmse", variable="head")


class TestWhenTheRefusalHappens:
    """A document no sample can score is refused before a session exists."""

    @staticmethod
    def _two_gauges():
        frame = pd.DataFrame({"datetime": _INDEX, "value": [1.0, 1.0, 1.0]})
        points = [
            SimpleNamespace(station_id=sid, variable="discharge", data=frame)
            for sid in ("OUTLET", "UP")
        ]
        return SimpleNamespace(
            setup=SimpleNamespace(time_grid=None),
            loaded_data=SimpleNamespace(hydrometry=SimpleNamespace(points=points)),
        )

    def test_two_gauges_without_a_declaration_are_refused_at_build_time(self) -> None:
        """Every trial used to fail instead, after a session row had been written."""
        with pytest.raises(ValueError, match="one simulated discharge series"):
            build_metric_extractor("discharge", "rmse", self._two_gauges())

    def test_naming_the_one_that_drives_the_search_builds(self) -> None:
        extractor = build_metric_extractor(
            "discharge", "rmse", self._two_gauges(), observed_station_id="UP"
        )

        assert callable(extractor)
