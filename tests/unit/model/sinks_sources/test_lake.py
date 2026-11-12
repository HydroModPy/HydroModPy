"""Lake forcings (m3/s) are zero or more, the sign MODFLOW 6 LAK reads.

A lake guide once wrote withdrawals as negative values and nothing flipped the sign, so
MODFLOW 6 aborted with 'Withdrawal must be positive'. The config and the build now refuse them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.model.sinks_sources.lake import FlowLakeConfig
from hydromodpy.solver.modflow6.builders._lake_outlets import _emit_forcing_rows

SEASONS = {"DJF": 0.01, "MAM": 0.03, "JJA": 0.05, "SON": 0.02}


def lake(**forcings: object) -> FlowLakeConfig:
    return FlowLakeConfig.model_validate({"initial_stage": 100.0, "bedleak": 1e-6, **forcings})


def constant(value: float) -> dict:
    return {"kind": "constant", "value": value}


NEGATIVE_FORCINGS = [
    pytest.param("rainfall", constant(-0.01), "Lake rainfall = -0.01", id="rainfall"),
    pytest.param("evaporation", constant(-0.01), "Lake evaporation = -0.01", id="evaporation"),
    pytest.param("runoff", constant(-0.01), "Lake runoff = -0.01", id="runoff"),
    pytest.param("inflow", constant(-0.01), "Lake inflow = -0.01", id="inflow"),
    pytest.param("withdrawal", constant(-0.01), "Lake withdrawal = -0.01", id="withdrawal"),
    pytest.param(
        "withdrawal",
        {"kind": "seasonal", "by_season": {**SEASONS, "JJA": -0.05}},
        "Write withdrawal as a positive rate",
        id="negative season",
    ),
    pytest.param(
        "inflow",
        {
            "kind": "piecewise",
            "segments": [
                {"start": "2020-01-01", "forcing": constant(1.0)},
                {"start": "2021-01-01", "forcing": constant(-2.0)},
            ],
        },
        "Lake inflow = -2",
        id="negative segment",
    ),
]


@pytest.mark.parametrize(("keyword", "forcing", "match"), NEGATIVE_FORCINGS)
def test_refusals(keyword, forcing, match):
    with pytest.raises(ValidationError, match=match) as excinfo:
        lake(**{keyword: forcing})

    if forcing["kind"] == "constant":
        assert f"MODFLOW 6 LAK reads {keyword.upper()}" in str(excinfo.value)
        assert "zero or more" in str(excinfo.value)


def test_positive_seasonal_withdrawal():
    config = lake(withdrawal={"kind": "seasonal", "units": "m3/s", "by_season": SEASONS})

    assert config.withdrawal.by_season == SEASONS


def test_negative_value_from_a_file_stops_the_build():
    forcing = {"kind": "values", "values": [0.01, -0.02]}
    with pytest.raises(SolverInputError, match="period 2"):
        _emit_forcing_rows(
            SimpleNamespace(nper=2, inputs=SimpleNamespace(time=SimpleNamespace(grid=None))),
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
