"""`evaluated` needs a score window that shares no day with the calibration window."""

from __future__ import annotations

from datetime import date

import pytest

from hydromodpy.results.checks import CalibratedBy, Checks
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.validity_rules import label_for
from tests.unit.results._run_record_factory import WINDOW, make_checks

# The run is scored on 2016-01-01 to 2020-12-31 (WINDOW), 1827 samples.


def _label(calibration: DateWindow, **overrides):
    by = CalibratedBy(session_id="s", trial=3, session_status="completed", window=calibration)
    checks: Checks = make_checks(calibrated_by=by, **overrides)
    return label_for(checks, hydromodpy_version="2.0.0a5", issues=())


def _window(start: tuple[int, int, int], end: tuple[int, int, int]) -> DateWindow:
    return DateWindow(start=date(*start), end=date(*end))


@pytest.mark.parametrize(
    "calibration",
    [
        _window((2017, 1, 1), (2018, 12, 31)),
        _window((2010, 1, 1), (2025, 12, 31)),
        _window((2020, 12, 31), (2022, 12, 31)),
        _window((2012, 1, 1), (2016, 1, 1)),
        _window((2015, 1, 1), (2018, 12, 31)),
    ],
    ids=["inside", "around", "last_day_shared", "first_day_shared", "partial"],
)
def test_overlapping_windows_are_calibrated_with_the_reason(calibration):
    result = _label(calibration)

    assert result.label == "calibrated"
    assert len(result.reasons) == 2
    assert "scored on a window that overlaps the calibration window" in result.reasons[1]
    assert "2016-01-01 to 2020-12-31" in result.reasons[1]
    assert f"{calibration.start} to {calibration.end}" in result.reasons[1]
    assert "1827 samples" in result.reasons[1]


@pytest.mark.parametrize(
    "calibration",
    [
        _window((2010, 1, 1), (2015, 12, 31)),
        _window((2021, 1, 1), (2023, 12, 31)),
    ],
    ids=["day_before", "day_after"],
)
def test_windows_that_share_no_day_are_evaluated(calibration):
    result = _label(calibration)

    assert result.label == "evaluated"
    assert "outside the calibration window" in result.reasons[1]


def test_equal_windows_stay_calibrated_without_an_overlap_reason():
    result = _label(WINDOW)

    assert result.label == "calibrated"
    assert len(result.reasons) == 1
