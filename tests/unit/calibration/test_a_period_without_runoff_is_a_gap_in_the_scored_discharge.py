"""A period the runoff forcing does not cover is a gap, not baseflow only.

``period_mean_on_index`` answers NaN for a period holding no runoff sample.
Adding that NaN as zero scored the drain baseflow alone against a total
streamflow observation, the apples-to-oranges the runoff addition exists to
remove. The summed discharge is a gap there, and the score drops the pair.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.calibration.metrics import series as series_module
from hydromodpy.calibration.metrics.series import add_runoff_to_discharge
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord

# 1 mm/day over 86.4 km2 is exactly 1 m3/s.
_CATCH_AREA_KM2 = 86.4
_SIM_INDEX = pd.DatetimeIndex(["2000-01-11", "2000-01-21", "2000-02-20"])


def _runoff_ending_before_the_last_period() -> LoadResult:
    days = pd.date_range("2000-01-01", "2000-01-20", freq="D")
    values = np.full((days.size, 1, 1), 2.0)
    dataset = xr.Dataset(
        {"runoff": (("time", "y", "x"), values)},
        coords={"time": days, "y": [0.5], "x": [0.5]},
    )
    record = FieldRecord(
        variable="runoff",
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


def _context(runoff: LoadResult) -> SimpleNamespace:
    return SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=runoff),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=_CATCH_AREA_KM2)),
    )


@pytest.fixture(autouse=True)
def _fresh_warnings(monkeypatch):
    monkeypatch.setattr(series_module, "_RUNOFF_WARNING_EMITTED", set())


def test_a_period_without_runoff_is_a_gap_in_the_scored_discharge() -> None:
    baseflow = pd.Series([0.4, 0.7, 1.1], index=_SIM_INDEX, name="discharge")

    scored = add_runoff_to_discharge(baseflow, _context(_runoff_ending_before_the_last_period()))

    assert scored.iloc[:2].tolist() == pytest.approx([2.4, 2.7])
    assert np.isnan(scored.iloc[2])


def test_the_periods_that_lost_their_runoff_are_counted_once(caplog) -> None:
    baseflow = pd.Series([0.4, 0.7, 1.1], index=_SIM_INDEX, name="discharge")
    context = _context(_runoff_ending_before_the_last_period())

    with caplog.at_level(logging.WARNING, logger=series_module.__name__):
        add_runoff_to_discharge(baseflow, context)
        add_runoff_to_discharge(baseflow, context)

    messages = [r.getMessage() for r in caplog.records if "no runoff" in r.getMessage()]
    assert len(messages) == 1
    assert "1 of 3" in messages[0]
