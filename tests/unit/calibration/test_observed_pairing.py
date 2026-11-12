"""Observed records paired with simulated outputs on one stress-period grid.

Discharge records are in m3/s and heads in m. An output names the station it
observes, and its record is read once per variable family.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.calibration.metrics.observed_pairing import (
    observed_series_for_outputs,
    pair_outputs_with_observations,
)


def test_records_loaded_once_per_family() -> None:
    records = [
        SimpleNamespace(
            station_id=name,
            variable="discharge",
            data=pd.DataFrame({"datetime": pd.to_datetime(["2000-01-01"]), "value": [value]}),
        )
        for name, value in (("A", 1.0), ("B", 2.0))
    ]
    ctx = SimpleNamespace(loaded_data=SimpleNamespace(hydrometry=SimpleNamespace(points=records)))
    outputs = {
        "qa": SimpleNamespace(observes="A", variable="discharge"),
        "qb": SimpleNamespace(observes="B", variable="discharge"),
    }

    series = observed_series_for_outputs(outputs, ctx)

    assert {name: values.tolist() for name, values in series.items()} == {"qa": [1.0], "qb": [2.0]}


def test_unknown_variable_refused() -> None:
    outputs = {"x": SimpleNamespace(observes="S1", variable="porosity")}

    with pytest.raises(ValueError, match="output 'x' observes 'S1' but its variable 'porosity'"):
        observed_series_for_outputs(outputs, SimpleNamespace())


def test_undated_record_refused() -> None:
    times = pd.date_range("2000-01-01", periods=2, freq="D")

    with pytest.raises(ValueError, match="the record runs over no dated sample"):
        pair_outputs_with_observations(
            observed={"q": pd.Series(dtype=float)},
            simulated={"q": pd.Series([1.0, 2.0], index=times)},
        )
