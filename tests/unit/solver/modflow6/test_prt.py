"""PRT release and tracking times are written in days and handed to MODFLOW 6 in its own time unit.

A value in days is multiplied by 86 400 s/day and divided by the seconds in one unit of the
TDIS. A model that declares no unit runs in the launcher unit, seconds, so the days become
seconds and a wrong fallback never shifts a time by 86 400.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.solver.modflow6.prt import Modflow6Prt, _regular_track_times_days


def _prt(time_units) -> Modflow6Prt:
    prt = object.__new__(Modflow6Prt)
    tdis = None if time_units is None else SimpleNamespace(time_units=time_units)
    prt.model_modflow = SimpleNamespace(tdis=tdis)
    return prt


class _Data:
    """A FloPy option block, read with ``get_data``."""

    def __init__(self, value: str) -> None:
        self._value = value

    def get_data(self) -> str:
        return self._value


# One row per TDIS unit: the unit in seconds, and what 10 days become in that unit.
_UNITS = [
    pytest.param("SECONDS", 1.0, 864000.0, id="seconds"),
    pytest.param("MINUTES", 60.0, 14400.0, id="minutes"),
    pytest.param("HOURS", 3600.0, 240.0, id="hours"),
    pytest.param("DAYS", 86400.0, 10.0, id="days"),
    pytest.param("YEARS", 31557600.0, 10.0 / 365.25, id="years"),
    pytest.param("days", 86400.0, 10.0, id="lower_case"),
]


@pytest.mark.parametrize(("token", "seconds", "ten_days"), _UNITS)
def test_days_in_tdis_unit(token, seconds, ten_days) -> None:
    prt = _prt(token)

    assert prt._model_time_unit_seconds() == seconds
    assert prt._days_to_model_time(10.0) == pytest.approx(ten_days, rel=1e-12)


def test_flopy_block_read_by_get_data() -> None:
    assert _prt(_Data("DAYS"))._model_time_unit_seconds() == 86400.0


# One row per model that declares no usable unit: it runs in the launcher unit, seconds.
_UNDECLARED = [
    pytest.param("UNKNOWN", id="unknown_token"),
    pytest.param("", id="empty_token"),
    pytest.param(None, id="no_tdis"),
]


@pytest.mark.parametrize("token", _UNDECLARED)
def test_undeclared_unit_is_seconds(token) -> None:
    prt = _prt(token)

    assert prt._model_time_unit_seconds() == 1.0
    assert prt._days_to_model_time(1.0) == 86400.0


# One row per declared token that is no time unit: PRT refuses it.
_REFUSED = [
    pytest.param("FORTNIGHTS", id="fortnights_is_refused"),
    pytest.param("DAYZ", id="misspelled_days_is_refused"),
]


@pytest.mark.parametrize("token", _REFUSED)
def test_unit_refusals(token) -> None:
    with pytest.raises(SolverInputError, match=token):
        _prt(token)._model_time_unit_seconds()


def test_no_time_stays_no_time() -> None:
    assert _prt("DAYS")._days_to_model_time(None) is None


# One row per regular tracking: step and stop in days, and the times asked.
_TRACK_TIMES = [
    pytest.param(None, 30.0, None, id="no_step"),
    pytest.param(10.0, 30.0, [0.0, 10.0, 20.0, 30.0], id="whole_steps"),
    pytest.param(10.0, 25.0, [0.0, 10.0, 20.0, 25.0], id="last_step_is_cut_at_the_stop"),
    pytest.param(0.1, 0.3, [0.0, 0.1, 0.2, 0.3], id="rounding_does_not_lose_the_stop"),
]


@pytest.mark.parametrize(("step", "stop", "expected"), _TRACK_TIMES)
def test_regular_track_times(step, stop, expected) -> None:
    times = _regular_track_times_days(stop_time=stop, track_time_step=step)

    if expected is None:
        assert times is None
    else:
        assert times == pytest.approx(expected)
        assert times[-1] == pytest.approx(stop, abs=1e-9)


# One row per refusal: step, stop and what the message says.
_TRACK_REFUSED = [
    pytest.param(10.0, None, "requires stop_time", id="no_stop"),
    pytest.param(0.0, 30.0, "must be positive", id="zero_step"),
    pytest.param(-1.0, 30.0, "must be positive", id="negative_step"),
    pytest.param(10.0, 0.0, "stop_time must be positive", id="zero_stop"),
]


@pytest.mark.parametrize(("step", "stop", "message"), _TRACK_REFUSED)
def test_track_time_refusals(step, stop, message) -> None:
    with pytest.raises(ValueError, match=message):
        _regular_track_times_days(stop_time=stop, track_time_step=step)
