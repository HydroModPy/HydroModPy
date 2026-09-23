"""A steady stage is scored on the window its one stamp closes.

A steady run has one stress period, stamped at its end. That stamp alone does
not say where the period starts, so the scorer takes the start from the run's
time grid. Without it the stage was scored against the last day of its
window, one day standing for a whole steady year.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, validate_calib_output
from hydromodpy.calibration.metrics.observable_scoring import ObservableScorer, StationScorer
from hydromodpy.calibration.metrics.series import ObservedSeries, time_grid_boundaries
from hydromodpy.core.contracts.observables import ObservableResult

# 1999 is worth 1.0 a day, 2000 is worth 3.0, 2001 is worth 5.0.
_DAYS = pd.date_range("1999-01-01", "2001-12-31", freq="D")
_RECORD = pd.Series(
    np.select([_DAYS.year == 1999, _DAYS.year == 2000], [1.0, 3.0], default=5.0), index=_DAYS
)
# One steady period over 2000, stamped at its end.
_BOUNDS = (pd.Timestamp("2000-01-01"), pd.Timestamp("2001-01-01"))
_STAMP = pd.DatetimeIndex([_BOUNDS[1]])


def _answer(value: float) -> ObservableResult:
    return ObservableResult(
        request_id="Q", values=np.asarray([value]), units="m3 s-1", times=_STAMP
    )


def test_the_single_metric_route_scores_a_steady_discharge_on_its_year() -> None:
    scorer = StationScorer(
        "discharge", "mae", [ObservedSeries("Q", "discharge", _RECORD)], observed_station_id="Q"
    )

    cost, _ = scorer.score({"Q": _answer(3.0)}, boundaries=_BOUNDS)

    # The year 2000 averages 3.0 exactly. The last day before the stamp is
    # also 3.0 here, so the start has to be checked on a stage it changes.
    assert cost == pytest.approx(0.0)


def test_the_window_start_moves_the_score_of_a_steady_stage() -> None:
    scorer = StationScorer(
        "discharge", "mae", [ObservedSeries("Q", "discharge", _RECORD)], observed_station_id="Q"
    )
    spanning = (pd.Timestamp("1999-01-01"), _BOUNDS[1])

    cost, _ = scorer.score({"Q": _answer(3.0)}, boundaries=spanning)

    # Two years, 1999 at 1.0 and 2000 at 3.0: (365 * 1 + 366 * 3) / 731.
    assert cost == pytest.approx(abs(3.0 - (365 * 1.0 + 366 * 3.0) / 731))


def test_the_weighted_route_takes_the_same_start_from_the_grid() -> None:
    outputs = {
        "Q": validate_calib_output(
            {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observes": "gauge",
            }
        )
    }
    blocks = [CalibObjectiveBlockDecl(name="flow", metric="mae", uses_outputs=["Q"])]
    scorer = ObservableScorer(outputs, blocks, observed_records={"Q": _RECORD})
    grid = SimpleNamespace(setup=SimpleNamespace(time_grid=SimpleNamespace(boundaries=_BOUNDS)))

    with_grid, _ = scorer.score({"Q": _answer(3.0)}, boundaries=time_grid_boundaries(grid))
    without, _ = scorer.score({"Q": _answer(3.0)})

    assert with_grid == pytest.approx(0.0)
    # No grid: the whole record, (365 + 366 * 3 + 365 * 5) / 1096.
    assert without == pytest.approx(abs(3.0 - (365 * 1.0 + 366 * 3.0 + 365 * 5.0) / 1096))


def test_a_steady_head_is_still_read_at_its_stamp() -> None:
    # A head is the state at the stamp: the grid start does not widen it.
    scorer = StationScorer("head", "mae", [ObservedSeries("P", "head", _RECORD)])

    cost, _ = scorer.score({"P": _answer(5.0)}, boundaries=_BOUNDS)

    # The reading AT 2001-01-01 is 5.0; the mean of 2000 would be 3.0.
    assert cost == pytest.approx(0.0)
