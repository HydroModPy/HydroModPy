"""``[calibration.aggregate] min_samples`` holds on every output that is scored against a record.

Since the single route, a point, a cell, a boundary, a lake and the implicit
output of ``variable`` + ``objective`` are all paired by the same function, so
the same floor applies to each. An output scored on fewer pairs than the floor
is refused by name; on as many, it is scored. The default floor stays 1.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import (
    CalibAggregateDecl,
    CalibObjectiveBlockDecl,
    validate_calib_output,
)
from hydromodpy.calibration.metrics.observable_scoring import (
    ObservableScorer,
    StationBlockScorer,
)
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.core.contracts.observables import ObservableResult

_RECORD_DAYS = pd.date_range("2000-01-01", "2000-03-31", freq="D")
_RECORD = pd.Series(np.linspace(1.0, 2.0, len(_RECORD_DAYS)), index=_RECORD_DAYS)
_STAMPS = pd.date_range("2000-01-02", periods=6, freq="D")
_BOUNDS = (pd.Timestamp("2000-01-01"), *_STAMPS)

SUPPORTS: dict[str, dict[str, Any]] = {
    "point": {"variable": "head", "support": "point"},
    "cell": {"variable": "discharge", "support": "cell", "row": 0, "col": 0, "layer": 0},
    "boundary": {"variable": "discharge", "support": "boundary", "boundary_id": "outlet"},
    "lake": {"variable": "stage", "support": "lake", "lake_id": "L1"},
}


def _answer(name: str) -> ObservableResult:
    return ObservableResult(
        request_id=name, values=np.linspace(1.0, 1.1, len(_STAMPS)), units="-", times=_STAMPS
    )


def _scorer(support: str, min_samples: int) -> ObservableScorer:
    outputs = {"Y": validate_calib_output({**SUPPORTS[support], "observes": "G"})}
    blocks = [CalibObjectiveBlockDecl(name="fit", metric="rmse", uses_outputs=["Y"])]
    return ObservableScorer(
        outputs, blocks, observed_records={"Y": _RECORD}, min_samples=min_samples
    )


def test_the_default_floor_is_one_pair() -> None:
    assert CalibAggregateDecl().min_samples == 1


@pytest.mark.parametrize("support", sorted(SUPPORTS))
def test_an_output_paired_on_fewer_than_the_floor_is_refused(support: str) -> None:
    scorer = _scorer(support, min_samples=len(_STAMPS) + 1)

    with pytest.raises(ValueError, match="min_samples"):
        scorer.score({"Y": _answer("Y")}, boundaries=_BOUNDS)


@pytest.mark.parametrize("support", sorted(SUPPORTS))
def test_an_output_paired_on_the_floor_is_scored(support: str) -> None:
    scorer = _scorer(support, min_samples=len(_STAMPS))

    cost, components = scorer.score({"Y": _answer("Y")}, boundaries=_BOUNDS)

    assert np.isfinite(cost)
    assert components["Y.n_paired"] == len(_STAMPS)


@pytest.mark.parametrize("variable", ["discharge", "head", "lake_level"])
def test_the_implicit_station_output_honours_the_floor(variable: str) -> None:
    record = [ObservedSeries("G", variable, _RECORD)]

    refused = StationBlockScorer(
        variable, "rmse", record, observed_station_id="G", min_samples=len(_STAMPS) + 1
    )
    with pytest.raises(ValueError, match="min_samples"):
        refused.score({"G": _answer("G")}, boundaries=_BOUNDS)

    kept = StationBlockScorer(
        variable, "rmse", record, observed_station_id="G", min_samples=len(_STAMPS)
    )
    cost, _ = kept.score({"G": _answer("G")}, boundaries=_BOUNDS)
    assert np.isfinite(cost)
