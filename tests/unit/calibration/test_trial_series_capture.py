"""Series a trial records while it is scored, on monthly stress periods.

Each row holds the output, the station, the period stamp, and the simulated and
observed values (m3/s). The rows must be the pairs the scorer reduced to a cost.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config_outputs import CalibOutputPoint
from hydromodpy.calibration.metrics.observable_scoring import ObservableScorer, StationBlockScorer
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink
from hydromodpy.core.time.period_aggregation import period_edges
from hydromodpy.results.derive.time_alignment import align_observed_simulated
from tests.unit.calibration._factories_scoring import adapter_result, objective_block

STATION = "G1"
TIMES = pd.date_range("2001-01-31", periods=4, freq="ME")
BOUNDARIES = period_edges(TIMES, start=pd.Timestamp("2000-12-31"))
OBSERVED = pd.Series([1.0, 2.0, 3.0, 4.0], index=TIMES, name=STATION)
SIMULATED = OBSERVED.to_numpy() * 0.9 + 0.1

# The alignment both scorers reduce to a cost from. The first stamp does not
# close a period on these boundaries, so 3 of the 4 stamps are scored.
EXPECTED_PAIR = align_observed_simulated(
    OBSERVED, pd.Series(SIMULATED, index=TIMES), method="mean", start=BOUNDARIES[0]
)


def station_scorer(sink: TrialSeriesSink) -> StationBlockScorer:
    records = [ObservedSeries(station_id=STATION, variable="discharge", series=OBSERVED)]
    return StationBlockScorer("discharge", "nse_log", records, series_sink=sink)


def composite_scorer(sink: TrialSeriesSink) -> ObservableScorer:
    output = CalibOutputPoint.model_validate(
        {"variable": "discharge", "support": "point", "observes": STATION}
    )
    block = objective_block("hydrograph", "nse_log", ["gauge"])
    return ObservableScorer(
        {"gauge": output}, [block], observed_records={"gauge": OBSERVED}, series_sink=sink
    )


@pytest.mark.parametrize(
    ("make_scorer", "key", "output"),
    [
        pytest.param(station_scorer, STATION, f"discharge@{STATION}", id="station route"),
        pytest.param(composite_scorer, "gauge", "gauge", id="composite route"),
    ],
)
def test_recorded_series_are_the_scored_pairs(make_scorer, key, output) -> None:
    sink = TrialSeriesSink()
    scorer = make_scorer(sink)

    scorer.score(
        {key: adapter_result(key, SIMULATED, "m3 s-1", times=TIMES)}, boundaries=BOUNDARIES
    )

    rows = sink.drain()
    n_pairs = len(EXPECTED_PAIR)
    assert [row["station"] for row in rows] == [STATION] * n_pairs
    assert [row["output"] for row in rows] == [output] * n_pairs
    assert [row["time"] for row in rows] == list(EXPECTED_PAIR.index)
    np.testing.assert_allclose([row["simulated"] for row in rows], EXPECTED_PAIR["sim"])
    np.testing.assert_allclose([row["observed"] for row in rows], EXPECTED_PAIR["obs"])
