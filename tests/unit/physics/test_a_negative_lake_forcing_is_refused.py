"""MODFLOW 6 LAK reads every lake forcing as zero or more and stops on a negative one.

The lake guide wrote withdrawals as negative values, and nothing flipped the
sign, so MODFLOW 6 aborted with 'Withdrawal must be positive'.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.physics.flow.sinks_sources.lake import FlowLakeConfig
from hydromodpy.solver.modflow6.builders._lake_outlets import _emit_forcing_rows

SEASONS = {"DJF": 0.01, "MAM": 0.03, "JJA": 0.05, "SON": 0.02}


def _lake(**forcings: object) -> FlowLakeConfig:
    return FlowLakeConfig.model_validate({"stageinit": 100.0, "bedleak": 1e-6, **forcings})


@pytest.mark.parametrize("keyword", ["rainfall", "evaporation", "runoff", "inflow", "withdrawal"])
def test_a_negative_constant_forcing_is_refused_with_the_convention(keyword: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _lake(**{keyword: {"kind": "constant", "value": -0.01}})
    message = str(excinfo.value)
    assert f"Lake {keyword} = -0.01" in message
    assert f"MODFLOW 6 LAK reads {keyword.upper()}" in message
    assert "zero or more" in message


def test_a_negative_season_of_a_withdrawal_is_refused() -> None:
    with pytest.raises(ValidationError, match="Write withdrawal as a positive rate"):
        _lake(withdrawal={"kind": "seasonal", "by_season": {**SEASONS, "JJA": -0.05}})


def test_a_negative_segment_of_a_piecewise_inflow_is_refused() -> None:
    with pytest.raises(ValidationError, match="Lake inflow = -2"):
        _lake(
            inflow={
                "kind": "piecewise",
                "segments": [
                    {"start": "2020-01-01", "forcing": {"kind": "constant", "value": 1.0}},
                    {"start": "2021-01-01", "forcing": {"kind": "constant", "value": -2.0}},
                ],
            }
        )


def test_a_positive_seasonal_withdrawal_is_accepted() -> None:
    lake = _lake(withdrawal={"kind": "seasonal", "units": "m3/s", "by_season": SEASONS})
    assert lake.withdrawal.by_season == SEASONS


def test_a_negative_value_read_from_a_file_stops_the_build() -> None:
    forcing = {"kind": "values", "values": [0.01, -0.02]}
    with pytest.raises(SolverInputError, match="period 2"):
        _emit_forcing_rows(
            SimpleNamespace(nper=2, time_grid=None),
            lake_index=0,
            lake_id="lac0",
            keyword="withdrawal",
            forcing=forcing,
            volumetric=True,
            mode="inline",
            min_periods=120,
            nper=2,
            period_rows={},
            ts_series=[],
        )
