"""A network output's ``time`` reads exactly one state: 'last' or 'first'.

Decision 9 (etude-reseau-observe-2026-09-27.md, option B): 'all' and a list of
dates used to reach the criterion as the whole stack, silently scored at its
last state instead of the one named. Both are refused at configuration load.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibOutputNetwork


def _kwargs(**overrides: object) -> dict[object, object]:
    base: dict[object, object] = {"support": "network", "stream_geometry_path": "streams.gpkg"}
    base.update(overrides)
    return base


def test_default_time_is_last() -> None:
    output = CalibOutputNetwork(**_kwargs())
    assert output.time == "last"


def test_time_last_validates() -> None:
    output = CalibOutputNetwork(**_kwargs(time="last"))
    assert output.time == "last"


def test_time_first_validates() -> None:
    output = CalibOutputNetwork(**_kwargs(time="first"))
    assert output.time == "first"


def test_time_all_is_refused() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CalibOutputNetwork(**_kwargs(time="all"))
    message = str(excinfo.value)
    assert "one state" in message
    assert "'last' or 'first'" in message
    assert "'extent' table" in message


def test_time_list_of_dates_is_refused() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CalibOutputNetwork(**_kwargs(time=["2002-08-31"]))
    message = str(excinfo.value)
    assert "one state" in message
    assert "'last' or 'first'" in message
