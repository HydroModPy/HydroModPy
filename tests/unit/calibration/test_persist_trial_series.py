"""persist_trial_series: opt-in, off by default, and a real capture at scoring time.

Three layers are covered without a solver, the way
``test_the_protocol_s_block_route_matches_the_single_metric_one.py`` scores
both routes on a synthetic series:

1. The key defaults off.
2. :class:`TrialSeriesSink` records and drains, per thread.
3. Both scorers (``StationScorer``, the single-metric route; ``ObservableScorer``,
   the composite route) record into a sink they are built with, as a side effect
   of scoring the same series they already align to compute a cost.
4. :class:`PipelineTrialEvaluator` creates a sink only when the key is on, and
   only when it builds its own extractor: a caller-supplied ``metric_fn`` never
   sees one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibOutputPoint,
    CalibrationConfig,
    validate_calib_output,
)
from hydromodpy.calibration.metrics.observable_scoring import ObservableScorer, StationScorer
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink
from hydromodpy.calibration.runners.pipeline_evaluator import PipelineTrialEvaluator
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.time.period_aggregation import period_edges
from hydromodpy.results.derive.time_alignment import align_observed_simulated

STATION = "G1"
TIMES = pd.date_range("2001-01-31", periods=4, freq="ME")
BOUNDARIES = period_edges(TIMES, start=pd.Timestamp("2000-12-31"))
OBSERVED = pd.Series([1.0, 2.0, 3.0, 4.0], index=TIMES, name=STATION)
SIMULATED = OBSERVED.to_numpy() * 0.9 + 0.1
# Ground truth: the same alignment both scorers reduce to a cost from, so the
# sink is checked against what was actually scored, not a re-guessed index.
EXPECTED_PAIR = align_observed_simulated(
    OBSERVED, pd.Series(SIMULATED, index=TIMES), method="mean", start=BOUNDARIES[0]
)


def test_the_key_defaults_off() -> None:
    assert CalibrationConfig().persist_trial_series is False


def test_a_sink_drains_only_what_was_recorded_on_the_calling_thread() -> None:
    sink = TrialSeriesSink()
    sink.record(
        output="q", station=STATION, times=TIMES[:2], simulated=[1.0, 2.0], observed=[1.1, 2.1]
    )

    rows = sink.drain()

    assert len(rows) == 2
    assert rows[0] == {
        "output": "q",
        "station": STATION,
        "time": TIMES[0],
        "simulated": 1.0,
        "observed": 1.1,
    }
    # Drained: a second call sees nothing left over from the first.
    assert sink.drain() == []


def test_the_single_metric_route_records_the_series_it_scored() -> None:
    sink = TrialSeriesSink()
    scorer = StationScorer(
        "discharge",
        "nse_log",
        [ObservedSeries(station_id=STATION, variable="discharge", series=OBSERVED)],
        series_sink=sink,
    )

    scorer.score(
        {
            STATION: ObservableResult(
                request_id=STATION, values=SIMULATED, units="m3 s-1", times=TIMES
            )
        },
        boundaries=BOUNDARIES,
    )

    rows = sink.drain()
    # One edge sample does not close a period on this boundary set (same
    # alignment ``test_the_protocol_s_block_route_matches_the_single_metric_one``
    # notes): 3 of the 4 stamps are the ones actually scored.
    assert [row["station"] for row in rows] == [STATION] * len(EXPECTED_PAIR)
    assert [row["output"] for row in rows] == ["discharge"] * len(EXPECTED_PAIR)
    assert [row["time"] for row in rows] == list(EXPECTED_PAIR.index)
    np.testing.assert_allclose([row["simulated"] for row in rows], EXPECTED_PAIR["sim"])
    np.testing.assert_allclose([row["observed"] for row in rows], EXPECTED_PAIR["obs"])


def test_the_composite_route_records_the_series_keyed_by_output_and_station() -> None:
    sink = TrialSeriesSink()
    output = CalibOutputPoint.model_validate(
        {"variable": "discharge", "support": "point", "observes": STATION}
    )
    block = CalibObjectiveBlockDecl(name="hydrograph", metric="nse_log", uses_outputs=["gauge"])
    scorer = ObservableScorer(
        {"gauge": output}, [block], observed_records={"gauge": OBSERVED}, series_sink=sink
    )

    scorer.score(
        {
            "gauge": ObservableResult(
                request_id="gauge", values=SIMULATED, units="m3 s-1", times=TIMES
            )
        },
        boundaries=BOUNDARIES,
    )

    rows = sink.drain()
    assert [row["output"] for row in rows] == ["gauge"] * len(EXPECTED_PAIR)
    assert [row["station"] for row in rows] == [STATION] * len(EXPECTED_PAIR)
    assert [row["time"] for row in rows] == list(EXPECTED_PAIR.index)
    np.testing.assert_allclose([row["simulated"] for row in rows], EXPECTED_PAIR["sim"])
    np.testing.assert_allclose([row["observed"] for row in rows], EXPECTED_PAIR["obs"])


def test_a_network_output_never_reaches_the_sink() -> None:
    sink = TrialSeriesSink()
    output = validate_calib_output({"support": "network", "observed_network": "data.hydrography"})
    block = CalibObjectiveBlockDecl(name="net", metric="distance_gap", uses_outputs=["net"])
    scorer = ObservableScorer({"net": output}, [block], series_sink=sink)

    scorer.score({}, network_values={"net": [12.0, 20.0]})

    assert sink.drain() == []


class TestThePipelineEvaluatorWiring:
    def test_a_sink_is_built_only_when_the_key_is_on(self) -> None:
        on = CalibrationConfig.model_validate({"persist_trial_series": True})
        off = CalibrationConfig()
        metric_fn = lambda ctx, **kwargs: (0.0, {})  # noqa: E731 - bypasses _extractor_for

        evaluator_on = PipelineTrialEvaluator(cfg=on, trial_ctx=object(), metric_fn=metric_fn)
        evaluator_off = PipelineTrialEvaluator(cfg=off, trial_ctx=object(), metric_fn=metric_fn)

        assert isinstance(evaluator_on.trial_series_sink, TrialSeriesSink)
        assert evaluator_off.trial_series_sink is None

    def test_a_caller_supplied_metric_fn_is_used_as_is_not_wrapped(self) -> None:
        on = CalibrationConfig.model_validate({"persist_trial_series": True})
        metric_fn = lambda ctx, **kwargs: (0.0, {})  # noqa: E731

        evaluator = PipelineTrialEvaluator(cfg=on, trial_ctx=object(), metric_fn=metric_fn)

        # A sink exists (read by the caller after evaluate()), but building the
        # extractor that would feed it is skipped: the caller's own callable runs
        # unmodified, so it never has to know the sink exists.
        assert isinstance(evaluator.trial_series_sink, TrialSeriesSink)
        assert evaluator._metric_fn is metric_fn
